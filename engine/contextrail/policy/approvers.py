"""Approver resolution (checklist T059): a HOLD names a person, not a role.

Rules name approver *roles* (manager, security-oncall, ...). The directory turns a role into a named person for
this subject. `manager` resolves through the subject record's manager_id; on-call roles through a roster.
The requester is never chosen to approve their own request (POL-SOD-001); if the only candidate is the
requester, the role stays unresolved. An unresolved approver is written `role:<name>` so it is visible, and the
Approve stage treats it as a blocker. Nobody is guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from contextrail.models import Subject

UNRESOLVED_PREFIX = "role:"


class ApproverDirectory(Protocol):
    mode: str  # "LIVE" | "FIXTURE"

    def candidates(self, role: str, subject: Subject) -> list[str]:
        """Person ids who can act for `role` on this subject, in preference order."""
        ...


def resolve_approver(directory: ApproverDirectory | None, role: str, subject: Subject,
                     *, requested_by: str | None = None) -> str:
    if directory is not None:
        for person in directory.candidates(role, subject):
            if person and person != requested_by:
                return person
    return f"{UNRESOLVED_PREFIX}{role}"


def is_unresolved(approver: str | None) -> bool:
    return approver is None or approver.startswith(UNRESOLVED_PREFIX)


@dataclass
class StaticDirectory:
    """FIXTURE directory: an on-call roster per role, plus manager ids mapped to person ids."""

    roster: dict[str, list[str]] = field(default_factory=dict)       # role -> [person_id, backup, ...]
    managers: dict[str, str] = field(default_factory=dict)            # subject.manager_id -> person_id
    mode: str = "FIXTURE"

    def candidates(self, role: str, subject: Subject) -> list[str]:
        if role == "manager":
            person = self.managers.get(subject.manager_id or "", subject.manager_id)
            return [person] if person else []
        return list(self.roster.get(role, []))
