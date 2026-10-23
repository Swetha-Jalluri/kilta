"""The Strands agent that stands in for Alexa+: it runs one turn against the Kilta MCP server."""

from __future__ import annotations

import asyncio
import logging
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
    "The user has not replied yet, so you cannot answer for them. End your turn by asking them "
    "the question, and wait for their answer."
)
QUESTION_CARDS = {"safety_question", "safety_recheck"}
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
        self._asked_this_turn = False  # a question or gate was put to the user in this turn
        self._cancelled: set[str] = set()
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
    def _answers_for_the_user(name: str, args: dict[str, Any]) -> bool:
        """A call that would clear a safety question or confirm a gate."""
        if name == "safety_check":
            return not args.get("danger_reported", False)
        return name == "confirm_gate" and bool(args.get("confirmed", True))

    def _before_tool(self, event: BeforeToolCallEvent) -> None:
        use = event.tool_use
        self._started[use["toolUseId"]] = time.monotonic()
        # Host policy: a turn may not both ask the user something and answer it. Models do
        # this ("No, there's no burning") when the user's message already describes the problem.
        # Reporting danger is always allowed.
        if self._asked_this_turn and self._answers_for_the_user(
            use["name"], use.get("input") or {}
        ):
            event.cancel_tool = NOT_YET
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
            self.card = card
            gate = card.get("gate")
            if card.get("type") in QUESTION_CARDS or (gate and not gate.get("confirmed")):
                self._asked_this_turn = True
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
        self._cancelled.clear()
        self.chain.begin_turn()
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
            result = await asyncio.wait_for(
                self.agent.invoke_async(prompt), self.settings.turn_timeout
            )
            speech = _text(result.message)
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
        speech = self._safety_speech(speech, language)
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
