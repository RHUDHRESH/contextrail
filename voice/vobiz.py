"""Vobiz specifics the voice door relies on: callback signatures and the VobizXML documents it returns.

Signatures (vobiz.ai/docs/concepts/validating-callbacks): Vobiz signs every callback with the account auth token.
  X-Vobiz-Signature-V3 = base64(HMAC-SHA256(auth_token, baseURL + "." + nonce)), nonce in X-Vobiz-Signature-V3-Nonce
  X-Vobiz-Signature-V2 = base64(HMAC-SHA256(auth_token, baseURL + nonce)),       nonce in X-Vobiz-Signature-V2-Nonce
baseURL is the URL Vobiz called, without its query string. Behind Caddy the service sees /answer, so the URL is
rebuilt from the public base (https://<host>/voice) and the path.

XML (vobiz-ai/Vobiz-Sarvam server.py and Agent-Skills vobiz-voice-xml): the stream URL is the text of <Stream>,
not an attribute; contentType asks for mu-law 8 kHz, which the audio path expects throughout.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import threading
import time
from collections.abc import Mapping
from urllib.parse import quote
from xml.sax.saxutils import escape

import httpx


def _sign(auth_token: str, message: str) -> str:
    return base64.b64encode(hmac.new(auth_token.encode(), message.encode(), hashlib.sha256).digest()).decode()


def signature_valid(url: str, headers: Mapping[str, str], auth_token: str) -> bool:
    if not auth_token:
        return False
    base = url.split("?", 1)[0]
    for version, joiner in (("V3", "."), ("V2", "")):
        sent, nonce = headers.get(f"X-Vobiz-Signature-{version}"), headers.get(f"X-Vobiz-Signature-{version}-Nonce")
        if sent and nonce:
            expected = _sign(auth_token, f"{base}{joiner}{nonce}")
            # a header may carry several comma-separated signatures while a token is being rotated
            return any(hmac.compare_digest(s.strip(), expected) for s in sent.split(","))
    return False


class NonceCache:
    """Single-process replay guard for signed callbacks; not an identity proof."""

    def __init__(self, ttl_seconds: int = 300, max_entries: int = 10000):
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def accept(self, headers: Mapping[str, str]) -> bool:
        nonce = (headers.get("X-Vobiz-Signature-V3-Nonce") or
                 headers.get("X-Vobiz-Signature-V2-Nonce"))
        if not nonce:
            return False
        now = time.monotonic()
        with self._lock:
            self._seen = {key: expiry for key, expiry in self._seen.items() if expiry > now}
            if nonce in self._seen or len(self._seen) >= self.max_entries:
                return False
            self._seen[nonce] = now + self.ttl_seconds
        return True


async def verified_live_caller(call_uuid: str, callback_from: str, callback_to: str, *, auth_id: str,
                               auth_token: str, transport=None) -> str | None:
    """Read an inbound live call from Vobiz and return its caller only on an exact callback match."""
    from calls import normalize_phone

    if not auth_id or not auth_token or not call_uuid or not callback_from or not callback_to:
        return None
    origin, target = normalize_phone(callback_from), normalize_phone(callback_to)
    if not origin or not target:
        return None
    path = quote(call_uuid, safe="")
    try:
        async with httpx.AsyncClient(transport=transport, timeout=3.0) as client:
            response = await client.get(f"https://api.vobiz.ai/api/v1/Account/{quote(auth_id, safe='')}/Call/"
                                        f"{path}/", params={"status": "live"},
                                        headers={"X-Auth-ID": auth_id, "X-Auth-Token": auth_token})
            response.raise_for_status()
            live = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    if (not isinstance(live, dict) or live.get("call_uuid") != call_uuid or
            live.get("direction") != "inbound" or live.get("call_status") != "in-progress" or
            normalize_phone(live.get("from")) != origin or normalize_phone(live.get("to")) != target):
        return None
    return origin


def _doc(body: str) -> str:
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<Response>\n{body}\n</Response>'


def stream_xml(ws_url: str, status_url: str, next_url: str | None = None) -> str:
    """Hold the call on a bidirectional mu-law stream, then hand control back for DTMF or transfer."""
    after = f'<Redirect method="POST">{escape(next_url)}</Redirect>' if next_url else "<Hangup/>"
    return _doc(f"""    <Stream bidirectional="true" keepCallAlive="true"
            contentType="audio/x-mulaw;rate=8000"
            statusCallbackUrl="{escape(status_url)}"
            statusCallbackMethod="POST">
        {escape(ws_url)}
    </Stream>
{after}""")


def gather_xml(action_url: str) -> str:
    """Collect exactly one DTMF digit, then call the same endpoint when no key was pressed."""
    url = escape(action_url)
    return _doc(f'    <Gather action="{url}" method="POST" inputType="dtmf" numDigits="1" '
                f'executionTimeout="15"></Gather>\n<Redirect method="POST">{url}</Redirect>')


def hangup_xml() -> str:
    return _doc("<Hangup/>")


def dial_xml(number: str, action_url: str) -> str:
    """Bridge to a configured human; Vobiz posts DialStatus to action_url when the attempt ends."""
    return _doc(f'<Dial timeout="30" action="{escape(action_url)}" method="POST">'
                f'<Number>{escape(number)}</Number></Dial>\n<Hangup/>')
