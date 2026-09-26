"""Stage event emitter (checklist T084): one stream of StageEvents per run, fanned out to SSE and door callbacks.

SSE subscribers get an asyncio.Queue; doors register callbacks (Slack set_status, Teams card update, voice
prompt). A slow or failing door never blocks the rail: callbacks run with a timeout and their errors are logged,
not raised. Each run's events carry a monotonic `seq` so doors can drop stale updates.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID

from contextrail.logs import get_logger
from contextrail.models import RunStatus, Stage, StageEvent

DoorCallback = Callable[[StageEvent], Awaitable[None]]
log = get_logger("contextrail.events")


class EventBus:
    def __init__(self, *, callback_timeout_s: float = 3.0, history: int = 200) -> None:
        self._seq: dict[UUID, int] = defaultdict(int)
        self._queues: dict[UUID, set[asyncio.Queue]] = defaultdict(set)
        self._callbacks: dict[UUID, list[DoorCallback]] = defaultdict(list)
        self._global: list[DoorCallback] = []
        self._history: dict[UUID, list[StageEvent]] = defaultdict(list)
        self._timeout = callback_timeout_s
        self._keep = history

    def subscribe(self, run_id: UUID) -> asyncio.Queue:
        """For SSE: a queue that receives this run's events (replaying what already happened)."""
        q: asyncio.Queue = asyncio.Queue()
        for e in self._history[run_id]:
            q.put_nowait(e)
        self._queues[run_id].add(q)
        return q

    def unsubscribe(self, run_id: UUID, q: asyncio.Queue) -> None:
        self._queues[run_id].discard(q)

    def on_run(self, run_id: UUID, callback: DoorCallback) -> None:
        """A door that started or displays this run (e.g. the Slack message to update in place)."""
        self._callbacks[run_id].append(callback)

    def on_every_run(self, callback: DoorCallback) -> None:
        self._global.append(callback)

    def history(self, run_id: UUID) -> list[StageEvent]:
        return list(self._history[run_id])

    async def emit(self, run_id: UUID, stage: Stage | str, status: RunStatus | str, message: str, *,
                   counts: dict | None = None, replay: bool = False) -> StageEvent:
        seq = self._seq[run_id]
        self._seq[run_id] += 1
        event = StageEvent(run_id=run_id, seq=seq, stage=stage, status=status, message=message[:280],
                           counts=counts or {}, at=datetime.now(UTC), replay=replay)
        hist = self._history[run_id]
        hist.append(event)
        del hist[:-self._keep]
        for q in list(self._queues[run_id]):
            q.put_nowait(event)
        for cb in (*self._callbacks[run_id], *self._global):
            try:
                await asyncio.wait_for(cb(event), timeout=self._timeout)
            except Exception as e:  # noqa: BLE001 -- isolation boundary: a door problem must never stop the rail
                log.warning("door_callback_failed", run_id=str(run_id), seq=seq, error=type(e).__name__)
        return event
