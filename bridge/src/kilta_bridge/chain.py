"""Model fallback chain: Gemini Flash -> Groq -> Gemini Flash-Lite -> Ollama.

A link is retried with exponential backoff on rate limits, 5xx and timeouts. Any other error
(bad key, unknown model) skips straight to the next link. Once a link has started streaming
we cannot switch, so a mid-stream failure is raised.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import AsyncGenerator, AsyncIterable, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
from strands.models.model import Model
from strands.types.exceptions import ModelThrottledException

from .config import Settings

log = logging.getLogger("kilta.chain")

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
RETRYABLE_TEXT = re.compile(
    r"\b(429|408|50[0234])\b|UNAVAILABLE|RESOURCE_EXHAUSTED|rate.?limit|overloaded|"
    r"high demand|timed? ?out",
    re.IGNORECASE,
)

# Gemini's free tier answers a spent daily quota with "Please retry in 8h56m12.35s". Retrying
# that is pointless, so it is not retried and the model is skipped for that long (capped).
RETRY_IN = re.compile(
    r"retry in\s*(?:(\d+)h)?\s*(?:(\d+)m)?\s*(?:(\d+(?:\.\d+)?)s)?", re.IGNORECASE
)
RETRY_DELAY = re.compile(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s")
LONG_WAIT_S = 120.0  # a wait longer than this is not worth a retry
MAX_SKIP_S = 6 * 3600.0

EventSink = Callable[[dict[str, Any]], None]


class AllModelsFailed(Exception):
    """Every link in the chain failed before producing a response."""

    def __init__(self, attempts: list[dict[str, Any]]) -> None:
        self.attempts = attempts
        tried = ", ".join(f"{a['model']}: {a['error']}" for a in attempts)
        super().__init__(f"all models failed ({tried})")


class FirstTokenTimeout(TimeoutError):
    pass


def quota_delay(error: BaseException) -> float | None:
    """Seconds until a spent quota resets, if the error says it is a long wait (else None)."""
    parts: list[str] = []
    current: BaseException | None = error
    while current is not None and len(parts) < 6:
        parts.append(f"{current} {getattr(current, 'details', '')}")
        current = current.__cause__
    text = " ".join(parts)
    delay = None
    if match := RETRY_IN.search(text):
        h, m, s = (float(g) if g else 0.0 for g in match.groups())
        delay = h * 3600 + m * 60 + s or None
    elif match := RETRY_DELAY.search(text):
        delay = float(match.group(1))
    if "PerDay" in text and delay is None:
        delay = 3600.0
    return delay if delay is not None and delay >= LONG_WAIT_S else None


def is_retryable(error: BaseException) -> bool:
    if quota_delay(error) is not None:
        return False
    if isinstance(error, FirstTokenTimeout):
        return False  # a model that did not answer in time is skipped, not asked again
    if isinstance(error, ModelThrottledException | TimeoutError | asyncio.TimeoutError):
        return True
    if isinstance(error, httpx.TimeoutException | httpx.ConnectError | ConnectionError):
        return True
    for attr in ("status_code", "code", "status"):
        value = getattr(error, attr, None)
        if isinstance(value, int) and value in RETRYABLE_STATUS:
            return True
    response = getattr(error, "response", None)
    if getattr(response, "status_code", None) in RETRYABLE_STATUS:
        return True
    return bool(RETRYABLE_TEXT.search(f"{type(error).__name__} {error}"))


@dataclass
class Link:
    name: str  # e.g. "gemini:gemini-flash-latest"
    model: Model
    min_interval: float = 0.0
    first_token_timeout: float | None = None  # overrides the chain's
    role: str = ""  # primary, groq, fallback or ollama
    _last_call: float = field(default=0.0, repr=False)
    down_until: float = field(default=0.0, repr=False)  # cooldown after a failure

    async def pace(self) -> None:
        if self.min_interval <= 0:
            return
        wait = self._last_call + self.min_interval - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_call = time.monotonic()


class FallbackModel(Model):
    def __init__(
        self,
        links: list[Link],
        *,
        retries: int = 2,
        base_delay: float = 1.0,
        first_token_timeout: float = 30.0,
        cooldown: float = 0.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        on_event: EventSink | None = None,
    ) -> None:
        if not links:
            raise ValueError("the model chain needs at least one model")
        self.links = links
        self.retries = retries
        self.base_delay = base_delay
        self.first_token_timeout = first_token_timeout
        self.cooldown = cooldown  # seconds a failed link is skipped, so one outage costs one wait
        self._clock = clock
        self._sleep = sleep
        self.on_event = on_event or (lambda event: None)
        # Chooses which tool specs each model call sees (set by the agent, from the engine state).
        self.tool_filter: Callable[[list[Any]], list[Any]] | None = None
        self.last_used: str | None = None
        self.attempts: list[dict[str, Any]] = []
        self._deadline: float | None = None  # when this turn's model calls must be done

    # --- Model interface -------------------------------------------------------------------

    def update_config(self, **model_config: Any) -> None:
        for link in self.links:
            link.model.update_config(**model_config)

    def get_config(self) -> Any:
        return self.links[0].model.get_config()

    def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):  # type: ignore[override]
        return self.links[0].model.structured_output(output_model, prompt, system_prompt, **kwargs)

    def begin_turn(self, budget: float | None = None) -> None:
        """Start a turn. `budget` is the seconds all of its model calls together may take: the
        chain shares what is left among the models still to try, so a slow link cannot use up the
        time the next one needs."""
        self.last_used = None
        self.attempts = []
        self._deadline = self._clock() + budget if budget else None

    def _candidates(self) -> list[Link]:
        now = self._clock()
        ready = [link for link in self.links if link.down_until <= now]
        for link in self.links:
            if link not in ready:
                self.on_event(
                    {
                        "type": "model_skipped",
                        "model": link.name,
                        "for_s": round(link.down_until - now, 1),
                    }
                )
        return ready or self.links  # if everything is cooling down, try them all anyway

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):  # type: ignore[override]
        if self.tool_filter and tool_specs:
            tool_specs = self.tool_filter(tool_specs)
        candidates = self._candidates()
        for index, link in enumerate(candidates):
            for attempt in range(self.retries + 1):
                started = False
                timeout = link.first_token_timeout or self.first_token_timeout
                if self._deadline is not None:
                    left = self._deadline - self._clock()
                    if left <= 0:
                        raise AllModelsFailed(self.attempts)
                    timeout = min(timeout, max(left / (len(candidates) - index), 2.0))
                try:
                    await link.pace()
                    inner = link.model.stream(messages, tool_specs, system_prompt, **kwargs)
                    async for event in self._with_first_token_timeout(inner, timeout):
                        started = True
                        yield event
                    link.down_until = 0.0
                    self.last_used = link.name
                    return
                except asyncio.CancelledError:
                    # The turn ran out of time inside this link: do not walk into it again.
                    link.down_until = self._clock() + self.cooldown
                    raise
                except Exception as error:
                    if started:
                        raise
                    retry = is_retryable(error) and attempt < self.retries
                    quota = quota_delay(error)
                    record = {
                        "model": link.name,
                        "attempt": attempt + 1,
                        "error": f"{type(error).__name__}: {str(error)[:160]}",
                        "retryable": is_retryable(error),
                    }
                    if quota:
                        record["quota_resets_in_s"] = int(quota)
                    self.attempts.append(record)
                    log.warning("model %s failed: %s", link.name, record["error"])
                    if retry:
                        delay = self.base_delay * (2**attempt)
                        self.on_event({"type": "model_retry", **record, "delay_s": delay})
                        await self._sleep(delay)
                        continue
                    nxt = candidates[index + 1].name if index + 1 < len(candidates) else None
                    skip_for = (
                        max(self.cooldown, min(quota, MAX_SKIP_S)) if quota else self.cooldown
                    )
                    link.down_until = self._clock() + skip_for
                    self.on_event({"type": "model_fallback", **record, "next": nxt})
                    break
        raise AllModelsFailed(self.attempts)

    async def _with_first_token_timeout(
        self, stream: AsyncIterable[Any], timeout: float
    ) -> AsyncGenerator[Any, None]:
        """Yield the stream, but hold back `messageStart` until a real event follows it.

        Providers announce the message before the request has really succeeded, so a bad key or
        a 429 can still arrive after it. Nothing counts as started until content does, and the
        first real event has to arrive within `first_token_timeout`.
        """
        iterator = aiter(stream)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        held: list[Any] = []
        while True:
            pending = asyncio.ensure_future(anext(iterator))
            try:
                done, _ = await asyncio.wait({pending}, timeout=max(deadline - loop.time(), 0.001))
            except asyncio.CancelledError:  # the whole turn was cancelled
                pending.cancel()
                raise
            if not done:  # only our own clock produces FirstTokenTimeout
                pending.cancel()
                raise FirstTokenTimeout(f"no response within {timeout:.0f}s")
            try:
                event = pending.result()  # a provider's own errors come through unchanged
            except StopAsyncIteration:
                break
            if "messageStart" in event:
                held.append(event)
                continue
            for early in held:
                yield early
            held.clear()
            yield event
            break
        for early in held:
            yield early
        async for event in iterator:
            yield event


ROLES = ("primary", "groq", "fallback", "ollama")


def build_chain(
    settings: Settings, on_event: EventSink | None = None, sleep=asyncio.sleep
) -> FallbackModel:
    """The real chain. Links without credentials are left out (Ollama needs none).

    `settings.model_only` keeps a single link (primary, groq, fallback or ollama), which is how
    the live tests run on one model without touching the other models' quotas.
    """
    interval = settings.min_model_interval

    def gemini(model_id: str, role: str) -> Link:
        from strands.models.gemini import GeminiModel

        model = GeminiModel(
            client_args={"api_key": settings.gemini_api_key},
            model_id=model_id,
            params={"temperature": 0.4, "max_output_tokens": 600},
        )
        return Link(f"gemini:{model_id}", model, interval, role=role)

    def groq() -> Link:
        from strands.models.openai import OpenAIModel

        model = OpenAIModel(
            client_args={"api_key": settings.groq_api_key, "base_url": settings.groq_base_url},
            model_id=settings.model_groq,
            params={"temperature": 0.4, "max_tokens": 600},
        )
        return Link(
            f"groq:{settings.model_groq}",
            model,
            interval,
            settings.groq_first_token_timeout,
            role="groq",
        )

    def ollama() -> Link:
        from strands.models.ollama import OllamaModel

        model = OllamaModel(
            settings.ollama_host,
            model_id=settings.ollama_model,
            temperature=0.1,  # steadier tool calls from a small local model
            max_tokens=600,
            keep_alive="30m",
            # Ollama's default context (4k tokens) would silently cut off the prompt and tools.
            options={"num_ctx": 12288},
            additional_args={"think": False},  # no hidden reasoning pass: keeps turns fast
        )
        return Link(
            f"ollama:{settings.ollama_model}",
            model,
            0.0,
            settings.ollama_first_token_timeout,
            role="ollama",
        )

    links: list[Link] = []
    if settings.gemini_api_key:
        links.append(gemini(settings.model_primary, "primary"))
    if settings.groq_api_key:
        links.append(groq())
    if settings.gemini_api_key:
        links.append(gemini(settings.model_fallback, "fallback"))
    links.append(ollama())
    if settings.model_only:
        if settings.model_only not in ROLES:
            raise ValueError(f"KILTA_MODEL_ONLY must be one of {', '.join(ROLES)}")
        links = [link for link in links if link.role == settings.model_only]
        if not links:
            raise ValueError(f"KILTA_MODEL_ONLY={settings.model_only}: that model has no API key")
    return FallbackModel(
        links,
        retries=settings.retries,
        base_delay=settings.retry_base_delay,
        first_token_timeout=settings.first_token_timeout,
        cooldown=settings.model_cooldown,
        sleep=sleep,
        on_event=on_event,
    )
