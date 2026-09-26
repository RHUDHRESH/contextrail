"""How requests become runs: one ticket, one run (CLAUDE.md §0 rule 5), and the 'rail.run' job.

A Freshservice ticket can reach the engine twice, usually within a second: the Workflow Automator webhook
(-> a 'rail.run' job) and the FDK app's onTicketCreate backup trigger (-> POST /v1/runs). Both paths lock the ticket
id with a transaction-scoped Postgres advisory lock, look for the ticket's run, and start one only if there is none.
The ticket therefore gets exactly one run, whichever path, process or worker gets there first.

Email-created tickets are Freshservice tickets too (D-007), so both sources count as ticket-backed.

'rail.run' payloads:
- {"ticket_id": 4242, "source": "freshservice" | "email"}: start the ticket's run through Door.start_run, reading the
  request from the ticket (TicketReader, the Freshservice connector). If the ticket already has a run, a duplicate
  delivery changes nothing, and a run that stopped mid-rail (a crashed attempt) is continued.
- {"run_id": "..."}: continue that run: a run created but never run (or stopped mid-rail) runs; a run awaiting
  approval resumes if a decision has been recorded; needs_input waits for the requester; finished runs stay finished.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal, Protocol
from uuid import UUID

from psycopg import AsyncConnection
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from contextrail import repo
from contextrail.db import Database
from contextrail.jobs import PermanentJobError, handler
from contextrail.logs import get_logger

TICKET_CHANNELS = ("freshservice", "email")
log = get_logger("contextrail.intake")


async def find_ticket_run(conn: AsyncConnection, ticket_id: str) -> dict | None:
    """The latest run started from this ticket, or None."""
    cur = await conn.execute(
        "select * from runs where source = any(%s) and source_ref = %s order by created_at desc limit 1",
        (list(TICKET_CHANNELS), ticket_id))
    return await cur.fetchone()


@asynccontextmanager
async def advisory_lock(db: Database, key: str) -> AsyncIterator[AsyncConnection]:
    """Hold a named lock until the block ends, across every process on this database. Transaction-scoped, so a crash
    or cancellation can never leave a pooled connection holding it. Yields the locked connection for lookups."""
    async with db.transaction() as conn:
        await conn.execute("select pg_advisory_xact_lock(hashtextextended(%s, 0))", (key,))
        yield conn


def ticket_lock(db: Database, ticket_id: str):
    return advisory_lock(db, f"ticket:{ticket_id}")


def run_lock(db: Database, run_id: object):
    """Serialises work on one run: a double-clicked candidate or a duplicate job must not run the rail twice."""
    return advisory_lock(db, f"run:{run_id}")


# --- reading the request from the ticket ------------------------------------------------------------------------

class TicketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ticket_id: str
    text: str = Field(min_length=1)            # as the requester wrote it: untrusted text (P6)
    requester_external_id: str | None = None   # the id Door.resolve_actor expects for the run's channel


class TicketReader(Protocol):
    """Implemented by the Freshservice connector (GET /api/v2/tickets/{id}, section I). Labelled LIVE or FIXTURE."""

    mode: str

    async def ticket_request(self, ticket_id: str) -> TicketRequest: ...


# --- the 'rail.run' job -----------------------------------------------------------------------------------------

class RailRunJob(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run_id: UUID | None = None
    ticket_id: str | None = Field(default=None, min_length=1, max_length=128)
    source: Literal["freshservice", "email"] = "freshservice"

    @field_validator("ticket_id", mode="before")
    @classmethod
    def _numeric_ids_are_refs(cls, v):  # Workflow Automator sends {{ticket.id_numeric}} as a number
        return str(v) if isinstance(v, int) and not isinstance(v, bool) else v

    @model_validator(mode="after")
    def _exactly_one(self) -> RailRunJob:
        if (self.run_id is None) == (self.ticket_id is None):
            raise ValueError("give exactly one of run_id or ticket_id")
        return self


async def continue_run(platform, run_id: UUID) -> str:
    """Take a run as far as it can go now. Returns the run's status afterwards."""
    async with run_lock(platform.db, run_id) as c:
        run = await repo.get_run(c, run_id)
        if run is None:
            raise PermanentJobError(f"no run {run_id}")
        if run["status"] == "running":  # created and never run, or stopped mid-rail: writes carry idempotency keys
            return await platform.runner.run(run_id)
        if run["status"] == "awaiting_approval":
            decided = await (await c.execute("""
                select exists (select 1 from actions a join approvals d on d.run_id = a.run_id and d.action_id = a.id
                               where a.run_id = %s and a.state = 'awaiting') as decided""", (run_id,))).fetchone()
            if decided["decided"]:
                return await platform.runner.resume(run_id)
        return run["status"]


@handler("rail.run")
async def rail_run(platform, payload: dict) -> None:
    try:
        job = RailRunJob.model_validate(payload)
    except ValidationError as e:
        raise PermanentJobError(f"bad rail.run payload: {e.errors(include_url=False)}") from None
    if job.run_id is not None:
        status = await continue_run(platform, job.run_id)
        log.info("rail_run_continued", run_id=str(job.run_id), status=str(status))
        return
    async with ticket_lock(platform.db, job.ticket_id) as c:
        run = await find_ticket_run(c, job.ticket_id)
        if run is None:
            if platform.tickets is None:
                raise PermanentJobError(f"no ticket reader configured; cannot read ticket {job.ticket_id} "
                                        "(wire the Freshservice connector into Platform.tickets)")
            req = await platform.tickets.ticket_request(job.ticket_id)
            view = await platform.door.start_run(req.text, channel=job.source,
                                                 actor_external_id=req.requester_external_id,
                                                 source_ref=job.ticket_id)
            log.info("rail_run_started", ticket_id=job.ticket_id, run_id=str(view.run_id), status=view.status)
        elif run["status"] == "running":
            status = await continue_run(platform, run["id"])
            log.info("rail_run_continued", ticket_id=job.ticket_id, run_id=str(run["id"]), status=str(status))
        else:
            log.info("rail_run_duplicate", ticket_id=job.ticket_id, run_id=str(run["id"]), status=run["status"])
