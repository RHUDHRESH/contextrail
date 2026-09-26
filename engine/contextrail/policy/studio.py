"""Policy Studio (checklist T072): "if this rule did not exist, what would this run have done?"

A service manager asks that before editing a rule. The Studio re-evaluates every action of a governed run twice
with today's rules, once as they are and once with one rule held out (`PolicyEngine.decide(disabled=...)`), and
reports the verdict diff per action plus a blast-radius summary. It also compares today's baseline with the verdict
the run recorded, so a diff computed against rules that have changed since the run is flagged as drift rather than
passed off as the run's own history.

It is a simulation. It reads a case file and writes nothing: no verdict, no action state, no audit row. Holding out
a terminal rule is allowed as analysis, and the report says the rule is terminal; the Studio grants no exception.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from contextrail.models import Action, CaseFile, Verdict
from contextrail.policy.engine import PolicyEngine

Change = Literal["none", "loosened", "tightened", "same_verdict"]
_STRICTNESS = {"ALLOW": 0, "HOLD": 1, "REFUSE": 2}


class UnknownRule(KeyError):
    """The rule to hold out is not one the engine has loaded."""


class Outcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    verdict: Literal["ALLOW", "HOLD", "REFUSE"]
    rule_id: str
    approver: str | None = None
    terminal: bool | None = None  # None: not recorded (a stored action keeps no terminal flag)

    @classmethod
    def of(cls, v: Verdict) -> Outcome:
        return cls(verdict=v.verdict, rule_id=v.rule_id, approver=v.approver, terminal=v.terminal)

    def same_decision(self, other: Outcome) -> bool:
        return (self.verdict, self.rule_id, self.approver) == (other.verdict, other.rule_id, other.approver)


class ActionDiff(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: str
    kind: str
    label: str
    stored: Outcome | None  # what the run recorded; None if the action was never governed
    before: Outcome         # today's rules, nothing held out
    after: Outcome          # today's rules, the one rule held out
    change: Change
    drift: bool             # today's baseline differs from what the run recorded


class BlastRadius(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    examined: int
    changed: int
    loosened: int           # REFUSE -> HOLD/ALLOW, or HOLD -> ALLOW
    tightened: int          # ALLOW -> HOLD/REFUSE, or HOLD -> REFUSE
    same_verdict: int       # same verdict, decided by another rule or approver
    unblocked: int          # was refused, would not be
    loses_approval: int     # was held for a person, would not be
    newly_refused: int      # was not refused, would be
    drift: int
    before: dict[str, int]  # allow / hold / refuse tallies
    after: dict[str, int]
    headline: str


class StudioReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID
    hold_out: str
    rule_title: str
    rule_terminal: bool
    capsule_digest: str | None
    simulation: Literal[True] = True  # nothing was written
    actions: list[ActionDiff]
    blast_radius: BlastRadius


def simulate_hold_out(case: CaseFile, engine: PolicyEngine, rule_id: str, *, role: dict,
                      requested_by: str | None) -> StudioReport:
    """Re-evaluate every action in `case` with and without `rule_id`. `role` and `requested_by` must be what Govern
    used for this run (the role catalogue entry and the run's requester), so the baseline reproduces the run."""
    rule = next((r for r in engine.rules if r.id == rule_id), None)
    if rule is None:
        raise UnknownRule(rule_id)
    run = {"requested_by": requested_by}
    rows = []
    for stored in case.actions:
        action = Action.create(stored.id, stored.kind, stored.target)  # a fresh copy: the case is never touched
        before = Outcome.of(engine.decide(action, case.subject, role=role, run=run).verdict)
        after = Outcome.of(engine.decide(action, case.subject, role=role, run=run,
                                         disabled=frozenset({rule_id})).verdict)
        recorded = (Outcome(verdict=stored.verdict, rule_id=stored.rule_id or "", approver=stored.approver)
                    if stored.verdict else None)
        rows.append(ActionDiff(
            action_id=stored.id, kind=stored.kind, label=_label(stored), stored=recorded, before=before, after=after,
            change=_change(before, after), drift=recorded is not None and not recorded.same_decision(before)))
    return StudioReport(run_id=case.run_id, hold_out=rule_id, rule_title=rule.title, rule_terminal=rule.terminal,
                        capsule_digest=case.digest, actions=rows,
                        blast_radius=_blast_radius(rows, rule_id, rule.terminal))


def _label(action: Action) -> str:
    t = action.target
    return str(t.get("entitlement") or t.get("label") or action.id)


def _change(before: Outcome, after: Outcome) -> Change:
    delta = _STRICTNESS[after.verdict] - _STRICTNESS[before.verdict]
    if delta < 0:
        return "loosened"
    if delta > 0:
        return "tightened"
    return "none" if before.same_decision(after) else "same_verdict"


def _tally(outcomes: list[Outcome]) -> dict[str, int]:
    out = {"allow": 0, "hold": 0, "refuse": 0}
    for o in outcomes:
        out[o.verdict.lower()] += 1
    return out


def _n(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def _blast_radius(rows: list[ActionDiff], rule_id: str, terminal: bool) -> BlastRadius:
    def count(pred) -> int:
        return sum(1 for r in rows if pred(r))

    unblocked = count(lambda r: r.before.verdict == "REFUSE" and r.after.verdict != "REFUSE")
    loses_approval = count(lambda r: r.before.verdict == "HOLD" and r.after.verdict == "ALLOW")
    tightened = count(lambda r: r.change == "tightened")
    same_verdict = count(lambda r: r.change == "same_verdict")
    drift = count(lambda r: r.drift)
    changed = count(lambda r: r.change != "none")

    if changed == 0:
        headline = (f"Holding out {rule_id} changes no verdict in this run: it decided nothing here, or another "
                    "rule reaches the same outcome.")
    else:
        effects = []
        if unblocked:
            effects.append(f"{_n(unblocked, 'refused action', 'refused actions')} would no longer be refused")
        if loses_approval:
            effects.append(f"{_n(loses_approval, 'held action', 'held actions')} would skip "
                           f"{'its approver' if loses_approval == 1 else 'their approvers'}")
        if tightened:
            effects.append(f"{_n(tightened, 'action', 'actions')} would get a stricter outcome")
        if same_verdict:
            effects.append(f"{_n(same_verdict, 'action', 'actions')} would keep "
                           f"{'its verdict' if same_verdict == 1 else 'their verdicts'} under another rule")
        headline = f"Without {rule_id}: {'; '.join(effects)}."
        if terminal and unblocked:
            headline += f" {rule_id} is terminal: this is a simulation, and no exception can be granted."
    if drift:
        headline = (f"{_n(drift, 'action is', 'actions are')} decided differently today than when this run was "
                    f"governed; the diff uses today's rules. {headline}")
    return BlastRadius(
        examined=len(rows), changed=changed, loosened=count(lambda r: r.change == "loosened"), tightened=tightened,
        same_verdict=same_verdict, unblocked=unblocked, loses_approval=loses_approval,
        newly_refused=count(lambda r: r.before.verdict != "REFUSE" and r.after.verdict == "REFUSE"), drift=drift,
        before=_tally([r.before for r in rows]), after=_tally([r.after for r in rows]), headline=headline)
