"""The policy engine (checklist T058, T059, T060). Deterministic code over records; the only producer of Verdicts.

Semantics (CLAUDE.md §9):
1. Candidate rules: `applies_to` holds for the Subject record and `match` holds for the action.
2. Each candidate fires at most one outcome: its `verdict` when all conditions hold (possibly raised by
   `escalate`), its `else_verdict` when a condition fails, or nothing.
3. Any REFUSE wins (terminal refusals first). Else any HOLD wins, with the most senior approver. Else ALLOW,
   but only when at least one rule explicitly allowed. Nothing fired means DEFAULT-DENY: nothing executes
   without a written rule that allows it.
4. The verdict carries the deciding rule's id and its clause text verbatim.

`decide()` has no parameter for evidence, messages or model output: the engine cannot be handed retrieved
text, so retrieved text cannot change a verdict (P6).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from contextrail.models import Action, Subject, Verdict
from contextrail.policy.approvers import ApproverDirectory, resolve_approver
from contextrail.policy.conditions import evaluate, evaluate_all
from contextrail.policy.matchers import applies_to, matches
from contextrail.policy.schema import APPROVER_ROLES, Rule

DEFAULT_DENY_ID = "DEFAULT-DENY"
DEFAULT_DENY_CLAUSE = (
    "No written policy allows this action. Under the Access Control & Least Privilege Standard, access and "
    "changes are denied by default until a rule explicitly allows them."
)
_APPROVER_RANK = {role: i for i, role in enumerate(APPROVER_ROLES)}  # later = more senior


@dataclass(frozen=True)
class RuleOutcome:
    rule: Rule
    verdict: str
    approver_role: str | None
    via: str  # "verdict" | "escalate" | "else"


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    fired: tuple[RuleOutcome, ...]  # every rule that produced an outcome, for explanations and Policy Studio


def build_context(action: Action, subject: Subject, *, role: dict | None = None, run: dict | None = None,
                  decision: dict | None = None) -> dict[str, Any]:
    return {
        "subject": subject.model_dump(mode="python"),
        "target": action.target,
        "action": {"id": action.id, "kind": action.kind},
        "role": role or {},
        "run": run or {},
        "decision": decision or {},
    }


def rule_outcome(rule: Rule, ctx: dict) -> RuleOutcome | None:
    if evaluate_all(rule.conditions, ctx):
        if rule.escalate and evaluate(rule.escalate.when, ctx):
            return RuleOutcome(rule, rule.escalate.verdict, rule.escalate.approver, "escalate")
        return RuleOutcome(rule, rule.verdict, rule.approver, "verdict")
    if rule.else_verdict:
        return RuleOutcome(rule, rule.else_verdict, None, "else")
    return None


class PolicyEngine:
    def __init__(self, rules: list[Rule], directory: ApproverDirectory | None = None) -> None:
        self.rules = sorted(rules, key=lambda r: r.id)
        self.directory = directory

    def decide(self, action: Action, subject: Subject, *, role: dict | None = None, run: dict | None = None,
               decision: dict | None = None, disabled: frozenset[str] = frozenset()) -> Decision:
        """Evaluate one action. `disabled` holds rule ids out (Policy Studio only; never in a real run)."""
        ctx = build_context(action, subject, role=role, run=run, decision=decision)
        fired = tuple(
            o for r in self.rules
            if r.id not in disabled and applies_to(r, subject) and matches(r, action)
            if (o := rule_outcome(r, ctx)) is not None
        )
        return Decision(verdict=self._resolve(fired, subject, (run or {}).get("requested_by")), fired=fired)

    def _resolve(self, fired: tuple[RuleOutcome, ...], subject: Subject, requested_by: str | None) -> Verdict:
        refusals = [o for o in fired if o.verdict == "REFUSE"]
        if refusals:
            top = min(refusals, key=lambda o: (not o.rule.terminal, o.rule.id))
            return Verdict(verdict="REFUSE", rule_id=top.rule.id, clause_text=top.rule.clause_text,
                           terminal=top.rule.terminal)
        holds = [o for o in fired if o.verdict == "HOLD"]
        if holds:
            top = max(holds, key=lambda o: (_APPROVER_RANK.get(o.approver_role or "", -1), _neg(o.rule.id)))
            approver = resolve_approver(self.directory, top.approver_role, subject, requested_by=requested_by)
            return Verdict(verdict="HOLD", rule_id=top.rule.id, clause_text=top.rule.clause_text, approver=approver)
        allows = [o for o in fired if o.verdict == "ALLOW"]
        if allows:
            top = min(allows, key=lambda o: o.rule.id)
            return Verdict(verdict="ALLOW", rule_id=top.rule.id, clause_text=top.rule.clause_text)
        return Verdict(verdict="REFUSE", rule_id=DEFAULT_DENY_ID, clause_text=DEFAULT_DENY_CLAUSE)


def _neg(rule_id: str) -> tuple[int, ...]:
    # Tie-break for max(): lower rule id wins among equally senior approvers.
    return tuple(-ord(c) for c in rule_id)


def check_decision(engine: PolicyEngine, subject: Subject, *, action_id: str, params_hash: str, approver: str,
                   requested_by: str | None, beneficiary: str | None) -> Verdict:
    """Separation of duties for any door's approval (POL-SOD-001), evaluated by the same engine as everything else.

    An unknown requester or beneficiary makes the check fail: an approval nobody can attribute is refused.
    """
    synthetic = Action.create(f"{action_id}:decision", "approval_decision",
                              {"action_id": action_id, "params_hash": params_hash})
    run = {k: v for k, v in (("requested_by", requested_by), ("beneficiary", beneficiary)) if v}
    return engine.decide(synthetic, subject, run=run, decision={"approver": approver}).verdict
