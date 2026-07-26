import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any


class EventBroker:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    async def publish(self, run_id: str, event: str, data: dict[str, Any]) -> None:
        payload = {"event": event, "data": {"run_id": run_id, **data}}
        for queue in tuple(self._subscribers.get(run_id, ())):
            with suppress(asyncio.QueueFull):
                queue.put_nowait(payload)

    async def subscribe(self, run_id: str) -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._subscribers[run_id].add(queue)
        try:
            while True:
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield {"event": "ping", "data": {"run_id": run_id}}
        finally:
            self._subscribers[run_id].discard(queue)
            if not self._subscribers[run_id]:
                self._subscribers.pop(run_id, None)
