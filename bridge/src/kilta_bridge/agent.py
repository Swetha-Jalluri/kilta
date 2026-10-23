"""The Strands agent that stands in for Alexa+: it runs one turn against the Kilta MCP server."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

from strands import Agent
from strands.agent.conversation_manager import SlidingWindowConversationManager
from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent
from strands.tools.mcp import MCPClient

from .chain import AllModelsFailed, FallbackModel
from .config import Settings
from .events import EventBus
from .mcp_probe import probe
from .models import ToolCall, TurnRequest, TurnResponse
from .tools import specs_for_state

log = logging.getLogger("kilta.agent")

NOT_YET = (
    "You have already asked the user something this turn, and they have not replied. Do not "
    "answer for them or move on. End your turn and wait for their reply."
)
# Cards that put a question or a task to the user. After one, the turn is over.
ASKING_CARDS = {
    "safety_question", "safety_recheck", "appliance", "quick_checks", "ask_code", "diagnosis",
    "verify", "paused", "fixed", "consent",
}  # fmt: skip
# Calls that move the repair on. Once the user has been asked something they are held back, so
# a model cannot skip ahead on the user's behalf. Reporting danger and reading state are not.
ADVANCING = {
    "identify_appliance", "find_manual", "quick_checks", "diagnose", "next_step", "confirm_gate",
    "go_back", "pause_repair", "resume_repair", "report_result", "share_insight", "safety_check",
    "start_repair",
}  # fmt: skip
DANGER_FIRST = (
    "The user just said something that may be dangerous (burning, smoke, sparks, gas, a shock). "
    "Call safety_check with their answer before anything else."
)
FALLBACK_DANGER_WORDS = frozenset(
    {"burning", "burnt", "smoke", "smoking", "spark", "sparks", "fire", "gas", "shock", "quemado",
     "humo", "chispas", "fuego"}
)  # fmt: skip
BUSY_SPEECH = "Sorry, I lost my train of thought for a second. Could you say that again?"


def _unwrap(error: BaseException) -> BaseException:
    """Find an AllModelsFailed buried under Strands' own exception wrappers."""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        if isinstance(current, AllModelsFailed):
            return current
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return error


def _text(message: dict[str, Any] | None) -> str:
    blocks = (message or {}).get("content", [])
    return " ".join(b["text"].strip() for b in blocks if "text" in b).strip()


