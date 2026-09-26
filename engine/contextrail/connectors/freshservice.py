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
"""

from __future__ import annotations

import re
from typing import Any, Self

import httpx

from contextrail.connectors.base import ConnectorError, TransientError, UnknownOutcome
from contextrail.connectors.ratelimit import TokenBucket

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


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


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
