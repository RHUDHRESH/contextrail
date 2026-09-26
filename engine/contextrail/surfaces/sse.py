"""Live stage events (checklist T212, CLAUDE.md §8 Runner, §17): what GET /v1/runs/{id}/events streams.

- History first: the EventBus replays the run's events to a new subscriber, then live events follow in `seq` order.
- Each event is `event: stage`, `id: <seq>`, `data: <StageEvent JSON>`. A reconnecting EventSource sends
  Last-Event-ID, and events it already has are skipped.
- Heartbeat: a `: keep-alive` comment when nothing happened for `heartbeat_s`, and on each heartbeat the run's
  status is re-read from the database.
- The stream ends with `event: end`, data {run_id, status}, when the run reaches a terminal status (partial, done,
  failed), whether the bus says so or the database does (a run finished by a worker in another process). Clients
  close on `end`. A run waiting for approval or input keeps the stream open: a decision resumes it.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from uuid import UUID

from fastapi.sse import ServerSentEvent

from contextrail.models import RunStatus
from contextrail.rail.events import EventBus

TERMINAL = frozenset({RunStatus.PARTIAL, RunStatus.DONE, RunStatus.FAILED})


def _end(run_id: UUID, status: str | None) -> ServerSentEvent:
    return ServerSentEvent(event="end", data={"run_id": str(run_id), "status": status})


async def stage_events(bus: EventBus, run_id: UUID, load_status: Callable[[], Awaitable[str | None]], *,
                       heartbeat_s: float, after_seq: int | None = None) -> AsyncIterator[ServerSentEvent]:
    queue = bus.subscribe(run_id)
    try:
        backlog = queue.qsize()           # the replayed history
        status = await load_status()      # None: the run no longer exists
        while True:
            if backlog == 0 and (status is None or status in TERMINAL):
                yield _end(run_id, status)
                return
            try:
                event = await asyncio.wait_for(queue.get(), timeout=heartbeat_s)
            except TimeoutError:
                status = await load_status()
                if status is not None and status not in TERMINAL:
                    yield ServerSentEvent(comment="keep-alive")
                continue
            backlog = max(0, backlog - 1)
            if after_seq is None or event.seq > after_seq:
                yield ServerSentEvent(event="stage", id=str(event.seq), data=event)
            if event.status in TERMINAL:
                yield _end(run_id, event.status)
                return
    finally:
        bus.unsubscribe(run_id, queue)
