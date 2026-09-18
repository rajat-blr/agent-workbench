import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class AgentEvent:
    session_id: int
    type: str
    payload: dict[str, Any]
    sequence: int
    created_at: str

    @classmethod
    def create(cls, session_id: int, event_type: str, payload: dict[str, Any], sequence: int) -> AgentEvent:
        return cls(
            session_id=session_id,
            type=event_type,
            payload=payload,
            sequence=sequence,
            created_at=datetime.now(UTC).isoformat(),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "type": self.type,
            "payload": self.payload,
            "sequence": self.sequence,
            "created_at": self.created_at,
        }


class EventBroker:
    def __init__(self, queue_size: int = 1000) -> None:
        self._queues: defaultdict[int | None, set[asyncio.Queue[AgentEvent]]] = defaultdict(set)
        self._queue_size = queue_size
        self._sequence = 0
        self._lock = asyncio.Lock()

    async def publish(self, session_id: int, event_type: str, payload: dict[str, Any]) -> AgentEvent:
        async with self._lock:
            self._sequence += 1
            event = AgentEvent.create(session_id, event_type, payload, self._sequence)
            queues = (*self._queues.get(None, ()), *self._queues.get(session_id, ()))
            for queue in queues:
                if queue.full():
                    queue.get_nowait()
                queue.put_nowait(event)
            return event

    @asynccontextmanager
    async def subscribe(self, session_id: int | None = None) -> AsyncIterator[asyncio.Queue[AgentEvent]]:
        queue: asyncio.Queue[AgentEvent] = asyncio.Queue(maxsize=self._queue_size)
        self._queues[session_id].add(queue)
        try:
            yield queue
        finally:
            self._queues[session_id].discard(queue)
            if not self._queues[session_id]:
                del self._queues[session_id]
