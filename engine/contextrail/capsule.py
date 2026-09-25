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
