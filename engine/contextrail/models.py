"""Domain models (CLAUDE.md §7). Pydantic v2 at every boundary.

The models carry principles, not just shapes:
- P1 relevance is not identity: `Subject.source_id` must look like a system-of-record ID, not a name.
- P6 retrieved text is data: messages and documents are always `trust="untrusted"`; nothing can relabel them.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from contextrail.canonical import params_hash as compute_params_hash


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


EmploymentType = Literal["employee", "contractor", "vendor", "customer"]


class Subject(_Model):
    """The person (or customer) a run is about. Fetched by ID from a system of record, never chosen by search."""

    source: Literal["freshservice", "hris", "freshdesk"]
    source_id: str = Field(min_length=1, max_length=64)
    display_name: str
    employment_type: EmploymentType
    role: str | None = None
    team: str | None = None
    seniority: Literal["junior", "mid", "senior", "lead", "principal"] | None = None
    manager_id: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    sow_repos: list[str] = Field(default_factory=list)

    @field_validator("source_id")
    @classmethod
    def _looks_like_an_id(cls, v: str) -> str:
        # A name ("Anil Kumar") has whitespace; an ID ("W-8841", "50001234") does not. This cannot prove the value
        # came from an exact lookup, but it stops the commonest failure: a display name passed as the subject.
        if any(ch.isspace() for ch in v):
            raise ValueError("source_id must be a system-of-record ID, not a name (P1: relevance is not identity)")
        return v


EvidenceKind = Literal["record", "policy", "document", "message", "precedent"]
Trust = Literal["record", "curated", "untrusted"]

# What each kind of evidence is allowed to be trusted as. Retrieved free text (messages, documents, inbound email
# bodies, voice transcripts) is untrusted, always: it may enter the capsule, and it can still change nothing.
_ALLOWED_TRUST: dict[str, set[str]] = {
    "record": {"record"},
    "policy": {"curated"},
    "precedent": {"curated"},
    "document": {"untrusted"},
    "message": {"untrusted"},
}


class Evidence(_Model):
    # Frozen: evidence is what was retrieved, as retrieved. Freezing also closes a pydantic v2 gap where a rejected
    # assignment still leaves the new value on the object (an injected message would stay relabelled 'curated').
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    kind: EvidenceKind
    source: str                      # 'hris' | 'freshservice' | 'okf' | 'slack' | 'email' | 'voice' ...
    uri: str
    excerpt: str
    retrieved_at: datetime
    last_verified: date | None = None
    stale: bool = False
    trust: Trust

    @model_validator(mode="after")
    def _trust_matches_kind(self) -> Evidence:
        if self.trust not in _ALLOWED_TRUST[self.kind]:
            allowed = ", ".join(sorted(_ALLOWED_TRUST[self.kind]))
            raise ValueError(f"evidence of kind {self.kind!r} must have trust {allowed} (P6), got {self.trust!r}")
        return self

    @field_validator("retrieved_at")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("retrieved_at must be timezone-aware (UTC)")
        return v


class ActionState(StrEnum):
    PLANNED = "planned"
    AWAITING = "awaiting"
    APPROVED = "approved"
    REFUSED = "refused"
    EXECUTED = "executed"
    VERIFIED = "verified"
    FAILED = "failed"
    UNKNOWN = "unknown"      # a write timed out: reconcile before any retry (never blind-retry)


_S = ActionState
# Allowed moves. 'verified' only follows a read-back (P3); 'refused' and 'verified' are terminal.
ACTION_TRANSITIONS: dict[ActionState, frozenset[ActionState]] = {
    _S.PLANNED: frozenset({_S.AWAITING, _S.REFUSED, _S.EXECUTED, _S.UNKNOWN, _S.FAILED}),
    _S.AWAITING: frozenset({_S.APPROVED, _S.REFUSED}),
    _S.APPROVED: frozenset({_S.EXECUTED, _S.UNKNOWN, _S.FAILED}),
    _S.EXECUTED: frozenset({_S.VERIFIED, _S.FAILED}),
    _S.UNKNOWN: frozenset({_S.EXECUTED, _S.VERIFIED, _S.FAILED}),
    _S.FAILED: frozenset(),
    _S.REFUSED: frozenset(),
    _S.VERIFIED: frozenset(),
}


class IllegalTransition(ValueError):
    pass


VerdictKind = Literal["ALLOW", "HOLD", "REFUSE"]


class Action(_Model):
    # Identity fields are frozen: pydantic raises on assignment *before* mutating. (A model_validator alone is not
    # enough: pydantic v2 leaves the new value in place after an after-validator rejects an assignment.)
    id: str = Field(frozen=True)
    kind: str = Field(frozen=True)   # 'grant' | 'revoke' | 'assign_asset' | 'refund' ...
    target: dict = Field(frozen=True)
    params_hash: str = Field(pattern=r"^[0-9a-f]{64}$", frozen=True)
    verdict: VerdictKind | None = None
    rule_id: str | None = None
    clause: str | None = None
    approver: str | None = None
    state: ActionState = ActionState.PLANNED
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def _params_hash_matches(self) -> Action:
        # The hash is what approvals bind to. It must describe this exact kind+target, so a target edited after
        # approval can never keep the old approval (CLAUDE.md §8 Approve: "changed params -> approval void").
        if self.params_hash != compute_params_hash(self.kind, self.target):
            raise ValueError(f"{self.id}: params_hash does not match kind+target; build a new Action instead")
        return self

    @classmethod
    def create(cls, id: str, kind: str, target: dict, **kw) -> Action:
        return cls(id=id, kind=kind, target=target, params_hash=compute_params_hash(kind, target), **kw)

    def transition(self, to: ActionState | str) -> None:
        """Move to a new state or raise. A REFUSE verdict may only ever become 'refused' (P4)."""
        to = ActionState(to)
        if self.verdict == "REFUSE" and to is not ActionState.REFUSED:
            raise IllegalTransition(f"{self.id}: REFUSE is terminal; cannot move to {to} (P4)")
        if to not in ACTION_TRANSITIONS[self.state]:
            raise IllegalTransition(f"{self.id}: {self.state} -> {to} is not allowed")
        self.state = to


class Verdict(_Model):
    """The policy engine's decision for one action. Produced by code (policy/engine.py), never by a model (§0 rule 2)."""

    verdict: VerdictKind
    rule_id: str = Field(min_length=1)       # 'DEFAULT-DENY' when no rule matched an access action
    clause_text: str = Field(min_length=1)   # quoted verbatim from the rule's source
    approver: str | None = None              # named human (or role resolved to one) for HOLD
    terminal: bool = False                   # a terminal REFUSE cannot be approved or overridden

    @model_validator(mode="after")
    def _shape(self) -> Verdict:
        if self.verdict == "HOLD" and not self.approver:
            raise ValueError("a HOLD verdict must name its approver")
        if self.verdict != "HOLD" and self.approver:
            raise ValueError(f"a {self.verdict} verdict has no approver")
        if self.verdict != "REFUSE" and self.terminal:
            raise ValueError("only a REFUSE can be terminal")
        return self


