"""Per-topic asyncio.Queue broker for Server-Sent Events (single process)."""

import asyncio
import json
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from pydantic import BaseModel

KEEPALIVE_S = 15.0


def _jsonable(data: Any) -> Any:
    if isinstance(data, BaseModel):
        return data.model_dump(mode="json")
    if isinstance(data, dict):
        return {k: _jsonable(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_jsonable(v) for v in data]
    return data


def format_sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(_jsonable(data), default=str)}\n\n"


class Broker:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue[tuple[str, Any]]]] = defaultdict(set)

    def publish(self, topic: str, event: str, data: Any) -> None:
        for q in list(self._subs.get(topic, ())):
            q.put_nowait((event, data))

    async def stream(
        self,
        topic: str,
        is_disconnected: Callable[[], Awaitable[bool]],
        first: tuple[str, Any] | None = None,
        keepalive_s: float = KEEPALIVE_S,
    ) -> AsyncIterator[str]:
        """Yield SSE frames for `topic` until the client disconnects."""
        q: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        self._subs[topic].add(q)
        try:
            if first is not None:
                yield format_sse(*first)
            while not await is_disconnected():
                try:
                    event, data = await asyncio.wait_for(q.get(), timeout=keepalive_s)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield format_sse(event, data)
        finally:
            self._subs[topic].discard(q)
            if not self._subs[topic]:
                del self._subs[topic]
