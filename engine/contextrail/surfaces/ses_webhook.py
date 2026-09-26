"""SES bounces and complaints, delivered by Amazon SNS: POST /v1/webhooks/ses (CLAUDE.md §12, §16, T237).

A notice is believed only when all of these hold, checked in this order:
1. its TopicArn is the one topic configured in SES_SNS_TOPIC_ARN (a valid SNS signature only proves that *some*
   SNS topic sent it; anyone can own a topic, so a foreign topic is rejected before any certificate is fetched);
2. SigningCertURL is https on an `sns.<region>.amazonaws.com` host and names a .pem file;
3. the certificate from that URL is in date, and the Signature (base64, PKCS#1 v1.5 with SHA1 for
   SignatureVersion 1, SHA256 for 2) verifies over the string to sign: "Key\\nValue\\n" for Message, MessageId,
   Subject (if present), Timestamp, TopicArn, Type (notifications), or Message, MessageId, SubscribeURL, Timestamp,
   Token, TopicArn, Type (subscription confirmations), in that order (AWS SNS developer guide, "Verifying the
   signature of an Amazon SNS message").

SNS retries until it gets a 2xx, so a verified message is recorded once per MessageId (webhook_dedupe). A bounce or
complaint for an email we sent marks that door message, is audited on its run (a recipient count, not addresses),
and a bounce queues `email.undeliverable` so the approval can be chased in another door.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from contextrail import repo
from contextrail.audit import chain
from contextrail.db import Database
from contextrail.logs import get_logger

router = APIRouter(prefix="/v1/webhooks", tags=["email"])
log = get_logger("contextrail.ses_webhook")

MAX_BODY_BYTES = 256 * 1024
_SNS_HOST = re.compile(r"^sns\.[a-z0-9-]+\.amazonaws\.com(\.cn)?$")
_CONFIRMATION_KEYS = ("Message", "MessageId", "SubscribeURL", "Timestamp", "Token", "TopicArn", "Type")
_SIGNED_KEYS = {
    "Notification": ("Message", "MessageId", "Subject", "Timestamp", "TopicArn", "Type"),
    "SubscriptionConfirmation": _CONFIRMATION_KEYS,
    "UnsubscribeConfirmation": _CONFIRMATION_KEYS,
}
_OPTIONAL_KEYS = {"Subject"}
_HASHES = {"1": hashes.SHA1, "2": hashes.SHA256}
_PEM_CACHE: dict[str, bytes] = {}

CertFetcher = Callable[[str], Awaitable[bytes]]
Confirmer = Callable[[str], Awaitable[None]]


class SnsRejected(Exception):
    """The message is not a verified notice from our topic. Nothing is written."""


def string_to_sign(msg: dict) -> bytes:
    keys = _SIGNED_KEYS.get(msg.get("Type"))
    if keys is None:
        raise SnsRejected(f"unknown message type {msg.get('Type')!r}")
    parts = []
    for key in keys:
        if key not in msg:
            if key in _OPTIONAL_KEYS:
                continue
            raise SnsRejected(f"missing {key}")
        parts.append(f"{key}\n{msg[key]}\n")
    return "".join(parts).encode("utf-8")


def is_sns_url(url: str, *, pem: bool = False) -> bool:
    try:
        u = urlsplit(url)
        port = u.port
    except ValueError:
        return False
    return (u.scheme == "https" and not u.username and port in (None, 443)
            and bool(_SNS_HOST.match(u.hostname or "")) and (not pem or u.path.endswith(".pem")))


async def fetch_certificate(url: str) -> bytes:
    """Default fetcher: HTTPS GET from the SNS host, no redirects, cached per URL for the process."""
    if url not in _PEM_CACHE:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
            response = await client.get(url)
            response.raise_for_status()
        if len(_PEM_CACHE) > 32:
            _PEM_CACHE.clear()
        _PEM_CACHE[url] = response.content
    return _PEM_CACHE[url]


async def confirm_subscription(url: str) -> None:
    async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
        (await client.get(url)).raise_for_status()


async def verify_sns(msg: dict, fetch: CertFetcher) -> None:
    version = str(msg.get("SignatureVersion", ""))
    if version not in _HASHES:
        raise SnsRejected(f"unsupported SignatureVersion {version!r}")
    url = str(msg.get("SigningCertURL", ""))
    if not is_sns_url(url, pem=True):
        raise SnsRejected("the signing certificate is not on an SNS host")
    to_sign = string_to_sign(msg)
    try:
        cert = x509.load_pem_x509_certificate(await fetch(url))
        signature = base64.b64decode(str(msg.get("Signature", "")), validate=True)
    except (ValueError, binascii.Error) as e:
        raise SnsRejected(f"unreadable certificate or signature: {type(e).__name__}") from e
    if not cert.not_valid_before_utc <= datetime.now(UTC) <= cert.not_valid_after_utc:
        raise SnsRejected("the signing certificate is out of date")
    key = cert.public_key()
    if not isinstance(key, rsa.RSAPublicKey):
        raise SnsRejected("the signing certificate is not RSA")
    try:
        key.verify(signature, to_sign, padding.PKCS1v15(), _HASHES[version]())
    except InvalidSignature as e:
        raise SnsRejected("bad signature") from e


def _status(code: int, status: str, reason: str | None = None) -> JSONResponse:
    return JSONResponse({"status": status, **({"reason": reason} if reason else {})}, status_code=code)


@router.post("/ses")
async def ses_events(request: Request) -> JSONResponse:
    state = request.app.state
    topic, door = state.settings.ses_sns_topic_arn, getattr(state, "door", None)
    if not topic or door is None:
        return _status(503, "unavailable", "SES_SNS_TOPIC_ARN is not configured; no notice is accepted")
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        return _status(413, "rejected", "body too large")
    try:
        msg = json.loads(body)
    except ValueError:
        return _status(400, "rejected", "not JSON")
    if not isinstance(msg, dict):
        return _status(400, "rejected", "not an SNS message")
    try:
        if msg.get("TopicArn") != topic:
            raise SnsRejected("not our topic")
        await verify_sns(msg, getattr(state, "sns_cert_fetcher", fetch_certificate))
    except SnsRejected as e:
        log.warning("ses_webhook_rejected", reason=str(e), type=msg.get("Type"))
        return _status(403, "rejected", str(e))
    if msg["Type"] == "SubscriptionConfirmation":
        if not is_sns_url(str(msg["SubscribeURL"])):
            return _status(403, "rejected", "SubscribeURL is not an SNS host")
        await getattr(state, "sns_subscription_confirmer", confirm_subscription)(msg["SubscribeURL"])
        return _status(200, "subscribed")
    if msg["Type"] == "UnsubscribeConfirmation":
        return _status(200, "unsubscribe_noted")
    return _status(200, await record_notice(door.db, msg))


async def record_notice(db: Database, msg: dict) -> str:
    """Apply one verified notification exactly once. Returns what happened, for the response and the log."""
    try:
        event = json.loads(msg["Message"])
    except ValueError:
        event = {}
    kind = str(event.get("notificationType") or event.get("eventType") or "").lower()
    async with db.transaction() as c:
        if not await repo.dedupe_webhook(c, "ses", str(msg["MessageId"])):
            return "duplicate"
        if kind not in ("bounce", "complaint"):
            return "ignored"
        ses_message_id = (event.get("mail") or {}).get("messageId")
        row = await (await c.execute(
            "select * from door_messages where channel = 'email' and ref->>'message_id' = %s",
            (ses_message_id,))).fetchone()
        if row is None:
            log.info("ses_notice_for_unknown_message", kind=kind)
            return "unknown_message"
        detail = event.get(kind) or {}
        recipients = detail.get("bouncedRecipients") or detail.get("complainedRecipients") or []
        facts = ({"bounce_type": detail.get("bounceType"), "bounce_sub_type": detail.get("bounceSubType")}
                 if kind == "bounce" else {"feedback_type": detail.get("complaintFeedbackType")})
        await repo.upsert_door_message(c, row["run_id"], "email", {**row["ref"], "delivery": kind, **facts},
                                       action_id=row["action_id"])
        await chain.append(c, run_id=row["run_id"], event=f"email.{kind}", payload={
            "action_id": row["action_id"], "message_id": ses_message_id, **facts, "recipients": len(recipients)})
        if kind == "bounce":
            await repo.enqueue_job(c, "email.undeliverable",
                                   {"run_id": str(row["run_id"]), "action_id": row["action_id"], "event": kind},
                                   dedupe_key=f"email.undeliverable:{msg['MessageId']}")
    return kind
