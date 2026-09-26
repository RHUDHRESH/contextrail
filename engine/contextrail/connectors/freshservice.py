"""Freshservice REST v2 (CLAUDE.md §12): the base, and the system of record for tickets, people and approvals.

Checked against api.freshservice.com (2026-09-26) and the reference client in
refs/matthewlboyd__freshservice-mcp (src/freshservice_mcp/client.py):
- Base URL `https://{domain}.freshservice.com/api/v2`; Basic auth with the API key as username and `X` as the
  password ("If you use the API key, there is no need for a password").
- Rate limits are account-wide; a 429 carries `Retry-After` in seconds.

How outcomes map to the connector contract (connectors/base.py):
- 2xx -> parsed JSON (None for 204 / empty bodies).
- 429 -> RateLimited (a TransientError with `retry_after`); 5xx -> TransientError. Retry with backoff.
- Other 4xx and unexpected 3xx -> FreshserviceHTTPError (a permanent ConnectorError quoting Freshservice).
- Transport failures: if the request never left (connect error/timeout, pool timeout) it is a TransientError for
  every method. Once it may have been sent (read/write timeout, dropped connection), a read is a TransientError,
  but a write is an UnknownOutcome: reconcile with a read before any retry, never blind-retry (§8 Execute).

FreshserviceConnector (T138) is what the rail and the doors use. It is LIVE only when FS_DOMAIN and FS_API_KEY are
set. Every result carries the mode of the system that actually answered: FIXTURE when not configured, and FIXTURE
with a `fallback_reason` (and a warning log) when a tenant call failed. A write with an unknown outcome is raised,
never redone against the fixture, because the tenant may already hold it (D-004, CLAUDE.md §0 rule 4).
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING, Any, Literal, Self, TypeVar

import httpx
from pydantic import BaseModel, ConfigDict

from contextrail.connectors.base import ConnectorError, Mode, TransientError, UnknownOutcome, WriteResult
from contextrail.connectors.freshservice_fixture import FIXTURE_DOMAIN, FixtureTenant
from contextrail.connectors.ratelimit import TokenBucket
from contextrail.connectors.state import FixtureState
from contextrail.logs import get_logger

if TYPE_CHECKING:
    from contextrail.models import Action
    from contextrail.settings import Settings

T = TypeVar("T")

TIMEOUT = httpx.Timeout(15.0, connect=5.0)
# One pooled client per process; idle connections are kept alive between the calls of a run.
LIMITS = httpx.Limits(max_connections=10, max_keepalive_connections=5, keepalive_expiry=30.0)

_DOMAIN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.freshservice\.com$")
_NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
_READS = frozenset({"GET", "HEAD"})

# Ticket `source` values (api.freshservice.com, Tickets: "Source Type"). Accounts can add custom sources.
SOURCES = {1: "email", 2: "portal", 3: "phone", 4: "chat", 5: "feedback_widget", 10: "slack", 15: "ms_teams"}


ACCESS_REQUEST_ITEM = "Access request (ContextRail)"  # the catalog item an admin creates (T134)
CATALOG_PAGE_SIZE = 30  # View List of Service Items: "per_page ... (default: 30, max: 30)"
MAX_PAGES = 50          # a tenant that always answers rel="next" cannot keep us paging forever
CONVERSATION_PAGE_SIZE = 30  # the documented default page size for a ticket's conversations
_MARKER = re.compile(r"^[a-z0-9][a-z0-9:_-]{7,79}$")  # plain tokens survive Freshservice's HTML handling


@dataclass(frozen=True)
class NoteOutcome:
    note: dict        # the conversation record
    replayed: bool    # a note with this marker already existed; nothing was posted
    confirmed: bool   # a re-fetch of the ticket shows the note


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


class ApprovalType(IntEnum):
    """Tickets > Approvals > Approval Properties: how several approvals on one ticket combine."""

    EVERYONE = 1
    ANYONE = 2
    MAJORITY = 3
    FIRST_RESPONDER = 4


class ApprovalStatus(IntEnum):
    """Approval status values. Through the API a status can only be set to CANCELLED; approve and reject happen
    only by the approver's own action in Freshservice (Cancel an approval: "Any other status change will be done
    based on the approver's action")."""

    REQUESTED = 0
    APPROVED = 1
    REJECTED = 2
    CANCELLED = 3


