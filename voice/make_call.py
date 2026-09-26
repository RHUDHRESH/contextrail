"""Place one deliberate Vobiz test call through the live ContextRail voice door.

The default is a read-only preflight. ``--dial`` makes exactly one POST; network
errors are reported as an unknown outcome and must never trigger a blind retry.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx
from dotenv import load_dotenv

API_BASE = "https://api.vobiz.ai/api/v1"
E164 = re.compile(r"\+[1-9]\d{7,14}\Z")


@dataclass(frozen=True)
class CallResult:
    ready: bool
    dialed: bool
    call_uuid: str | None
    from_last4: str
    to_last4: str
    outcome: str


def _validate_number(number: str, label: str) -> str:
    if not E164.fullmatch(number):
        raise ValueError(f"{label} must be an E.164 phone number")
    return number


def _public_base(value: str) -> str:
    parsed = urlsplit(value.rstrip("/"))
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or
            parsed.query or parsed.fragment or parsed.hostname in {"localhost", "127.0.0.1", "::1"}):
        raise ValueError("voice URL must be a public HTTPS base URL")
    return value.rstrip("/")


def _credentials(auth_id: str, auth_token: str) -> dict[str, str]:
    if not auth_id or not auth_token:
        raise ValueError("Vobiz account credentials are required")
    return {"X-Auth-ID": auth_id, "X-Auth-Token": auth_token}


def _owned_number(client: httpx.Client, auth_id: str, headers: dict[str, str], selected: str | None) -> str:
    response = client.get(f"{API_BASE}/Account/{quote(auth_id, safe='')}/numbers", headers=headers)
    response.raise_for_status()
    body = response.json()
    items = body.get("items", []) if isinstance(body, dict) else []
    owned = [item.get("e164") for item in items if isinstance(item, dict) and
             item.get("status") == "active" and not item.get("is_blocked") and
             (item.get("voice_enabled") or item.get("capabilities", {}).get("voice"))]
    if selected:
        _validate_number(selected, "from")
        if selected not in owned:
            raise ValueError("selected caller ID is not an active voice-capable Vobiz number on this account")
        return selected
    if len(owned) != 1:
        raise ValueError("select exactly one owned voice-capable caller ID with --from")
    return owned[0]


def _check_voice_health(client: httpx.Client, base: str) -> None:
    response = client.get(f"{base}/health")
    response.raise_for_status()
    body = response.json()
    modes = body.get("modes", {}) if isinstance(body, dict) else {}
    needed = {"vobiz_callbacks": "LIVE", "sarvam": "LIVE", "llm": "LIVE",
              "llm_provider": "SARVAM", "engine": "configured"}
    if body.get("status") != "ok" or any(modes.get(key) != value for key, value in needed.items()):
        raise ValueError("public voice door is not healthy with live Vobiz, Sarvam, Anthropic and engine modes")
    if body.get("base_url", "").rstrip("/") != base:
        raise ValueError("public voice door base URL does not match the call answer URL")


def place_test_call(*, to: str, voice_base: str, auth_id: str, auth_token: str,
              from_number: str | None = None, dial: bool = False,
              transport: httpx.BaseTransport | None = None) -> CallResult:
    """Verify prerequisites and optionally originate one call, without automatic retries."""
    to = _validate_number(to, "to")
    base = _public_base(voice_base)
    headers = _credentials(auth_id, auth_token)
    with httpx.Client(transport=transport, timeout=10.0, follow_redirects=False) as client:
        _check_voice_health(client, base)
        origin = _owned_number(client, auth_id, headers, from_number)
        if not dial:
            return CallResult(True, False, None, origin[-4:], to[-4:], "preflight passed; no call placed")
        payload = {"from": origin, "to": to, "answer_url": f"{base}/answer", "answer_method": "POST",
                   "hangup_url": f"{base}/hangup", "hangup_method": "POST"}
        # A timeout is an unknown outcome; the caller must inspect call history before any repeat.
        response = client.post(f"{API_BASE}/Account/{quote(auth_id, safe='')}/Call/",
                               headers=headers, json=payload)
        response.raise_for_status()
        body = response.json()
        call_uuid = body.get("request_uuid") or body.get("call_uuid") if isinstance(body, dict) else None
        if not isinstance(call_uuid, str) or not call_uuid:
            return CallResult(True, True, None, origin[-4:], to[-4:], "submitted; provider ID absent; inspect calls")
        return CallResult(True, True, call_uuid, origin[-4:], to[-4:], "submitted; awaiting answer callback")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to", required=True, help="Destination in E.164 format")
    parser.add_argument("--from", dest="from_number", help="Owned Vobiz caller ID; inferred if exactly one")
    parser.add_argument("--voice-base", help="Public HTTPS voice base, e.g. https://host/voice")
    parser.add_argument("--dial", action="store_true", help="Place one billable outbound call after preflight")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    load_dotenv(Path(__file__).resolve().parent / ".env")
    base = args.voice_base or os.getenv("VOICE_PUBLIC_URL") or os.getenv("PUBLIC_URL", "").rstrip("/") + "/voice"
    try:
        result = place_test_call(to=args.to, voice_base=base, auth_id=os.getenv("VOBIZ_AUTH_ID", ""),
                           auth_token=os.getenv("VOBIZ_AUTH_TOKEN", ""), from_number=args.from_number,
                           dial=args.dial)
    except (ValueError, httpx.HTTPError, json.JSONDecodeError) as exc:
        # Exceptions may contain URLs; print only the class, never credentials or phone numbers.
        print(json.dumps({"ready": False, "dialed": False, "error": type(exc).__name__,
                          "note": "preflight or call failed; inspect provider call history before retrying"}))
        return 1
    print(json.dumps(asdict(result)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

