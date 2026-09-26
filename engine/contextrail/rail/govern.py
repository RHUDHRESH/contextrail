"""Govern (CLAUDE.md §8): build every candidate action, then let the policy engine decide each one.

AI does nothing here. Candidates come from records (who holds what, the role catalogue, the SOW); verdicts come
from `policy/engine.py` over the Subject record. Untrusted evidence is not an input to either step.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from contextrail.models import Action, Subject, Verdict
from contextrail.policy.engine import PolicyEngine, RuleOutcome, apply_decision
from contextrail.rail.compile import CompileInputs

_EVERYTHING = re.compile(r"\beverything\b", re.IGNORECASE)


def _grant(n: int, ent: str, catalog: dict, subject: Subject, origin: str) -> Action:
    target = {**catalog[ent], "entitlement": ent, "origin": origin, "subject_id": subject.source_id}
    return Action.create(f"A{n:02d}", "grant", target)


def build_candidates(intent: str, request_text: str, subject: Subject, inputs: CompileInputs,
                     peer: Subject | None = None) -> list[Action]:
    """T095: the actions this request could mean, before any policy is applied."""
    held = set(inputs.subject_holdings)
    catalog = inputs.catalog
    if intent == "access.same_as_peer":
        wanted = [e for e in inputs.peer_holdings if e not in held]
        return [_grant(i, e, catalog, subject, "same_as_peer") for i, e in enumerate(wanted, 1)]
    if intent == "onboarding":
        wanted = [e for e in inputs.role.get("baseline", []) if e not in held]
        sow = {t["repo"]: e for e, t in catalog.items() if t.get("system") == "github"}
        wanted += [sow[r] for r in subject.sow_repos if r in sow and sow[r] not in wanted and sow[r] not in held]
        if _EVERYTHING.search(request_text) and subject.team:
            # "Give her everything" means everything her team has, which is exactly what policy must filter.
            wanted += [e for e, t in catalog.items()
                       if subject.team in t.get("teams", []) and e not in wanted and e not in held]
        return [_grant(i, e, catalog, subject, "onboarding") for i, e in enumerate(wanted, 1)]
    return []


@dataclass(frozen=True)
class Governed:
    action: Action
    verdict: Verdict
    fired: tuple[RuleOutcome, ...]


def evaluate(actions: list[Action], subject: Subject, engine: PolicyEngine, *, role: dict,
             requested_by: str | None, now: datetime | None = None) -> list[Governed]:
    """T096: every candidate through the policy engine; the verdict is stamped on the action once, with the
    rule's time box as expires_at (T068)."""
    now = now or datetime.now(UTC)
    out = []
    for a in actions:
        decision = engine.decide(a, subject, role=role, run={"requested_by": requested_by})
        out.append(Governed(apply_decision(a, decision, now=now), decision.verdict, decision.fired))
    return out