class KiltaAgent:
    def __init__(
        self, settings: Settings, chain: FallbackModel, bus: EventBus, system_prompt: str
    ) -> None:
        self.settings = settings
        self.chain = chain
        self.bus = bus
        self.system_prompt = system_prompt
        self.lock = asyncio.Lock()
        self._household: dict[str, Any] | None = None
        self._calls: list[ToolCall] = []
        self._started: dict[str, float] = {}
        self._asked_this_turn = False  # the user was asked something in this turn
        self._danger_pending = False  # the user's message has danger words and nothing answered
        self._cancelled: set[str] = set()
        self._danger_words: frozenset[str] | None = None
        self.state: str | None = None
        self.session_id: str | None = None
        self.card: dict[str, Any] | None = None
        self.client: MCPClient | None = None
        self.agent: Agent | None = None
        chain.on_event = self._chain_event
        # Each model call sees only the tools that fit the engine's current state.
        chain.tool_filter = lambda specs: specs_for_state(specs, self.state)

    # --- lifecycle -----------------------------------------------------------------------

    def _build(self) -> None:
        self.close()
        self.client = MCPClient(url=self.settings.mcp_url)
        self.agent = Agent(
            model=self.chain,
            tools=[self.client],
            system_prompt=self.system_prompt,
            callback_handler=None,
            conversation_manager=SlidingWindowConversationManager(window_size=200),
            hooks=[self._before_tool, self._after_tool],
        )

    def close(self) -> None:
        if self.client is not None:
            try:
                self.client.stop(None, None, None)
            except Exception:  # noqa: BLE001
                log.debug("MCP client stop failed", exc_info=True)
        self.client = self.agent = None

    def reset(self) -> None:
        """Forget the conversation (the caller clears the server-side demo data)."""
        self.close()
        self.state = self.session_id = self.card = None
        self.chain.begin_turn()
        self.bus.publish({"type": "reset"})

    async def health(self) -> dict[str, Any]:
        info = await probe(self.settings.mcp_url)
        return info

    # --- hooks ---------------------------------------------------------------------------

    def _chain_event(self, event: dict[str, Any]) -> None:
        self.bus.publish(event)

    @staticmethod
    def _moves_on(name: str, args: dict[str, Any]) -> bool:
        """A call that advances the repair. Reporting danger never counts."""
        if name == "safety_check":
            return not args.get("danger_reported", False)
        return name in ADVANCING

    def _is_restatement(self, call: ToolCall, card: dict[str, Any]) -> bool:
        """Asking identify_appliance again after "yes" says the same thing, it asks nothing new,
        so it must not stop find_manual from following in that turn."""
        return (
            call.name == "identify_appliance"
            and self.state == "MANUAL"
            and call.state == "MANUAL"
            and (self.card or {}).get("appliance_id") == card.get("appliance_id")
        )

    @staticmethod
    def _asks_the_user(name: str, card: dict[str, Any]) -> bool:
        kind = card.get("type")
        gate = card.get("gate")
        if kind == "step":
            # A fresh step is a task. Confirming a gate is only an answer, unless it was a
            # "before" gate: then the step has just been revealed and the user has yet to do it.
            if name != "confirm_gate":
                return True
            return bool(gate and (not gate.get("confirmed") or gate.get("kind") == "before"))
        if kind == "appliance_list":
            return name in ("identify_appliance", "safety_check")
        if kind == "ask_code":  # quick_checks(false) only hands over to diagnose
            return name == "diagnose"
        return kind in ASKING_CARDS

    def _before_tool(self, event: BeforeToolCallEvent) -> None:
        use = event.tool_use
        self._started[use["toolUseId"]] = time.monotonic()
        # Models invent session ids ("123456"). The bridge knows the real one.
        args = use.get("input")
        if isinstance(args, dict) and "session_id" in args:
            if self.session_id:
                args["session_id"] = self.session_id
            else:
                del args["session_id"]  # none yet: the server uses the newest
        # Host policy: once a turn has asked the user something, it may not go on to answer it
        # or skip ahead. Models do ("No, there's no burning"; confirm, identify, diagnose and
        # start the steps in one go) when the user's message already says a lot.
        if self._asked_this_turn and self._moves_on(use["name"], use.get("input") or {}):
            event.cancel_tool = NOT_YET
            self._cancelled.add(use["toolUseId"])
        elif use["name"] == "safety_check":
            self._danger_pending = False  # the model has dealt with the danger words
        elif self._danger_pending and use["name"] in ADVANCING and use["name"] != "start_repair":
            # The engine only sees the danger words a model passes on. If the user's own message
            # has them, nothing moves on until safety_check has been called.
            event.cancel_tool = DANGER_FIRST
            self._cancelled.add(use["toolUseId"])

    def _after_tool(self, event: AfterToolCallEvent) -> None:
        use = event.tool_use
        started = self._started.pop(use["toolUseId"], time.monotonic())
        result = event.result or {}
        structured = result.get("structuredContent") or {}
        error = None
        cancelled = use["toolUseId"] in self._cancelled
        if cancelled:
            error = "answered_for_user"
        elif event.exception is not None:
            error = f"{type(event.exception).__name__}: {event.exception}"[:200]
        elif result.get("status") == "error":
            error = _text({"content": result.get("content", [])})[:200] or "tool error"
        call = ToolCall(
            name=use["name"],
            arguments=dict(use.get("input") or {}),
            ok=error is None,
            refused=cancelled or bool(structured.get("refused")),
            reason="not_answered_by_user" if cancelled else structured.get("reason"),
            state=structured.get("state"),
            session_id=structured.get("session_id"),
            say=_text({"content": result.get("content", [])}) or None,
            card_type=(structured.get("card") or {}).get("type"),
            ms=int((time.monotonic() - started) * 1000),
            error=error,
        )
        self._calls.append(call)
        card = structured.get("card")
        if isinstance(card, dict):
            if self._asks_the_user(call.name, card) and not self._is_restatement(call, card):
                self._asked_this_turn = True
            self.card = card
        if call.state:
            self.state = call.state
        if call.session_id:
            self.session_id = call.session_id
        self.bus.publish(
            {"type": "tool_call", **call.model_dump(), "card_type": (card or {}).get("type")}
        )

    # --- one turn ------------------------------------------------------------------------

    async def _members(self) -> list[dict[str, Any]]:
        if self._household is None:
            info = await probe(self.settings.mcp_url, household=True)
            self._household = info.get("household")
        return (self._household or {}).get("members", [])

    def _context(self, member: dict[str, Any] | None, language: str) -> str:
        who = member["name"] if member else "unknown"
        confidence = member["confidence"] if member else "unknown"
        pace = member["pace"] if member else "normal"
        session = self.session_id or "none"
        return (
            f"[context: speaker={who}; language={language}; confidence={confidence}; "
            f"pace={pace}; active_session={session}]"
        )

    def _has_danger_words(self, text: str) -> bool:
        if self._danger_words is None:
            path = self.settings.data_dir / "safety.json"
            try:
                self._danger_words = frozenset(json.loads(path.read_text())["danger_keywords"])
            except (OSError, KeyError, ValueError):
                self._danger_words = FALLBACK_DANGER_WORDS
        return bool(set(re.findall(r"[^\W\d_]+", text.lower())) & self._danger_words)

    def _scrub_cancelled(self, start: int) -> None:
        """Take calls the host cancelled out of the history. Left in, a small model learns from
        them that it must not call the tool again, and stops answering."""
        if self.agent is None or not self._cancelled:
            return
        kept = []
        for message in self.agent.messages[start:]:
            blocks = [
                b
                for b in message["content"]
                if b.get("toolUse", {}).get("toolUseId") not in self._cancelled
                and b.get("toolResult", {}).get("toolUseId") not in self._cancelled
            ]
            if blocks:
                kept.append({**message, "content": blocks})
        self.agent.messages[start:] = kept

    def _truthful_speech(self, speech: str) -> str:
        """If the engine refused to record "fixed", the user must hear the engine's question, not
        a celebration. A model has answered "great job!" right after that refusal."""
        asked_first = [c for c in self._calls if c.reason == "verify_first" and c.say]
        if asked_first and self.state == "VERIFY":
            return asked_first[-1].say
        return speech

    def _safety_speech(self, speech: str, language: str) -> str:
        """A safety stop is spoken by the engine, whatever the model said. Small models have
        answered a stop with "can you tell me more?". In another language the model's own words
        come first and the engine's English instructions follow, so nothing is left out."""
        stops = [c.say for c in self._calls if c.card_type == "safety_stop" and c.say]
        if not stops:
            return speech
        return stops[-1] if language.startswith("en") else f"{speech} {stops[-1]}".strip()

    async def turn(self, request: TurnRequest) -> TurnResponse:
        async with self.lock:
            return await self._turn(request)

    async def _turn(self, request: TurnRequest) -> TurnResponse:
        started = time.monotonic()
        members = await self._members()
        member = next((m for m in members if m["id"] == (request.member_id or "").lower()), None)
        language = request.language or (member["language"] if member else "en")
        snapshot = list(self.agent.messages) if self.agent else []
        self._calls = []
        self._asked_this_turn = False
        self._danger_pending = self._has_danger_words(request.text)
        self._cancelled.clear()
        self.chain.begin_turn(self.settings.turn_timeout * 0.9)
        self.bus.publish(
            {
                "type": "turn_start",
                "member_id": request.member_id,
                "language": language,
                "text": request.text,
            }
        )
        speech, error = "", None
        try:
            if self.agent is None:
                # Starts the MCP client, so this fails while the Kilta server is down. The next
                # turn tries again, which is how the bridge recovers once the server is back.
                await asyncio.to_thread(self._build)
            assert self.agent is not None
            prompt = f"{self._context(member, language)}\n{request.text}"
            for attempt in (1, 2):
                result = await asyncio.wait_for(
                    self.agent.invoke_async(prompt), self.settings.turn_timeout
                )
                speech = _text(result.message)
                if speech or self._calls or attempt == 2:
                    break
                # A model that answers with nothing at all (small local models sometimes do):
                # forget that exchange and ask once more.
                self.bus.publish({"type": "model_empty", "model": self.chain.last_used})
                self.agent.messages[:] = snapshot
        except Exception as caught:  # noqa: BLE001 - a turn must always answer
            failure = _unwrap(caught)
            error = (
                "all_models_failed"
                if isinstance(failure, AllModelsFailed)
                else f"{type(failure).__name__}: {failure}"[:200]
            )
            log.error("turn failed: %s", error, exc_info=caught)
            if self.agent is not None:
                self.agent.messages[:] = snapshot  # drop the dangling user message
        if not speech:
            spoken = [c.say for c in reversed(self._calls) if c.ok and c.say]
            speech = spoken[0] if spoken and not error else BUSY_SPEECH
        self._scrub_cancelled(len(snapshot))
        speech = self._safety_speech(speech, language)
        speech = self._truthful_speech(speech)
        response = TurnResponse(
            speech=speech,
            card=self.card if self._calls else None,
            tool_calls=self._calls,
            state=self.state,
            session_id=self.session_id,
            member_id=member["id"] if member else request.member_id,
            language=language,
            model=self.chain.last_used,
            fallbacks=list(self.chain.attempts),
            elapsed_ms=int((time.monotonic() - started) * 1000),
            error=error,
        )
        self.bus.publish(
            {
                "type": "turn_end",
                "speech": response.speech,
                "state": response.state,
                "model": response.model,
                "error": error,
                "elapsed_ms": response.elapsed_ms,
            }
        )
        return response