def approval_status(approval: dict) -> ApprovalStatus:
    """The status of an approval record, read from `approval_status.id` (the display name may vary)."""
    return ApprovalStatus(int(approval["approval_status"]["id"]))


def source_name(ticket: dict) -> str:
    """'email' for tickets raised through the support mailbox (the email door, CLAUDE.md §13.6), and so on."""
    return SOURCES.get(ticket.get("source"), "other")


def fs_id(value: object) -> int:
    """A Freshservice id as a positive int. Anything else is refused before it can reach a URL path."""
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise TypeError(f"not a Freshservice id: {value!r}")
    text = str(value).strip()
    if not (text.isascii() and text.isdigit()) or int(text) <= 0:
        raise ValueError(f"not a Freshservice id: {value!r}")
    return int(text)


def _unwrap(body: Any, key: str, what: str) -> Any:
    if not isinstance(body, dict) or key not in body:
        raise ConnectorError(f"{what}: response has no '{key}' envelope")
    return body[key]


class FreshserviceHTTPError(ConnectorError):
    """A permanent Freshservice error (4xx other than 429). Do not retry."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class RateLimited(TransientError):
    """429 from Freshservice. `retry_after` is the server's Retry-After in seconds, when it sent one."""

    def __init__(self, message: str, retry_after: float | None) -> None:
        super().__init__(message)
        self.status = 429
        self.retry_after = retry_after


def base_url(domain: str) -> str:
    """`https://{tenant}.freshservice.com/api/v2`. Anything else is refused, so the API key never goes elsewhere."""
    host = re.sub(r"^https?://", "", (domain or "").strip()).rstrip("/").lower()
    if not _DOMAIN.match(host):
        raise ValueError(f"FS_DOMAIN must be '<tenant>.freshservice.com', got {domain!r}")
    return f"https://{host}/api/v2"


def _describe(r: httpx.Response) -> str:
    try:
        body = r.json()
    except ValueError:
        return r.text[:300]
    if not isinstance(body, dict):
        return str(body)[:300]
    parts = [str(body.get("description") or body.get("message") or "")]
    parts += [f"{e.get('field')}: {e.get('message')}" for e in body.get("errors") or [] if isinstance(e, dict)]
    return "; ".join(p for p in parts if p)[:500]


def _retry_after(r: httpx.Response) -> float | None:
    try:
        return float(r.headers["retry-after"])
    except (KeyError, ValueError):
        return None


