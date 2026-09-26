"""Signed decision links for the email door and the Teams ONE-WAY fallback (CLAUDE.md §13.6, §16, D-007, T232).

    token = base64url(payload) + "." + base64url(HMAC-SHA256(DECISION_LINK_SECRET,
                                                            "run_id|action_id|params_hash|approver|decision|exp"))

The payload says what the link claims; the MAC is what makes the claim believable. Verification checks the MAC in
constant time before it looks at anything else, including the expiry, so an unauthenticated `exp` is never trusted.
No field may contain "|", so two different claims can never share one signed string.

A link is a bearer capability for one decision by one named approver on one exact parameter set. It decides nothing
by itself: the POST handler hands it to door.decide, which re-checks identity, params_hash, separation of duties and
first-decision-wins.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

Decision = Literal["approved", "refused"]
LinkFailure = Literal["malformed", "bad_signature", "expired"]
MIN_SECRET_LENGTH = 32
MAX_TOKEN_LENGTH = 2048
_PLACEHOLDERS = {"change-me", "changeme"}
IST = timezone(timedelta(hours=5, minutes=30), "IST")  # the demo's approvers are in India; IST has no DST


def format_ist(moment: datetime) -> str:
    return moment.astimezone(IST).strftime("%d %b %Y %H:%M IST")


class LinkClaims(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID
    action_id: str = Field(min_length=1, max_length=64, pattern=r"^[^|]+$")
    params_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    approver: str = Field(min_length=1, max_length=64, pattern=r"^[^|]+$")  # identity_map.person_id
    decision: Decision
    exp: int  # unix seconds; the link stops working at this instant

    def signed_string(self) -> bytes:
        return "|".join((str(self.run_id), self.action_id, self.params_hash, self.approver, self.decision,
                         str(self.exp))).encode()

    @property
    def expires_at(self) -> datetime:
        return datetime.fromtimestamp(self.exp, UTC)


class LinkError(Exception):
    """The link cannot be used. `claims` is what it *claimed*, when it could be read at all; it is not trusted."""

    def __init__(self, reason: LinkFailure, claims: LinkClaims | None = None) -> None:
        super().__init__(reason)
        self.reason, self.claims = reason, claims


class WeakSecret(ValueError):
    """DECISION_LINK_SECRET is empty, the placeholder, or too short: links are switched off rather than forgeable."""


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class LinkSigner:
    def __init__(self, secret: str | SecretStr) -> None:
        raw = secret.get_secret_value() if isinstance(secret, SecretStr) else secret
        if raw.strip().lower() in _PLACEHOLDERS or len(raw) < MIN_SECRET_LENGTH:
            raise WeakSecret(f"DECISION_LINK_SECRET must be at least {MIN_SECRET_LENGTH} random characters")
        self._key = raw.encode()

    def _mac(self, claims: LinkClaims) -> bytes:
        return hmac.new(self._key, claims.signed_string(), hashlib.sha256).digest()

    def sign(self, claims: LinkClaims) -> str:
        payload = json.dumps(claims.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        return f"{_b64encode(payload)}.{_b64encode(self._mac(claims))}"

    def verify(self, token: str, *, now: datetime | None = None) -> LinkClaims:
        if not token or len(token) > MAX_TOKEN_LENGTH or token.count(".") != 1:
            raise LinkError("malformed")
        payload, mac = token.split(".")
        try:
            claims = LinkClaims.model_validate(json.loads(_b64decode(payload)))
            given = _b64decode(mac)
        except (binascii.Error, ValueError, ValidationError, UnicodeDecodeError) as e:
            raise LinkError("malformed") from e
        if not hmac.compare_digest(self._mac(claims), given):
            raise LinkError("bad_signature", claims)
        if (now or datetime.now(UTC)).timestamp() >= claims.exp:
            raise LinkError("expired", claims)
        return claims
