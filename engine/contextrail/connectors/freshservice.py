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

TIMEOUT = httpx.Timeout(15.0, connect=5.0)
# One pooled client per process; idle connections are kept alive between the calls of a run.
LIMITS = httpx.Limits(max_connections=10, max_keepalive_connections=5, keepalive_expiry=30.0)

_DOMAIN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.freshservice\.com$")
_NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
_READS = frozenset({"GET", "HEAD"})


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

    def __init__(self, domain: str, api_key: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = base_url(domain)
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

    async def request(self, method: str, path: str, *, params: dict | None = None, json: Any = None) -> Any:
        what = f"freshservice {method} /{path}"
        try:
            r = await self.http.request(method, path, params=params, json=json)
        except _NOT_SENT as e:
            raise TransientError(f"{what}: {type(e).__name__}, request not sent") from e
        except httpx.TransportError as e:
            if method in _READS:
                raise TransientError(f"{what}: {type(e).__name__}") from e
            raise UnknownOutcome(f"{what}: {type(e).__name__} after sending; outcome unknown") from e
        return self._parse(r, what, write=method not in _READS)

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

    async def get(self, path: str, params: dict | None = None) -> Any:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, json: Any) -> Any:
        return await self.request("POST", path, json=json)

    async def put(self, path: str, json: Any) -> Any:
        return await self.request("PUT", path, json=json)