class FreshserviceClient:
    """Async REST v2 client: auth, base URL, timeouts, keep-alive and error mapping. No retries of its own."""

    def __init__(self, domain: str, api_key: str, *, transport: httpx.AsyncBaseTransport | None = None,
                 limiter: TokenBucket | None = None) -> None:
        self.base_url = base_url(domain)
        self.limiter = limiter
        self._access_item: dict | None = None
        self.http = httpx.AsyncClient(
            base_url=self.base_url + "/",
            auth=httpx.BasicAuth(api_key, "X"),
            headers={"Accept": "application/json"},
            timeout=TIMEOUT,
            limits=LIMITS,
            transport=transport,
            follow_redirects=False,
        )

    def __repr__(self) -> str:
        return f"FreshserviceClient({self.base_url!r})"

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self.http.aclose()

    async def _send(self, method: str, path: str, *, params: dict | None = None, json: Any = None
                    ) -> tuple[httpx.Response, Any]:
        """One rate-limited call with errors mapped; returns the response (for headers) and its parsed body."""
        what = f"freshservice {method} /{path}"
        if self.limiter is not None:
            await self.limiter.acquire()
        try:
            r = await self.http.request(method, path, params=params, json=json)
        except _NOT_SENT as e:
            raise TransientError(f"{what}: {type(e).__name__}, request not sent") from e
        except httpx.TransportError as e:
            if method in _READS:
                raise TransientError(f"{what}: {type(e).__name__}") from e
            raise UnknownOutcome(f"{what}: {type(e).__name__} after sending; outcome unknown") from e
        return r, self._parse(r, what, write=method not in _READS)

    @staticmethod
    def _parse(r: httpx.Response, what: str, *, write: bool) -> Any:
        if r.status_code == 429:
            after = _retry_after(r)
            raise RateLimited(f"{what}: 429 rate limited (retry after {after}s)", after)
        if r.status_code >= 500:
            raise TransientError(f"{what}: {r.status_code} {_describe(r)}".rstrip())
        if r.status_code >= 300:
            raise FreshserviceHTTPError(r.status_code, f"{what}: {r.status_code} {_describe(r)}".rstrip())
        if r.status_code == 204 or not r.content.strip():
            return None
        try:
            return r.json()
        except ValueError as e:
            if write:
                raise UnknownOutcome(f"{what}: {r.status_code} with an unreadable body; outcome unknown") from e
            raise ConnectorError(f"{what}: {r.status_code} with an unreadable body") from e

    async def request(self, method: str, path: str, *, params: dict | None = None, json: Any = None) -> Any:
        return (await self._send(method, path, params=params, json=json))[1]

    async def get_all(self, path: str, key: str, *, page_size: int = 100, max_pages: int = MAX_PAGES,
                      params: dict | None = None) -> list[dict]:
        """Every object of a paginated list. The `link` header's rel="next" only says whether to ask for page n+1;
        its URL is never followed, so an authenticated call cannot be steered to another host."""
        out: list[dict] = []
        for page in range(1, max_pages + 1):
            r, body = await self._send("GET", path, params={**(params or {}), "page": page, "per_page": page_size})
            out.extend(_unwrap(body, key, path))
            if "next" not in r.links:
                break
        return out

    async def get(self, path: str, params: dict | None = None) -> Any:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, json: Any) -> Any:
        return await self.request("POST", path, json=json)

    async def put(self, path: str, json: Any) -> Any:
        return await self.request("PUT", path, json=json)

    # --- reads by id (T124) ------------------------------------------------------------------------------------

    async def get_ticket(self, ticket_id: object) -> dict:
        """GET /tickets/{id}. `source` tells a mailbox (email) ticket from a portal/catalog one."""
        path = f"tickets/{fs_id(ticket_id)}"
        return _unwrap(await self.get(path), "ticket", path)

    async def get_requester(self, requester_id: object) -> dict:
        path = f"requesters/{fs_id(requester_id)}"
        return _unwrap(await self.get(path), "requester", path)

    async def get_agent(self, agent_id: object) -> dict:
        path = f"agents/{fs_id(agent_id)}"
        return _unwrap(await self.get(path), "agent", path)

    async def find_agents_by_email(self, email: str) -> list[dict]:
        """GET /agents?email=... Every agent whose address is exactly `email` (case-insensitive), never a near match."""
        want = email.strip().casefold()
        agents = _unwrap(await self.get("agents", {"email": email.strip()}), "agents", "agents?email")
        return [a for a in agents if str(a.get("email", "")).casefold() == want]

    # --- service catalog (T125) --------------------------------------------------------------------------------

    async def list_catalog_items(self, *, max_pages: int = MAX_PAGES) -> list[dict]:
        """GET /service_catalog/items, every page (this endpoint allows at most 30 per page)."""
        return await self.get_all("service_catalog/items", "service_items", page_size=CATALOG_PAGE_SIZE,
                                  max_pages=max_pages)

    async def find_catalog_items(self, name: str) -> list[dict]:
        """Live (not deleted) items whose name equals `name`, ignoring case and runs of whitespace."""
        want = _norm(name)
        return [i for i in await self.list_catalog_items() if not i.get("deleted") and _norm(i.get("name", "")) == want]

    async def access_request_item(self) -> dict:
        """The 'Access request (ContextRail)' catalog item ({id, display_id, name}), looked up once and remembered.

        place_request addresses items by display_id and approvals/tickets reference the id, so both are kept.
        Zero or several matches are errors: an admin must create exactly one such item (T134); we never guess.
        """
        if self._access_item is None:
            found = await self.find_catalog_items(ACCESS_REQUEST_ITEM)
            if len(found) != 1:
                what = "no catalog item" if not found else f"{len(found)} catalog items"
                raise ConnectorError(f"{what} named {ACCESS_REQUEST_ITEM!r}; an admin must create exactly one (T134)")
            self._access_item = {k: found[0][k] for k in ("id", "display_id", "name")}
        return dict(self._access_item)

    # --- approvals on a ticket (T126) --------------------------------------------------------------------------

    async def create_approval(self, ticket_id: object, approver_id: object, *,
                              approval_type: ApprovalType = ApprovalType.EVERYONE,
                              email_content: str | None = None) -> dict:
        """POST /tickets/{id}/approvals: ask one Freshservice user to approve the ticket.

        EVERYONE by default: each held action's approver gets their own approval, and the ticket counts as
        approved in Freshservice only when all of them have approved, as in the rail.
        """
        path = f"tickets/{fs_id(ticket_id)}/approvals"
        body: dict[str, Any] = {"approver_id": fs_id(approver_id), "approval_type": int(approval_type)}
        if email_content is not None:
            body["email_content"] = email_content
        return _unwrap(await self.post(path, body), "approval", path)

    async def list_approvals(self, ticket_id: object) -> list[dict]:
        path = f"tickets/{fs_id(ticket_id)}/approvals"
        return _unwrap(await self.get(path), "approvals", path)

    async def get_approval(self, ticket_id: object, approval_id: object) -> dict:
        path = f"tickets/{fs_id(ticket_id)}/approvals/{fs_id(approval_id)}"
        return _unwrap(await self.get(path), "approval", path)

    async def request_approval(self, ticket_id: object, approver_id: object, *,
                               approval_type: ApprovalType = ApprovalType.EVERYONE,
                               email_content: str | None = None) -> tuple[dict, bool]:
        """Ask `approver_id` to approve the ticket unless a live (not cancelled) approval for them already exists.

        Returns (approval, replayed). Freshservice accepts no idempotency key, so the read comes first: a job that
        is retried after an UnknownOutcome finds what the earlier attempt created instead of asking twice.
        """
        who = fs_id(approver_id)
        for a in await self.list_approvals(ticket_id):
            if a.get("approver_id") == who and approval_status(a) is not ApprovalStatus.CANCELLED:
                return a, True
        return await self.create_approval(ticket_id, who, approval_type=approval_type,
                                          email_content=email_content), False

    # --- private notes: receipts and decision mirrors (T127) ---------------------------------------------------

    async def create_note(self, ticket_id: object, body_html: str, *, private: bool = True) -> dict:
        """POST /tickets/{id}/notes -> `conversation`. Private (agent-only) unless asked otherwise."""
        path = f"tickets/{fs_id(ticket_id)}/notes"
        return _unwrap(await self.post(path, {"body": body_html, "private": private}), "conversation", path)

    async def list_conversations(self, ticket_id: object) -> list[dict]:
        return await self.get_all(f"tickets/{fs_id(ticket_id)}/conversations", "conversations",
                                  page_size=CONVERSATION_PAGE_SIZE)

    async def find_note(self, ticket_id: object, marker: str) -> dict | None:
        for c in await self.list_conversations(ticket_id):
            if marker in (c.get("body_text") or "") or marker in (c.get("body") or ""):
                return c
        return None

    async def add_private_note(self, ticket_id: object, body_html: str, marker: str) -> NoteOutcome:
        """Post a private note carrying `marker` once, then read the ticket back to confirm the note is there.

        The marker makes the write idempotent: a note already carrying it is returned (replayed), not posted
        again. `confirmed` is True only if the re-fetch shows the note; a 201 alone is not done (P3). A timeout
        after sending raises UnknownOutcome, and the next attempt reconciles through the marker.
        """
        if not _MARKER.match(marker):
            raise ValueError(f"note marker must match {_MARKER.pattern}, got {marker!r}")
        existing = await self.find_note(ticket_id, marker)
        if existing is not None:
            return NoteOutcome(note=existing, replayed=True, confirmed=True)
        note = await self.create_note(ticket_id, f"{body_html}\n<p>ContextRail ref {marker}</p>")
        seen = await self.find_note(ticket_id, marker)
        return NoteOutcome(note=note, replayed=False, confirmed=seen is not None and seen.get("id") == note.get("id"))


