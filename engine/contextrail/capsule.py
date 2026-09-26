"""Sealing the case file (checklist T049).

The digest is sha256 over the canonical JSON of the whole case file except the digest itself. Any change to the
request, subject, evidence, constraints, actions (including state), decisions or blockers changes the digest.
Stages that legitimately change the case re-seal it. Anyone else's change shows up as a mismatch.
"""

from __future__ import annotations

from contextrail.canonical import sha256_hex
from contextrail.models import CaseFile


def compute_digest(case: CaseFile) -> str:
    return sha256_hex(case.model_dump(mode="python", exclude={"digest"}))


def seal(case: CaseFile) -> CaseFile:
    """Return a copy of the case file carrying its digest. The input is not modified."""
    return case.model_copy(update={"digest": compute_digest(case)}, deep=True)


class DigestMismatch(Exception):
    """The case file received is not the case file that was sealed. Halt and audit; never continue on it."""

    def __init__(self, expected: str | None, actual: str) -> None:
        super().__init__(f"capsule digest mismatch: sealed {expected or 'NONE'}, received content hashes to {actual}")
        self.expected, self.actual = expected, actual


def verify(case: CaseFile) -> CaseFile:
    """Raise DigestMismatch unless the case carries a digest that matches its content."""
    actual = compute_digest(case)
    if case.digest != actual:
        raise DigestMismatch(case.digest, actual)
    return case


def receive(payload: str | bytes | dict) -> CaseFile:
    """The handoff boundary: parse a capsule passed by value (JSON or dict), then verify it before any use."""
    case = CaseFile.model_validate_json(payload) if isinstance(payload, (str, bytes)) else CaseFile.model_validate(payload)
    return verify(case)
