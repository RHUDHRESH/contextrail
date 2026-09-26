"""One ticket, one run (CLAUDE.md §0 rule 5: idempotency everywhere).

A Freshservice ticket can reach the engine twice, usually within a second: the Workflow Automator webhook
(-> a 'rail.run' job) and the FDK app's onTicketCreate backup trigger (-> POST /v1/runs). Both paths lock the ticket
id with a transaction-scoped Postgres advisory lock, look for the ticket's run, and start one only if there is none.
The ticket therefore gets exactly one run, whichever path, process or worker gets there first.

Email-created tickets are Freshservice tickets too (D-007), so both sources count as ticket-backed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from psycopg import AsyncConnection

from contextrail.db import Database

TICKET_CHANNELS = ("freshservice", "email")


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
    """Serialises picks on one run: a double-clicked candidate must not start the rail twice."""
    return advisory_lock(db, f"run:{run_id}")
