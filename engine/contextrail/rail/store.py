"""Capsule persistence (checklist T094) and the handoff boundary (P5).

`save_case` seals the case file and stores it with its digest on the run row, in the caller's transaction.
`load_case` is how any later stage or door receives the case: by value, re-verified against its own content AND
against the digest recorded for the run. A capsule edited in the database, or swapped for another sealed capsule,
is rejected with DigestMismatch.
"""

from __future__ import annotations

from uuid import UUID

from psycopg import AsyncConnection

from contextrail import repo
from contextrail.capsule import DigestMismatch, receive, seal
from contextrail.models import CaseFile


async def save_case(conn: AsyncConnection, case: CaseFile, *, stage: str | None = None,
                    status: str | None = None) -> CaseFile:
    sealed = seal(case)
    await repo.set_stage(conn, case.run_id, stage=stage, status=status, intent=sealed.intent,
                         subject_id=sealed.subject.source_id, capsule=sealed.model_dump(mode="json"),
                         capsule_digest=sealed.digest)
    return sealed


async def load_case(conn: AsyncConnection, run_id: UUID) -> CaseFile:
    row = await repo.get_run(conn, run_id)
    if row is None or row["capsule"] is None:
        raise LookupError(f"run {run_id} has no sealed case file")
    case = receive(row["capsule"])                       # content matches its own digest
    if case.digest != row["capsule_digest"]:             # and it is the digest this run recorded
        raise DigestMismatch(row["capsule_digest"], case.digest)
    return case
