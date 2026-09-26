"""Rule schema (checklist T053).

A rule, in YAML:

    id: POL-ACC-004
    title: Repository access ...
    source: {okf: knowledge/policies/access-control-standard.md, clause: "§3"}
    clause_text: "..."                       # quoted verbatim on every verdict this rule decides
    applies_to: {employment_type: [contractor, vendor]}   # Subject fields only; omitted = everyone
    match: {kind: grant, target.system: github}           # action kind + target paths; value or list of values
    conditions:                                           # all must hold; items are expressions or any/all blocks
      - target.repo in subject.sow_repos
      - {any: ["subject.employment_type == 'employee'", "target.permission == 'read'"]}
    verdict: ALLOW                                        # outcome when every condition holds
    approver: manager                                     # required when verdict is HOLD
    escalate: {when: "target.repo_tags contains 'production'", verdict: HOLD, approver: security-oncall}
    else_verdict: REFUSE                                  # outcome when a condition fails; omitted = rule silent
    terminal: true                                        # a terminal REFUSE: no approval path, no exception
    expires_after: 4h                                     # granted access expires (HOLD/ALLOW)
    alternative: target.masked_view                       # what to offer instead when this rule holds or refuses

Paths may start only with: subject, target, action, role, run, decision. Retrieved evidence is not addressable,
so no rule can be influenced by it (P6). This is checked when rules load, not when they run.

`alternative` names a path whose value is offered to the requester alongside a HOLD or REFUSE this rule decides
(POL-DAT-001 offers the masked view named by the catalogue). It is read after the verdict is final and never
changes it.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from contextrail.models import Subject

VerdictKind = Literal["ALLOW", "HOLD", "REFUSE"]
ALLOWED_ROOTS = frozenset({"subject", "target", "action", "role", "run", "decision"})
SUBJECT_FIELDS = frozenset(Subject.model_fields)
APPROVER_ROLES = ("manager", "security-oncall", "incident-commander", "data-owner", "finance", "vp-finance")

_OPS = r"not in|in|==|!=|not contains|contains|>=|<=|>|<"
CONDITION_RE = re.compile(rf"^\s*(?P<left>[A-Za-z_][\w.]*)\s+(?P<op>{_OPS})\s+(?P<right>.+?)\s*$")
_DURATION_RE = re.compile(r"^\d+[mhd]$")


def path_root(path: str) -> str:
    return path.split(".", 1)[0]


def check_path(path: str, where: str) -> str:
    root = path_root(path)
    if root not in ALLOWED_ROOTS:
        raise ValueError(
            f"{where}: path {path!r} starts with {root!r}; rules may only read {sorted(ALLOWED_ROOTS)} "
            "(retrieved evidence is never readable by policy, P6)")
    return path


def _right_is_path(right: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][\w]*(\.[\w]+)+", right)) and path_root(right) in ALLOWED_ROOTS


def check_condition(expr: Any, where: str) -> Any:
    """Validate an expression string or a nested {any|all: [...]} block."""
    if isinstance(expr, str):
        m = CONDITION_RE.match(expr)
        if not m:
            raise ValueError(f"{where}: cannot parse condition {expr!r} (expected '<path> <op> <value|path>')")
        check_path(m["left"], where)
        right = m["right"]
        if re.fullmatch(r"[A-Za-z_][\w]*(\.[\w]+)+", right) and not _right_is_path(right):
            check_path(right, where)  # raises with the P6 message
        return expr
    if isinstance(expr, dict) and len(expr) == 1 and next(iter(expr)) in ("any", "all"):
        items = next(iter(expr.values()))
        if not isinstance(items, list) or not items:
            raise ValueError(f"{where}: {next(iter(expr))!r} needs a non-empty list")
        for i in items:
            check_condition(i, where)
        return expr
    raise ValueError(f"{where}: a condition is a string or a single-key {{any|all: [...]}} block, got {expr!r}")


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    okf: str
    clause: str


class Escalate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    when: str
    verdict: VerdictKind
    approver: str | None = None


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^POL-[A-Z]{3}-\d{3}$")
    title: str
    source: Source
    clause_text: str = Field(min_length=20)
    applies_to: dict[str, list[Any]] = Field(default_factory=dict)
    match: dict[str, Any] = Field(default_factory=dict)
    conditions: list[Any] = Field(default_factory=list)
    verdict: VerdictKind
    approver: str | None = None
    escalate: Escalate | None = None
    else_verdict: VerdictKind | None = None
    terminal: bool = False
    expires_after: str | None = None
    alternative: str | None = None

    @field_validator("applies_to")
    @classmethod
    def _subject_fields_only(cls, v: dict[str, list[Any]]) -> dict[str, list[Any]]:
        unknown = sorted(set(v) - SUBJECT_FIELDS)
        if unknown:
            raise ValueError(f"applies_to may only name Subject fields; unknown: {unknown}")
        return v

    @field_validator("match")
    @classmethod
    def _match_keys(cls, v: dict[str, Any]) -> dict[str, Any]:
        for key in v:
            if key != "kind" and not key.startswith("target."):
                raise ValueError(f"match keys are 'kind' or 'target.<path>', got {key!r}")
        return v

    @field_validator("expires_after")
    @classmethod
    def _duration(cls, v: str | None) -> str | None:
        if v is not None and not _DURATION_RE.match(v):
            raise ValueError("expires_after is like '4h', '90d', '30m'")
        return v

    @model_validator(mode="after")
    def _coherent(self) -> Rule:
        where = self.id
        for c in self.conditions:
            check_condition(c, where)
        for outcome, approver in ((self.verdict, self.approver),
                                  *(((self.escalate.verdict, self.escalate.approver),) if self.escalate else ())):
            if outcome == "HOLD" and not approver:
                raise ValueError(f"{where}: a HOLD outcome must name an approver role")
            if approver and approver not in APPROVER_ROLES:
                raise ValueError(f"{where}: unknown approver role {approver!r}; known: {APPROVER_ROLES}")
        if self.escalate:
            check_condition(self.escalate.when, where)
        if self.terminal and "REFUSE" not in (self.verdict, self.else_verdict):
            raise ValueError(f"{where}: only a rule that can REFUSE may be terminal")
        if self.else_verdict and not self.conditions:
            raise ValueError(f"{where}: else_verdict needs conditions to fail")
        if self.alternative is not None:
            check_path(self.alternative, where)
            if not _right_is_path(self.alternative):
                raise ValueError(f"{where}: alternative must be a dotted path such as 'target.masked_view'")
            outcomes = {self.verdict, self.else_verdict, *((self.escalate.verdict,) if self.escalate else ())}
            if not outcomes & {"HOLD", "REFUSE"}:
                raise ValueError(f"{where}: an alternative is offered on HOLD or REFUSE, and this rule can do neither")
        return self