# --- the connector: LIVE when configured, labelled FIXTURE otherwise or on failure (T138) ---------------------

class FsRead(BaseModel):
    """A record (or list) read from Freshservice, with the mode of the system that answered."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    data: Any
    mode: Mode
    fallback_reason: str | None = None  # set when a LIVE call failed and the fixture answered instead


class FsApproval(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ticket_id: int
    approval_id: int
    approver_id: int
    status: Literal["requested", "approved", "rejected", "cancelled"]
    replayed: bool = False  # an existing live approval for this approver was reused; nothing was created
    mode: Mode
    fallback_reason: str | None = None


class FsNote(BaseModel):
    """The receipt of a private note: where it is, whether a re-fetch showed it, and which system holds it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ticket_id: int
    note_id: int
    marker: str
    replayed: bool
    confirmed: bool
    mode: Mode
    fallback_reason: str | None = None


def _approval(ticket_id: int, a: dict, mode: Mode, why: str | None, replayed: bool = False) -> FsApproval:
    return FsApproval(ticket_id=ticket_id, approval_id=a["id"], approver_id=a["approver_id"],
                      status=approval_status(a).name.lower(), replayed=replayed, mode=mode, fallback_reason=why)


class FreshserviceConnector:
    """Freshservice for the rail and the doors. Reads and ticket writes only: it is not an action target."""

    name = "freshservice"

    def __init__(self, settings: Settings | None = None, *, state: FixtureState | None = None,
                 transport: httpx.AsyncBaseTransport | None = None, limiter: TokenBucket | None = None) -> None:
        self.fixture_state = state or FixtureState("freshservice")
        self.fixture = FreshserviceClient(FIXTURE_DOMAIN, "fixture", transport=FixtureTenant(self.fixture_state).transport)
        self.live: FreshserviceClient | None = None
        if settings is not None and settings.freshservice_configured:
            self.live = FreshserviceClient(settings.fs_domain, settings.fs_api_key.get_secret_value(),
                                           transport=transport,
                                           limiter=limiter or TokenBucket(settings.fs_rate_limit_per_min))
        self.mode: Mode = "LIVE" if self.live is not None else "FIXTURE"

    async def aclose(self) -> None:
        await self.fixture.aclose()
        if self.live is not None:
            await self.live.aclose()

    async def _call(self, op: str, fn: Callable[[FreshserviceClient], Awaitable[T]]) -> tuple[T, Mode, str | None]:
        if self.live is None:
            return await fn(self.fixture), "FIXTURE", None
        try:
            return await fn(self.live), "LIVE", None
        except UnknownOutcome:
            raise  # the tenant may hold the write already: reconcile, do not write it somewhere else
        except ConnectorError as e:
            failure = e
        reason = f"tenant call failed: {failure}"
        get_logger("contextrail.freshservice").warning("freshservice.fixture_fallback", op=op, reason=reason)
        try:
            return await fn(self.fixture), "FIXTURE", reason
        except ConnectorError as e:
            kind = TransientError if isinstance(failure, TransientError) else ConnectorError
            raise kind(f"{reason}; the fixture fallback failed too: {e}") from e

    # --- reads -------------------------------------------------------------------------------------------------

    async def _read(self, op: str, fn: Callable[[FreshserviceClient], Awaitable[Any]]) -> FsRead:
        data, mode, why = await self._call(op, fn)
        return FsRead(data=data, mode=mode, fallback_reason=why)

    async def get_ticket(self, ticket_id: object) -> FsRead:
        tid = fs_id(ticket_id)
        return await self._read("get_ticket", lambda c: c.get_ticket(tid))

    async def get_requester(self, requester_id: object) -> FsRead:
        rid = fs_id(requester_id)
        return await self._read("get_requester", lambda c: c.get_requester(rid))

    async def get_agent(self, agent_id: object) -> FsRead:
        aid = fs_id(agent_id)
        return await self._read("get_agent", lambda c: c.get_agent(aid))

    async def find_agents_by_email(self, email: str) -> FsRead:
        return await self._read("find_agents_by_email", lambda c: c.find_agents_by_email(email))

    async def access_request_item(self) -> FsRead:
        return await self._read("access_request_item", lambda c: c.access_request_item())

    async def list_approvals(self, ticket_id: object) -> FsRead:
        tid = fs_id(ticket_id)
        return await self._read("list_approvals", lambda c: c.list_approvals(tid))

    async def get_approval(self, ticket_id: object, approval_id: object) -> FsApproval:
        tid, aid = fs_id(ticket_id), fs_id(approval_id)
        a, mode, why = await self._call("get_approval", lambda c: c.get_approval(tid, aid))
        return _approval(tid, a, mode, why)

    # --- ticket writes -----------------------------------------------------------------------------------------

    async def request_approval(self, ticket_id: object, approver_id: object, *, email_content: str | None = None,
                               approval_type: ApprovalType = ApprovalType.EVERYONE) -> FsApproval:
        tid, who = fs_id(ticket_id), fs_id(approver_id)
        (a, replayed), mode, why = await self._call("request_approval", lambda c: c.request_approval(
            tid, who, approval_type=approval_type, email_content=email_content))
        return _approval(tid, a, mode, why, replayed)

    async def add_private_note(self, ticket_id: object, body_html: str, marker: str) -> FsNote:
        tid = fs_id(ticket_id)
        out, mode, why = await self._call("add_private_note", lambda c: c.add_private_note(tid, body_html, marker))
        return FsNote(ticket_id=tid, note_id=out.note["id"], marker=marker, replayed=out.replayed,
                      confirmed=out.confirmed, mode=mode, fallback_reason=why)

    # --- the Connector protocol --------------------------------------------------------------------------------

    async def read(self, ref: dict) -> dict:
        if "ticket_id" in ref:
            return (await self.get_ticket(ref["ticket_id"])).model_dump()
        if "requester_id" in ref:
            return (await self.get_requester(ref["requester_id"])).model_dump()
        if "agent_id" in ref:
            return (await self.get_agent(ref["agent_id"])).model_dump()
        if "agent_email" in ref:
            return (await self.find_agents_by_email(ref["agent_email"])).model_dump()
        raise ConnectorError(f"freshservice: cannot read {sorted(ref)}")

    async def write(self, action: Action, idem_key: str) -> WriteResult:
        raise ConnectorError("Freshservice holds tickets, people and approvals here; it is not an action target")

    async def verify(self, action: Action) -> tuple[bool, dict]:
        raise ConnectorError("Freshservice holds tickets, people and approvals here; it is not an action target")
