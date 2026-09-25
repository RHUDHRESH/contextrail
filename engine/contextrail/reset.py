"""Restore FIXTURE connector state between demo runs (checklist T082).

    python -m contextrail.reset

Resets every FIXTURE connector to its seed and reports what was undone, so the operator sees what the previous
run changed. The database is not touched: the audit chain is append-only by design (0002), and a clean demo
database means a fresh database (`make reset` in deployment), not rewritten history.
"""

from __future__ import annotations

import json
import sys

from contextrail.connectors.state import FixtureState
from contextrail.seed import FIXTURE_CONNECTORS

_BOOKKEEPING = ("_ledger", "_faults")


def _content(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k not in _BOOKKEEPING}


def _count_changes(before: object, after: object) -> int:
    """Number of leaf values that differ between two JSON documents."""
    if isinstance(before, dict) and isinstance(after, dict):
        return sum(_count_changes(before.get(k), after.get(k)) for k in set(before) | set(after))
    if isinstance(before, list) and isinstance(after, list):
        if all(isinstance(x, str) for x in before + after):
            return len(set(before) ^ set(after))
        return sum(_count_changes(b, a) for b, a in zip(before, after, strict=False)) + abs(len(before) - len(after))
    return int(before != after)


def reset_all(directory=None) -> dict[str, dict]:
    report = {}
    for name in FIXTURE_CONNECTORS:
        state = FixtureState(name, directory=directory)
        before = json.loads(state.path.read_text(encoding="utf-8")) if state.path.exists() else None
        state.reset()
        seed = _content(json.loads(state.seed_path.read_text(encoding="utf-8")))
        report[name] = {
            "changes_undone": _count_changes(_content(before), seed) if before else 0,
            "writes_forgotten": len(before.get("_ledger", {})) if before else 0,
            "created": before is None,
        }
    return report


def main(argv: list[str]) -> int:
    for name, r in reset_all().items():
        note = "created from seed" if r["created"] else (
            f"{r['changes_undone']} change(s) undone, {r['writes_forgotten']} idempotency key(s) cleared")
        print(f"{name:13} FIXTURE  {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
