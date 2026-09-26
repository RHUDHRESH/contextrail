"""Inbound webhooks. POST /v1/webhooks/freshservice starts the rail for a Freshservice ticket (CLAUDE.md §13.2).

Signature scheme (checklist T132, §16). Every delivery carries two headers:

    X-ContextRail-Timestamp: <unix time in seconds>
    X-ContextRail-Signature: sha256=<hex HMAC-SHA256(key=FS_WEBHOOK_SECRET, msg="<timestamp>.<raw request body>")>

- The signature covers the exact bytes received and the timestamp, so neither can be changed after signing.
- It is compared in constant time (hmac.compare_digest).
- A timestamp more than 300 s from the engine's clock is refused, in either direction. Inside that window, a
  replayed delivery is absorbed by the dedupe on ticket id (T133), which serves as the nonce table.
- No FS_WEBHOOK_SECRET configured -> every delivery is refused (503). The endpoint never runs unsigned.
- The signature is checked before the body is parsed; the body is capped at 16 KB.

`sign()` produces the header value, for callers and tests.

Freshservice Workflow Automator's Web Request node offers Basic, API-key or no auth and cannot compute an HMAC
(support.freshservice.com, "Web Request Node"). A signing hop is therefore needed between Workflow Automator and
this endpoint, or a decision to accept a weaker static secret. See D-016 (open).
"""

from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from contextrail.connectors.freshservice import fs_id
from contextrail.logs import get_logger

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

TOLERANCE_SECONDS = 300
MAX_BODY_BYTES = 16 * 1024
_PREFIX = "sha256="


class SignatureError(Exception):
    pass


def sign(secret: str, body: bytes, timestamp: int) -> str:
    mac = hmac.new(secret.encode("utf-8"), f"{timestamp}.".encode() + body, hashlib.sha256)
    return _PREFIX + mac.hexdigest()


def verify_signature(secret: str, body: bytes, signature: str | None, timestamp: str | None, *, now: float) -> None:
    """Raise SignatureError unless `signature` is sign(secret, body, timestamp) and the timestamp is fresh."""
    if not signature or not timestamp:
        raise SignatureError("missing X-ContextRail-Signature or X-ContextRail-Timestamp")
    if not (timestamp.isascii() and timestamp.isdigit()):
        raise SignatureError("timestamp must be unix seconds")
    if abs(now - int(timestamp)) > TOLERANCE_SECONDS:
        raise SignatureError(f"timestamp is outside the {TOLERANCE_SECONDS} s window")
    if not signature.lower().startswith(_PREFIX):
        raise SignatureError("signature format must be sha256=<hex>")
    expected = sign(secret, body, int(timestamp))
    if not hmac.compare_digest(expected.encode(), signature.lower().encode()):
        raise SignatureError("signature does not match")


class FreshserviceDelivery(BaseModel):
    """What Workflow Automator sends: {"ticket_id": {{ticket.id_numeric}}}. Other keys are ignored."""

    model_config = ConfigDict(extra="ignore")

    ticket_id: int

    @field_validator("ticket_id", mode="before")
    @classmethod
    def _numeric_id(cls, v: object) -> int:
        try:
            return fs_id(v)
        except (ValueError, TypeError) as e:
            raise ValueError(f"ticket_id must be a positive integer ({{{{ticket.id_numeric}}}}): {e}") from e


async def _signed_body(request: Request) -> bytes:
    secret = request.app.state.settings.fs_webhook_secret.get_secret_value()
    if not secret:
        raise HTTPException(503, "FS_WEBHOOK_SECRET is not configured; unsigned webhooks are refused")
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(413, f"body larger than {MAX_BODY_BYTES} bytes")
    try:
        verify_signature(secret, body, request.headers.get("x-contextrail-signature"),
                         request.headers.get("x-contextrail-timestamp"), now=time.time())
    except SignatureError as e:
        get_logger("contextrail.webhooks").warning("webhook.refused", source="freshservice", reason=str(e))
        raise HTTPException(401, str(e)) from e
    return body


@router.post("/freshservice", status_code=202)
async def freshservice(request: Request) -> JSONResponse:
    body = await _signed_body(request)
    try:
        delivery = FreshserviceDelivery.model_validate_json(body)
    except ValidationError as e:
        raise HTTPException(422, "; ".join(err["msg"] for err in e.errors())) from e
    return JSONResponse({"accepted": True, "ticket_id": delivery.ticket_id}, status_code=202)
