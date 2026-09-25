"""Plan (CLAUDE.md §8): dependency order, revocations for a team transfer, and refusals kept visible (P4).

Order: allowed grants, then transfer revocations (new access lands before old access goes, same day), then held
actions (waiting on a named person), then refusals, last but never removed, so everyone sees what was asked and
what was refused in one table.
"""

from __future__ import annotations

from contextrail.models import Action, Subject
from contextrail.policy.engine import PolicyEngine
from contextrail.rail.compile import CompileInputs
from contextrail.rail.govern import Governed, evaluate


def transfer_revokes(subject: Subject, subject_record: dict, inputs: CompileInputs) -> list[Action]:
    """Access the person holds that their new role does not cover, when the record shows a team transfer."""
    previous = subject_record.get("previous_team")
    if not previous:
        return []
    old = [e for e in inputs.subject_holdings if subject.role not in inputs.catalog[e].get("role_scope", [])]
    return [Action.create(f"R{i:02d}", "revoke", {**inputs.catalog[e], "entitlement": e, "origin": "transfer",
                                                   "previous_team": previous, "subject_id": subject.source_id})
            for i, e in enumerate(old, 1)]


def _rank(g: Governed) -> tuple[int, str]:
    v, kind = g.verdict.verdict, g.action.kind
    rank = {"ALLOW": 0 if kind == "grant" else 1, "HOLD": 2, "REFUSE": 3}[v]
    return rank, g.action.id


def build_plan(governed: list[Governed], subject: Subject, subject_record: dict, inputs: CompileInputs,
               engine: PolicyEngine, *, requested_by: str | None) -> list[Governed]:
    """T097: add transfer revocations (governed by policy like everything else) and order the whole plan."""
    revokes = evaluate(transfer_revokes(subject, subject_record, inputs), subject, engine, role=inputs.role,
                       requested_by=requested_by)
    return sorted([*governed, *revokes], key=_rank)
