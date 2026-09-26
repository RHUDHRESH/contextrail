"""Tier 4 replay store (T112, CLAUDE.md §11): recorded model answers for the demo script, served flagged replay=true.

Record mode saves every live answer; replay mode serves them as the last tier of the chain. A recording is one JSON
file named by its key: sha256 over the canonical {model, system + policy text, messages, tools}. max_tokens and
temperature are not in the key; they limit an answer, they do not change the question. The request is stored next
to the answer and re-hashed on load, so a hand-edited or renamed file is a miss, never a wrong answer.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from contextrail.canonical import sha256_hex


def request_for(*, model: str, system: str, policy_text: str | None, messages: list, tools: list | None) -> dict:
    """The keyed part of a call, as stored beside the answer."""
    return {"model": model, "system": system, "policy_text": policy_text, "messages": messages, "tools": tools or []}


def replay_key(**request) -> str:
    return sha256_hex(request_for(**request))


class ReplayStore:
    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def save(self, *, request: dict, response: dict, recorded_from: dict) -> str:
        key = sha256_hex(request)
        self.directory.mkdir(parents=True, exist_ok=True)
        doc = {"key": key, "model": request["model"], "recorded_at": datetime.now(UTC).isoformat(),
               "recorded_from": recorded_from, "request": request, "response": response}
        self._path(key).write_text(json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                                   encoding="utf-8")
        return key

    def load(self, key: str) -> dict[str, Any] | None:
        """The recorded response for this key, or None (absent, unreadable, or not matching its own request)."""
        try:
            doc = json.loads(self._path(key).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if doc.get("key") != key or sha256_hex(doc.get("request")) != key:
            return None
        return doc.get("response")
