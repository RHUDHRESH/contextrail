"""The job worker (D-003): Postgres jobs claimed with `FOR UPDATE SKIP LOCKED`, run by registered handlers.

    from contextrail.jobs import handler

    @handler("rail.run")
    async def run_rail(platform, payload: dict) -> None: ...

- A worker claims only the kinds it has a handler for. Other kinds stay queued, untouched, for a worker that has one.
- A claim is a lease (`locked_until`). A handler gets less time than its lease, so two workers never run one job.
- A failure is retried with exponential backoff until `max_attempts`. The job then stays in the table, dead
  (`attempts = max_attempts`, `last_error` set), for an operator to read. `PermanentJobError` (a bad payload, a
  missing connector) goes dead at once, because retrying cannot fix it.
- Delivery is at least once: a crash after a handler's work but before `complete_job` runs the job again, so
  handlers must be idempotent (the rail is: runs are looked up before they are started, writes carry keys).
- `stop()` is graceful: the current job finishes, then the loop exits.

Handlers receive the Platform (app_state.py) and the job payload.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

import structlog

from contextrail import repo
from contextrail.db import Database
from contextrail.logs import get_logger

Handler = Callable[[Any, dict], Awaitable[None]]
log = get_logger("contextrail.jobs")


class PermanentJobError(Exception):
    """Retrying cannot help (bad payload, missing configuration): the job goes dead now, with this message."""


class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    def handler(self, kind: str) -> Callable[[Handler], Handler]:
        def register(fn: Handler) -> Handler:
            if kind in self._handlers:
                raise ValueError(f"a handler for {kind!r} is already registered")
            self._handlers[kind] = fn
            return fn
        return register

    def get(self, kind: str) -> Handler | None:
        return self._handlers.get(kind)

    def kinds(self) -> list[str]:
        return sorted(self._handlers)


handlers = HandlerRegistry()
handler = handlers.handler


def retry_delay(attempt: int, *, base_s: int = 5, cap_s: int = 600) -> int:
    """Seconds before retry number `attempt` (1-based): 5, 10, 20, 40 ... capped at 10 minutes."""
    return min(cap_s, base_s * 2 ** min(attempt - 1, 20))


@dataclass(frozen=True)
class JobOutcome:
    id: int
    kind: str
    outcome: Literal["done", "retry", "dead"]
    error: str | None = None


class Worker:
    def __init__(self, db: Database, context: Any, *, registry: HandlerRegistry | None = None, lease_s: float = 300,
                 timeout_s: float | None = None, poll_s: float = 1.0,
                 retry_delay: Callable[[int], float] = retry_delay) -> None:
        timeout_s = lease_s * 0.9 if timeout_s is None else timeout_s
        if timeout_s >= lease_s:
            raise ValueError("a handler's timeout must be shorter than its lease, or two workers could run one job")
        self.db, self.context = db, context
        self.registry = handlers if registry is None else registry
        self.lease_s, self.timeout_s, self.poll_s, self.retry_delay = lease_s, timeout_s, poll_s, retry_delay
        self._stop = asyncio.Event()

    async def run_once(self) -> JobOutcome | None:
        """Claim and run one ready job. None when there is nothing this worker can run."""
        kinds = self.registry.kinds()
        if not kinds:
            return None
        async with self.db.transaction() as c:
            job = await repo.claim_job(c, kinds=kinds, lease_seconds=self.lease_s)
        if job is None:
            return None
        with structlog.contextvars.bound_contextvars(job_id=job["id"], job_kind=job["kind"],
                                                     run_id=job["payload"].get("run_id")):
            out = await self._run(job)
            log.info("job_" + out.outcome, attempt=job["attempts"], error=out.error)
        return out

    async def _run(self, job: dict) -> JobOutcome:
        fn = self.registry.get(job["kind"])
        try:
            await asyncio.wait_for(fn(self.context, job["payload"]), timeout=self.timeout_s)
        except PermanentJobError as e:
            async with self.db.connection() as c:
                await c.execute("""update jobs set attempts = greatest(attempts, max_attempts), locked_until = null,
                                   last_error = %s where id = %s""", (str(e)[:2000], job["id"]))
            return JobOutcome(job["id"], job["kind"], "dead", str(e))
        except Exception as e:  # noqa: BLE001 -- a handler failure is recorded on its job; it never stops the worker
            error = f"timed out after {self.timeout_s}s" if isinstance(e, TimeoutError) else f"{type(e).__name__}: {e}"
            last = job["attempts"] >= job["max_attempts"]
            async with self.db.connection() as c:
                await repo.fail_job(c, job["id"], error, retry_in_seconds=0 if last else self.retry_delay(job["attempts"]))
            return JobOutcome(job["id"], job["kind"], "dead" if last else "retry", error)
        async with self.db.connection() as c:
            await repo.complete_job(c, job["id"])
        return JobOutcome(job["id"], job["kind"], "done")

    async def run(self) -> None:
        """Poll until stop(). An empty queue or a database hiccup waits `poll_s`, not a hot loop."""
        log.info("worker_started", kinds=self.registry.kinds())
        while not self._stop.is_set():
            try:
                out = await self.run_once()
            except Exception as e:  # noqa: BLE001 -- e.g. the database restarted: back off and keep serving
                log.warning("worker_poll_failed", error=type(e).__name__)
                out = None
            if out is None:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=self.poll_s)
        log.info("worker_stopped")

    def stop(self) -> None:
        self._stop.set()