def apply_verdict(action: Action, v: Verdict) -> Action:
    """Stamp a verdict onto a planned action exactly once, moving it to its first state (refused / awaiting)."""
    if action.verdict is not None:
        raise IllegalTransition(f"{action.id}: already has verdict {action.verdict}; verdicts are set once")
    action.verdict, action.rule_id, action.clause, action.approver = v.verdict, v.rule_id, v.clause_text, v.approver
    if v.verdict == "REFUSE":
        action.transition(ActionState.REFUSED)
    elif v.verdict == "HOLD":
        action.transition(ActionState.AWAITING)
    return action


class CaseFile(_Model):
    """The sealed capsule: one object that carries the case through every stage and door, by value (P5)."""

    run_id: UUID
    request_text: str
    intent: str
    subject: Subject
    peer: Subject | None = None                  # "same as <peer>" requests
    evidence: list[Evidence] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    decisions: list[dict] = Field(default_factory=list)
    open_blockers: list[str] = Field(default_factory=list)
    digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _unique_ids(self) -> CaseFile:
        for name, ids in (("action", [a.id for a in self.actions]), ("evidence", [e.id for e in self.evidence])):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            if dupes:
                raise ValueError(f"duplicate {name} ids in case file: {dupes}")
        return self

    def action(self, action_id: str) -> Action:
        for a in self.actions:
            if a.id == action_id:
                return a
        raise KeyError(action_id)
