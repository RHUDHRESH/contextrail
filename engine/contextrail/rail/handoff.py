"""Handoff (CLAUDE.md §8, checklist T099): per-team views of the sealed case file, passed by value, verified on receipt.

A team gets an allow-listed projection of the capsule, never the capsule itself (CLAUDE.md §16: capsule field
allow-lists per team; Security never sees salary). A field that is not on a team's list is not in its view. Every
view carries the digest of the capsule it was cut from and a digest of its own content.

On receipt, a view is accepted only if (1) its content matches its own digest, (2) it was cut from the capsule the
receiver holds (whose seal was itself verified), and (3) it equals the allow-listed projection of that capsule, so a
field added in transit, a promoted refusal or a stripped constraint is rejected even when the attacker re-hashed the
view. A mismatch halts the run with an audit event (§8 Handoff failure behaviour).

Refused actions are in every view (P4). Evidence text is not: Security sees where each piece of evidence came from and
how far it is trusted, not the excerpt, because record excerpts can carry HR data.
"""

from __future__ import annotations

import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from contextrail.canonical import sha256_hex
from contextrail.capsule import DigestMismatch, verify
from contextrail.models import CaseFile

Team = Literal["it", "security"]
TEAMS: tuple[Team, ...] = ("it", "security")

SUBJECT_FIELDS: dict[str, tuple[str, ...]] = {
    "it": ("source_id", "display_name", "employment_type", "role", "team", "start_date", "end_date"),
    "security": ("source_id", "display_name", "employment_type", "role", "team", "seniority", "manager_id",
                 "start_date", "end_date", "sow_repos"),
}
ACTION_FIELDS: dict[str, tuple[str, ...]] = {
    team: ("id", "kind", "verdict", "rule_id", "clause", "approver", "state", "params_hash", "expires_at")
    for team in TEAMS
}
TARGET_FIELDS: dict[str, tuple[str, ...]] = {
    "it": ("system", "entitlement", "label", "repo", "permission"),
    "security": ("system", "entitlement", "label", "repo", "permission", "resource_class", "repo_tags"),
}
EVIDENCE_FIELDS: dict[str, tuple[str, ...]] = {
    "it": (),
    "security": ("id", "kind", "source", "uri", "trust", "stale", "last_verified"),
}
# Case-level lists each team receives, besides request, subject, peer and actions.
CASE_FIELDS: dict[str, tuple[str, ...]] = {
    "it": ("constraints", "open_blockers"),
    "security": ("constraints", "open_blockers", "decisions"),
}
# Defence in depth for §16: whatever the lists above say, no key like these may reach Security.
SALARY_LIKE = re.compile(r"salar|compensation|payroll|pay_?band|bonus|wage|ctc|stipend|bank", re.IGNORECASE)


class ViewMismatch(DigestMismatch):
    """A team view that is not the allow-listed projection of the sealed capsule the receiver holds."""

    def __init__(self, team: str, expected: str | None, actual: str) -> None:
        super().__init__(expected, actual)
        self.team = team


class TeamView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    team: Team
    run_id: UUID
    capsule_digest: str = Field(pattern=r"^[0-9a-f]{64}$")   # the sealed capsule this view was cut from
    body: dict                                                # JSON-native, allow-listed projection
    view_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


def view_digest(team: str, run_id: UUID | str, capsule_digest: str, body: dict) -> str:
    return sha256_hex({"team": team, "run_id": str(run_id), "capsule_digest": capsule_digest, "body": body})


def _pick(d: dict, fields: tuple[str, ...]) -> dict:
    return {k: d[k] for k in fields if k in d}


def _keys(obj) -> list[str]:
    if isinstance(obj, dict):
        return [*obj, *(k for v in obj.values() for k in _keys(v))]
    if isinstance(obj, list):
        return [k for v in obj for k in _keys(v)]
    return []


def _project(case: CaseFile, team: Team) -> dict:
    c = case.model_dump(mode="json")
    body = {
        "request_text": c["request_text"], "intent": c["intent"],
        "subject": _pick(c["subject"], SUBJECT_FIELDS[team]),
        "peer": _pick(c["peer"], ("source_id", "display_name")) if c["peer"] else None,
        "actions": [{**_pick(a, ACTION_FIELDS[team]), "target": _pick(a["target"], TARGET_FIELDS[team])}
                    for a in c["actions"]],
        **{k: c[k] for k in CASE_FIELDS[team]},
    }
    if EVIDENCE_FIELDS[team]:
        body["evidence"] = [_pick(e, EVIDENCE_FIELDS[team]) for e in c["evidence"]]
    if team == "security" and (leaks := sorted({k for k in _keys(body) if SALARY_LIKE.search(k)})):
        raise ValueError(f"salary-like fields may never reach Security (CLAUDE.md §16): {leaks}")
    return body


def build_team_view(case: CaseFile, team: Team) -> TeamView:
    """Cut one team's view from a sealed capsule. An unsealed or altered capsule is never handed off."""
    verify(case)
    body = _project(case, team)
    return TeamView(team=team, run_id=case.run_id, capsule_digest=case.digest, body=body,
                    view_digest=view_digest(team, case.run_id, case.digest, body))


def receive_view(payload: str | bytes | dict, case: CaseFile) -> TeamView:
    """The receiving side of a handoff. `case` is the capsule the receiver holds, already verified (store.load_case)."""
    view = (TeamView.model_validate_json(payload) if isinstance(payload, (str, bytes))
            else TeamView.model_validate(payload))
    own = view_digest(view.team, view.run_id, view.capsule_digest, view.body)
    if own != view.view_digest:
        raise ViewMismatch(view.team, view.view_digest, own)                  # altered in transit
    if view.capsule_digest != case.digest:
        raise ViewMismatch(view.team, case.digest, view.capsule_digest)       # cut from another capsule
    expected = build_team_view(case, view.team)
    if view != expected:
        raise ViewMismatch(view.team, expected.view_digest, view.view_digest)  # not the allow-listed projection
    return view


def hand_over(case: CaseFile) -> dict[str, TeamView]:
    """Every team's view, passed by value (serialised) and verified on receipt, as a real hop would be."""
    return {team: receive_view(build_team_view(case, team).model_dump_json(), case) for team in TEAMS}
