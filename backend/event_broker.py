import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class AgentEvent:
    session_id: int
    run_id: int | None
    type: str
    payload: dict[str, Any]
    sequence: int
    created_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "run_id": self.run_id,
            "type": self.type,
            "payload": self.payload,
            "sequence": self.sequence,
            "created_at": self.created_at,
        }


class EventBroker:
    def __init__(self, queue_size: int = 1000) -> None:
        self._queues: defaultdict[int, set[asyncio.Queue[AgentEvent]]] = defaultdict(
            set
        )
        self._queue_size = queue_size

    def publish(self, event: AgentEvent) -> None:
        for queue in tuple(self._queues.get(event.session_id, ())):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)

    @asynccontextmanager
    async def subscribe(
        self, session_id: int
    ) -> AsyncIterator[asyncio.Queue[AgentEvent]]:
        queue: asyncio.Queue[AgentEvent] = asyncio.Queue(maxsize=self._queue_size)
        self._queues[session_id].add(queue)
        try:
            yield queue
        finally:
            self._queues[session_id].discard(queue)
            if not self._queues[session_id]:
                del self._queues[session_id]
