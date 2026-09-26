"""The FIXTURE Freshservice tenant (checklist T138): the documented REST v2 endpoints, served in-process.

It is an httpx transport, so the FIXTURE path runs the very same FreshserviceClient code as LIVE (envelopes,
pagination, read-before-write reconciliation, error mapping); only the tenant behind it differs. State lives in
`FixtureState("freshservice")`, seeded from fixtures/freshservice.json, so approvals and notes really persist,
read back, and are undone by `python -m contextrail.reset`. Nothing here touches the network.

Served: GET tickets/{id}, requesters/{id}, agents/{id}, agents?email=, service_catalog/items,
tickets/{id}/approvals[/{id}], tickets/{id}/conversations; POST tickets/{id}/approvals, tickets/{id}/notes.
Anything else is a 404, as an unknown path would be on a tenant.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import httpx

from contextrail.connectors.state import FixtureState

FIXTURE_DOMAIN = "fixture.freshservice.com"  # never resolved: the transport below answers every request
_STATUS_NAMES = {0: "requested", 1: "approved", 2: "rejected", 3: "cancelled"}

Handler = Callable[..., Awaitable[httpx.Response]]


def _ok(payload: object, status: int = 200, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json=payload, headers=headers)


def _error(status: int, description: str, field: str | None = None) -> httpx.Response:
    errors = [{"field": field, "message": description, "code": "invalid_value"}] if field else []
    return _ok({"description": description, "errors": errors}, status=status)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _page(request: httpx.Request, items: list, key: str) -> httpx.Response:
    page = int(request.url.params.get("page", 1))
    size = int(request.url.params.get("per_page", 30))
    more = {"link": f'<https://{FIXTURE_DOMAIN}{request.url.path}?page={page + 1}>; rel="next"'} \
        if page * size < len(items) else {}
    return _ok({key: items[(page - 1) * size: page * size]}, headers=more)


class FixtureTenant:
    def __init__(self, state: FixtureState) -> None:
        self.state = state
        self._routes: list[tuple[str, re.Pattern[str], Handler]] = [
            ("GET", re.compile(r"^/api/v2/tickets/(\d+)$"), self._ticket),
            ("GET", re.compile(r"^/api/v2/requesters/(\d+)$"), self._requester),
            ("GET", re.compile(r"^/api/v2/agents/(\d+)$"), self._agent),
            ("GET", re.compile(r"^/api/v2/agents$"), self._agents),
            ("GET", re.compile(r"^/api/v2/service_catalog/items$"), self._catalog),
            ("GET", re.compile(r"^/api/v2/solutions/articles/(\d+)$"), self._article),
            ("GET", re.compile(r"^/api/v2/tickets/(\d+)/approvals$"), self._approvals),
            ("GET", re.compile(r"^/api/v2/tickets/(\d+)/approvals/(\d+)$"), self._approval),
            ("POST", re.compile(r"^/api/v2/tickets/(\d+)/approvals$"), self._create_approval),
            ("GET", re.compile(r"^/api/v2/tickets/(\d+)/conversations$"), self._conversations),
            ("POST", re.compile(r"^/api/v2/tickets/(\d+)/notes$"), self._create_note),
        ]

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    async def handle(self, request: httpx.Request) -> httpx.Response:
        for method, pattern, fn in self._routes:
            m = pattern.match(request.url.path)
            if m and request.method == method:
                return await fn(request, *m.groups())
        return _error(404, "Not found in the Freshservice fixture")

    # --- reads ---------------------------------------------------------------------------------------------

    def _record(self, collection: str, key: str) -> dict | None:
        return self.state.load()[collection].get(key)

    async def _ticket(self, request: httpx.Request, tid: str) -> httpx.Response:
        t = self._record("tickets", tid)
        return _ok({"ticket": t}) if t else _error(404, f"ticket {tid} not found")

    async def _requester(self, request: httpx.Request, rid: str) -> httpx.Response:
        r = self._record("requesters", rid)
        return _ok({"requester": r}) if r else _error(404, f"requester {rid} not found")

    async def _agent(self, request: httpx.Request, aid: str) -> httpx.Response:
        a = self._record("agents", aid)
        return _ok({"agent": a}) if a else _error(404, f"agent {aid} not found")

    async def _agents(self, request: httpx.Request) -> httpx.Response:
        agents = list(self.state.load()["agents"].values())
        email = request.url.params.get("email")
        if email is not None:
            agents = [a for a in agents if a["email"].casefold() == email.strip().casefold()]
        return _ok({"agents": agents})

    async def _catalog(self, request: httpx.Request) -> httpx.Response:
        return _page(request, self.state.load()["service_items"], "service_items")

    async def _article(self, request: httpx.Request, aid: str) -> httpx.Response:
        a = self._record("solution_articles", aid)
        return _ok({"article": a}) if a else _error(404, f"solution article {aid} not found")

    async def _approvals(self, request: httpx.Request, tid: str) -> httpx.Response:
        doc = self.state.load()
        if tid not in doc["tickets"]:
            return _error(404, f"ticket {tid} not found")
        return _ok({"approvals": doc["approvals"].get(tid, [])})

    async def _approval(self, request: httpx.Request, tid: str, aid: str) -> httpx.Response:
        for a in self.state.load()["approvals"].get(tid, []):
            if str(a["id"]) == aid:
                return _ok({"approval": a})
        return _error(404, f"approval {aid} not found on ticket {tid}")

    async def _conversations(self, request: httpx.Request, tid: str) -> httpx.Response:
        doc = self.state.load()
        if tid not in doc["tickets"]:
            return _error(404, f"ticket {tid} not found")
        return _page(request, doc["conversations"].get(tid, []), "conversations")

    # --- writes --------------------------------------------------------------------------------------------

    async def _create_approval(self, request: httpx.Request, tid: str) -> httpx.Response:
        body = json.loads(request.content or b"{}")

        def apply(doc: dict) -> httpx.Response:
            if tid not in doc["tickets"]:
                return _error(404, f"ticket {tid} not found")
            approver = doc["agents"].get(str(body.get("approver_id"))) or \
                doc["requesters"].get(str(body.get("approver_id")))
            if approver is None:
                return _error(400, "Validation failed: no such user", field="approver_id")
            approval_id, doc["next_id"] = doc["next_id"], doc["next_id"] + 1
            record = {"id": approval_id, "created_at": _now(), "updated_at": _now(),
                      "approver_id": approver["id"], "approver_name": f"{approver['first_name']} {approver['last_name']}",
                      "user_id": None, "user_name": "ContextRail", "level": 1,
                      "approval_type": int(body.get("approval_type", 1)),
                      "approval_status": {"id": 0, "name": _STATUS_NAMES[0]},
                      "email_content": body.get("email_content"), "latest_remark": ""}
            doc["approvals"].setdefault(tid, []).append(record)
            return _ok({"approval": record})

        return await self.state.mutate(apply)

    async def _create_note(self, request: httpx.Request, tid: str) -> httpx.Response:
        body = json.loads(request.content or b"{}")

        def apply(doc: dict) -> httpx.Response:
            if tid not in doc["tickets"]:
                return _error(404, f"ticket {tid} not found")
            if not body.get("body"):
                return _error(400, "Validation failed: body is required", field="body")
            note_id, doc["next_id"] = doc["next_id"], doc["next_id"] + 1
            text = " ".join(re.sub(r"<[^>]+>", " ", body["body"]).split())
            record = {"id": note_id, "body": body["body"], "body_text": text, "incoming": False,
                      "private": bool(body.get("private", True)), "user_id": None, "ticket_id": int(tid),
                      "created_at": _now(), "updated_at": _now(), "attachments": []}
            doc["conversations"].setdefault(tid, []).append(record)
            return _ok({"conversation": record}, status=201)

        return await self.state.mutate(apply)
