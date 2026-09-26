"""FIXTURE data access (checklist section F). Seeds live in the repo's `fixtures/` directory, read-only.

Anything served from here is labelled FIXTURE by the connector that uses it (CLAUDE.md §0 rule 4, D-004).
"""

from __future__ import annotations

import json
import os
from functools import cache
from pathlib import Path
from typing import Any

from contextrail.models import Subject
from contextrail.settings import get_settings

_REPO_ROOT = Path(__file__).resolve().parents[2]


def fixtures_dir() -> Path:
    return Path((os.environ.get("FIXTURES_DIR") or get_settings().fixtures_dir) or _REPO_ROOT / "fixtures")


@cache
def _load(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load(name: str, directory: Path | None = None) -> Any:
    """Load fixtures/<name>.json (cached per path). Callers must not mutate the returned object."""
    return _load(str((directory or fixtures_dir()) / f"{name}.json"))


def subject_from_record(record: dict) -> Subject:
    """Project an HRIS record onto the Subject model. Extra HR fields (salary, transfer history...) stay out of the
    capsule unless a stage asks for them explicitly (CLAUDE.md §16 allow-lists)."""
    return Subject(**{k: record[k] for k in Subject.model_fields if k in record})
