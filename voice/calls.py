"""Live calls known to this voice service, keyed by Vobiz CallUUID.

A call is registered by the signed answer callback, which is the only place the caller's number is trusted. The
media WebSocket then proves it belongs to that call with an unguessable per-call token in its URL, so neither a
CallUUID seen elsewhere nor a forged socket can borrow a caller's identity. The Dialogue lives here, not on the
socket, so the conversation survives the stream being stopped and restarted (DTMF capture, transfer).

State is per process: run one uvicorn worker (the Dockerfile does).
"""

from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass, field

from dialogue import Dialogue

_MAX_AGE_S = 4 * 3600  # a call whose hangup callback never arrived is forgotten after this


def normalize_phone(raw: str | None) -> str | None:
    """E.164 (+ and 11-15 digits) or None. A number without a country code cannot be matched safely, so it is not
    guessed at: such a caller is simply unknown."""
    if not raw:
        return None
    digits = re.sub(r"[\s().-]", "", raw)
    if digits.startswith("+"):
        digits = digits[1:]
    elif len(digits) < 11:
        return None
    return f"+{digits}" if digits.isdigit() and 11 <= len(digits) <= 15 else None


@dataclass
class Call:
    call_uuid: str
    caller: str | None  # E.164, set only when the answer callback was signed by Vobiz
    token: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    started: float = field(default_factory=time.monotonic)
    dialogue: Dialogue | None = None


class CallRegistry:
    def __init__(self) -> None:
        self._calls: dict[str, Call] = {}

    def register(self, call_uuid: str, caller: str | None) -> Call:
        now = time.monotonic()
        for uuid in [u for u, c in self._calls.items() if now - c.started > _MAX_AGE_S]:
            del self._calls[uuid]
        existing = self._calls.get(call_uuid)
        if existing is not None:  # Vobiz retried the answer callback: same call, same conversation
            return existing
        call = self._calls[call_uuid] = Call(call_uuid, caller)
        return call

    def get(self, call_uuid: str) -> Call | None:
        return self._calls.get(call_uuid)

    def by_token(self, token: str) -> Call | None:
        return next((c for c in self._calls.values() if secrets.compare_digest(c.token, token)), None)

    def drop(self, call_uuid: str) -> None:
        self._calls.pop(call_uuid, None)
