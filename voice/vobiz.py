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
from collections.abc import Mapping
from xml.sax.saxutils import escape


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
