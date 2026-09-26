"""Finalize (CLAUDE.md §8, checklist T106): derive the run's status from its actions and trigger the receipt.

The status is computed, never chosen:
- awaiting_approval while any action waits for a named person;
- partial when anything was refused, failed, is still unknown, or a blocker is open. A refusal is a successful,
  governed outcome, and the manager sees "partial", not a green dashboard;
- done only when every action that was asked for is verified.
"""

from __future__ import annotations

from collections import Counter

from psycopg import AsyncConnection

from contextrail import repo
from contextrail.models import ActionState, CaseFile, RunStatus

_S = ActionState


def tally(case: CaseFile) -> dict[str, int]:
    verdicts = Counter(a.verdict for a in case.actions)
    states = Counter(a.state for a in case.actions)
    return {"allow": verdicts["ALLOW"], "hold": verdicts["HOLD"], "refuse": verdicts["REFUSE"],
            "verified": states[_S.VERIFIED], "failed": states[_S.FAILED] + states[_S.UNKNOWN]}


def final_status(case: CaseFile) -> RunStatus:
    states = {a.state for a in case.actions}
    if _S.AWAITING in states:
        return RunStatus.AWAITING_APPROVAL
    if case.open_blockers or states & {_S.REFUSED, _S.FAILED, _S.UNKNOWN, _S.PLANNED, _S.APPROVED, _S.EXECUTED}:
        return RunStatus.PARTIAL
    return RunStatus.DONE


async def request_receipt(conn: AsyncConnection, case: CaseFile, status: RunStatus) -> int | None:
    """Enqueue receipt generation (T210). One receipt per distinct outcome of the run, not per call."""
    t = tally(case)
    key = f"receipt.build:{case.run_id}:{status}:{t['verified']}:{t['failed']}"
    return await repo.enqueue_job(conn, "receipt.build", {"run_id": str(case.run_id), "status": str(status)},
                                  dedupe_key=key)
