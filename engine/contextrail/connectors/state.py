"""Persistent state for FIXTURE connectors.

Seeds are read-only in `fixtures/`. Each fixture connector works on its own copy in the state directory
(`STATE_DIR`, default `<repo>/.state`), so a demo run really changes something that `verify()` can read back and
`reset` (T082) can restore. Writes are atomic (temp file + os.replace) and serialised per connector.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from contextrail.fixtures import fixtures_dir
from contextrail.settings import get_settings

_REPO_ROOT = Path(__file__).resolve().parents[3]


def state_dir() -> Path:
    return Path((os.environ.get("STATE_DIR") or get_settings().state_dir) or _REPO_ROOT / ".state")


class FixtureState:
    """A JSON document on disk, seeded from fixtures/<name>.json, with an idempotency ledger and fault switches."""

    def __init__(self, name: str, *, directory: Path | None = None, seeds: Path | None = None) -> None:
        self.name = name
        self.path = (directory or state_dir()) / f"{name}.json"
        self.seed_path = (seeds or fixtures_dir()) / f"{name}.json"
        self._lock = asyncio.Lock()

    def reset(self) -> None:
        doc = json.loads(self.seed_path.read_text(encoding="utf-8"))
        doc["_ledger"] = {}   # idempotency key -> result of the first application
        doc["_faults"] = {}   # target key -> "ack_without_apply" | "timeout_after_apply" | "timeout_before_apply" | "transient_once"
        self._write(doc)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            self.reset()
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, doc: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=f".{self.name}.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=1, sort_keys=True)
        os.replace(tmp, self.path)

    async def mutate(self, fn) -> Any:
        """Run fn(doc) under the lock and persist the document. Returns fn's result."""
        async with self._lock:
            doc = self.load()
            result = fn(doc)
            self._write(doc)
            return result

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self.load())

    async def inject_fault(self, key: str, fault: str) -> None:
        """Test and demo hook: make the next write for `key` misbehave (see _faults)."""
        await self.mutate(lambda d: d["_faults"].__setitem__(key, fault))
