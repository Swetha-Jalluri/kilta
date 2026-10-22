"""Fake models for deterministic tests. They stream the same events a real provider would."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from strands.models.model import Model


@dataclass
class Plan:
    """What the scripted model does on one user turn: call these tools in order, then speak."""

    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    say: str = "Okay."


def _usage() -> dict[str, Any]:
    return {
        "metadata": {
            "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
            "metrics": {"latencyMs": 1},
        }
    }


def is_user_text(message: dict[str, Any]) -> bool:
    return (
        message["role"] == "user"
        and any("text" in b for b in message["content"])
        and not any("toolResult" in b for b in message["content"])
    )


class _BaseFake(Model):
    def update_config(self, **model_config: Any) -> None:  # pragma: no cover
        pass

    def get_config(self) -> Any:
        return {}

    def structured_output(self, *args: Any, **kwargs: Any):  # pragma: no cover
        raise NotImplementedError


class ScriptedModel(_BaseFake):
    """Plays one Plan per user turn. The turn is found by counting the user's own messages, so a
    rolled-back conversation replays the same plan."""

    def __init__(self, plans: list[Plan]) -> None:
        self.plans = plans
        self.seen_prompts: list[str] = []
        self.seen_tools: list[list[str]] = []  # tool names offered on each model call
        self.model_calls = 0

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        user_idx = [i for i, m in enumerate(messages) if is_user_text(m)]
        self.seen_prompts = [
            "\n".join(b["text"] for b in messages[i]["content"] if "text" in b) for i in user_idx
        ]
        self.seen_tools.append([t["name"] for t in tool_specs or []])
        turn = len(user_idx)
        plan = self.plans[turn - 1]
        done = sum(
            1
            for m in messages[user_idx[-1] + 1 :]
            if m["role"] == "assistant" and any("toolUse" in b for b in m["content"])
        )
        self.model_calls += 1
        yield {"messageStart": {"role": "assistant"}}
        if done < len(plan.calls):
            name, args = plan.calls[done]
            use_id = f"t{turn}-{done}"
            yield {"contentBlockStart": {"start": {"toolUse": {"name": name, "toolUseId": use_id}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(args)}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": plan.say}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
        yield _usage()


class FailingModel(_BaseFake):
    """Raises on every call, before streaming anything."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        self.calls += 1
        raise self.error
        yield  # pragma: no cover  (makes this an async generator)


class FlakyModel(_BaseFake):
    """Fails the first `failures` calls with `error`, then delegates to `inner`."""

    def __init__(self, inner: Model, failures: int, error: Exception) -> None:
        self.inner, self.failures, self.error, self.calls = inner, failures, error, 0

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error
        async for event in self.inner.stream(messages, tool_specs, system_prompt, **kwargs):
            yield event


class SlowModel(_BaseFake):
    """Never produces a first event (for the first-token timeout)."""

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        await asyncio.sleep(3600)
        yield {}  # pragma: no cover


class BrokenMidStream(_BaseFake):
    """Yields one event, then fails: a chain cannot switch models after that."""

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        yield {"messageStart": {"role": "assistant"}}
        yield {"contentBlockStart": {"start": {}}}
        yield {"contentBlockDelta": {"delta": {"text": "Half an ans"}}}
        raise RuntimeError("connection reset mid-stream")


class FailsAfterMessageStart(_BaseFake):
    """Announces the message, then fails before any content, like a real provider on a 429."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        self.calls += 1
        yield {"messageStart": {"role": "assistant"}}
        raise self.error
