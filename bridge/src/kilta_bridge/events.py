"""A tiny in-process event bus behind GET /api/events (server-sent events)."""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from collections.abc import AsyncIterator
from typing import Any


class EventBus:
    def __init__(self, history: int = 200) -> None:
        self._history: deque[dict[str, Any]] = deque(maxlen=history)
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._seq = 0

    def publish(self, event: dict[str, Any]) -> dict[str, Any]:
        self._seq += 1
        event = {"seq": self._seq, "ts": round(time.time(), 3), **event}
        self._history.append(event)
        for queue in list(self._subscribers):
            queue.put_nowait(event)
        return event

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(self._history)[-limit:] if limit > 0 else []

    def open(self, replay: int = 0) -> asyncio.Queue[dict[str, Any]]:
        """A queue that receives every event from now on, after `replay` recent ones."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        for event in self.recent(replay):
            queue.put_nowait(event)
        self._subscribers.add(queue)
        return queue

    def close(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    async def subscribe(self, replay: int = 0) -> AsyncIterator[dict[str, Any]]:
        queue = self.open(replay)
        try:
            while True:
                yield await queue.get()
        finally:
            self.close(queue)


def sse_format(event: dict[str, Any]) -> str:
    return f"id: {event['seq']}\nevent: {event['type']}\ndata: {json.dumps(event)}\n\n"
