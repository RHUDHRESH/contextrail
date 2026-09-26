"""Approve (CLAUDE.md §8): held actions become approval requests; decisions come back bound to params_hash.

Dispatch is a job per held action (`approval.dispatch`), consumed by the Freshservice approval call and the
approver's doors (Slack, Email, Teams, Voice). The job is de-duplicated per action, so re-running the stage never
asks twice. An approver the directory could not resolve (`role:<name>`) is an open blocker, never a guess.
"""

from __future__ import annotations

from psycopg import AsyncConnection

from contextrail import repo
from contextrail.models import ActionState, CaseFile
from contextrail.policy.approvers import is_unresolved


async def dispatch_holds(conn: AsyncConnection, case: CaseFile) -> tuple[list[str], list[str]]:
    """T100: enqueue one approval.dispatch job per awaiting action. Returns (dispatched action ids, blockers)."""
    dispatched, blockers = [], []
    for a in case.actions:
        if a.state is not ActionState.AWAITING:
            continue
        if is_unresolved(a.approver):
            blockers.append(f"No named approver for {a.id} ({a.approver}); resolve the role before it can proceed.")
            continue
        job = await repo.enqueue_job(conn, "approval.dispatch",
                                     {"run_id": str(case.run_id), "action_id": a.id, "approver": a.approver,
                                      "params_hash": a.params_hash, "rule_id": a.rule_id},
                                     dedupe_key=f"approval.dispatch:{case.run_id}:{a.id}")
        if job is not None:
            dispatched.append(a.id)
    return dispatched, blockers


async def apply_decisions(conn: AsyncConnection, case: CaseFile) -> tuple[list[str], list[str]]:
    """T102: bring decisions recorded by any door into the case. Returns (decided action ids, void notes).

    A decision counts only if it was given for exactly these parameters: params_hash must match the action.
    Anything else is void and the action keeps waiting (CLAUDE.md §8 Approve: changed params -> approval void).
    """
    decided, void = [], []
    for a in case.actions:
        if a.state is not ActionState.AWAITING:
            continue
        d = await repo.get_approval(conn, case.run_id, a.id)
        if d is None:
            continue
        if d["params_hash"] != a.params_hash:
            void.append(f"{a.id}: approval by {d['approver']} via {d['channel']} is void; it was given for "
                        f"different parameters")
            continue
        a.transition(ActionState.APPROVED if d["decision"] == "approved" else ActionState.REFUSED)
        decided.append(a.id)
    return decided, void
