"""Test helpers for the knowledge bundle: a writable, re-dated copy of the shipped bundle."""

from __future__ import annotations

import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

from contextrail.knowledge.okf import knowledge_dir


def fresh_copy(tmp_path: Path, *, drop_clause: str | None = None, verified: str | None = None) -> Path:
    """Copy the shipped bundle under tmp_path, re-verified today (or on `verified`) so no test depends on the
    calendar; optionally with one clause text cut out of every page that carries it."""
    root = tmp_path / "knowledge"
    shutil.copytree(knowledge_dir(), root)
    day = verified or datetime.now(UTC).date().isoformat()
    for f in root.rglob("*.md"):
        text = re.sub(r"^last_verified: .*$", f"last_verified: {day}", f.read_text(encoding="utf-8"),
                      flags=re.MULTILINE)
        if drop_clause:
            text = text.replace(drop_clause, "(clause removed)")
        f.write_text(text, encoding="utf-8", newline="\n")
    return root


def edit(root: Path, rel: str, old: str, new: str) -> None:
    """Replace one exact piece of text in a bundle file; fails loudly if it is not there."""
    p = root / rel
    text = p.read_text(encoding="utf-8")
    assert old in text, f"{rel} does not contain {old!r}"
    p.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
