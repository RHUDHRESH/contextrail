"""Test doubles for the Slack door. No network.

FakeSlackClient subclasses the real AsyncWebClient and replaces only the HTTP send (`_request`), so the SDK still
builds real request arguments and still raises SlackApiError on `{"ok": false}`. Every call is recorded.
`signed_headers` signs a body with Slack's v0 scheme (HMAC-SHA256 over "v0:<ts>:<body>"), computed here rather than
with the SDK's own verifier so the test checks the SDK instead of agreeing with it.
"""

from __future__ import annotations

import hashlib
import hmac
import time

from slack_sdk.web.async_base_client import AsyncBaseClient
from slack_sdk.web.async_client import AsyncWebClient

SIGNING_SECRET = "fake-signing-secret"
BOT_TOKEN = "fake-bot-token"


class FakeSlackClient(AsyncWebClient):
    def __init__(self, *, emails: dict[str, str] | None = None, errors: dict[str, str] | None = None) -> None:
        super().__init__(token=BOT_TOKEN)
        self.calls: list[tuple[str, dict]] = []
        self.emails = {k.lower(): v for k, v in (emails or {}).items()}  # users.lookupByEmail directory
        self.errors = dict(errors or {})                                  # api method -> Slack error code
        self._n = 0

    async def _request(self, *, http_verb, api_url, req_args):  # same signature as AsyncBaseClient._request
        method = api_url.rsplit("/", 1)[-1]
        args: dict = {}
        for key in ("params", "data", "json"):
            if isinstance(req_args.get(key), dict):
                args.update(req_args[key])
        self.calls.append((method, args))
        data = {"ok": False, "error": self.errors[method]} if method in self.errors else self._reply(method, args)
        return {"data": data, "headers": {}, "status_code": 200}

    def _reply(self, method: str, args: dict) -> dict:
        if method == "auth.test":
            return {"ok": True, "user_id": "UBOT00001", "bot_id": "BBOT00001", "team_id": "T0NORTH01",
                    "user": "contextrail"}
        if method == "chat.postMessage":
            self._n += 1
            return {"ok": True, "channel": args["channel"], "ts": f"1790000000.{self._n:06d}"}
        if method == "chat.update":
            return {"ok": True, "channel": args["channel"], "ts": args["ts"]}
        if method == "chat.postEphemeral":
            return {"ok": True, "message_ts": "1790000000.999999"}
        if method == "conversations.open":
            return {"ok": True, "channel": {"id": "D" + args["users"]}}
        if method == "users.lookupByEmail":
            uid = self.emails.get(str(args["email"]).lower())
            return {"ok": True, "user": {"id": uid}} if uid else {"ok": False, "error": "users_not_found"}
        return {"ok": True}

    def called(self, method: str) -> list[dict]:
        return [a for m, a in self.calls if m == method]


def forbid_real_slack_calls(monkeypatch) -> None:
    """Make any real Slack Web API client fail loudly. Bolt builds a fresh AsyncWebClient per request (since
    slack_bolt 1.15), so a handler or middleware that used it instead of the door's client would reach slack.com."""

    async def _no_network(self, *, http_verb, api_url, req_args):
        raise AssertionError(f"real Slack API call attempted in a test: {http_verb} {api_url}")

    monkeypatch.setattr(AsyncBaseClient, "_request", _no_network)


def signed_headers(body: str, *, secret: str = SIGNING_SECRET, timestamp: int | None = None,
                   content_type: str = "application/x-www-form-urlencoded") -> dict[str, str]:
    ts = str(int(time.time()) if timestamp is None else timestamp)
    sig = hmac.new(secret.encode(), f"v0:{ts}:{body}".encode(), hashlib.sha256).hexdigest()
    return {"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": f"v0={sig}", "Content-Type": content_type}
