"""The Freshservice REST v2 client (T122): auth, base URL, and how HTTP outcomes map to connector errors.

The mapping matters to the rail: TransientError may be retried with backoff, UnknownOutcome must be reconciled
before any retry (CLAUDE.md §8 Execute), and any other ConnectorError is permanent.
"""

import base64

import httpx
import pytest
from _fs_mock import API_KEY, BASE, DOMAIN, FakeTenant, ok

from contextrail.connectors.base import ConnectorError, TransientError, UnknownOutcome
from contextrail.connectors.freshservice import FreshserviceClient, RateLimited, base_url


def client(tenant: FakeTenant) -> FreshserviceClient:
    return FreshserviceClient(DOMAIN, API_KEY, transport=tenant.transport)


async def test_requests_use_basic_auth_with_the_api_key_and_X_against_api_v2():
    tenant = FakeTenant({("GET", "/api/v2/tickets/20"): ok({"ticket": {"id": 20}})})
    async with client(tenant) as fs:
        assert await fs.get("tickets/20") == {"ticket": {"id": 20}}
    req = tenant.requests[0]
    assert str(req.url) == f"{BASE}/tickets/20"
    assert req.headers["authorization"] == "Basic " + base64.b64encode(f"{API_KEY}:X".encode()).decode()
    assert req.headers["accept"] == "application/json"


def test_base_url_is_normalised_and_only_a_freshservice_domain_gets_the_key():
    assert base_url("https://Northbeam.freshservice.com/") == BASE
    assert base_url(DOMAIN) == BASE
    for bad in ("", "northbeam", "evil.example.com", "northbeam.freshservice.com.evil.example", "a/b.freshservice.com"):
        with pytest.raises(ValueError):
            base_url(bad)


async def test_json_bodies_are_sent_as_json_and_2xx_bodies_come_back_parsed():
    tenant = FakeTenant({("POST", "/api/v2/tickets/20/notes"): ok({"conversation": {"id": 9}}, status=201),
                         ("PUT", "/api/v2/tickets/20/approvals/7/remind"): httpx.Response(204)})
    async with client(tenant) as fs:
        assert await fs.post("tickets/20/notes", {"body": "hi", "private": True}) == {"conversation": {"id": 9}}
        assert await fs.put("tickets/20/approvals/7/remind", None) is None
    assert tenant.requests[0].headers["content-type"] == "application/json"
    assert tenant.body(0) == {"body": "hi", "private": True}


async def test_429_is_transient_and_carries_retry_after():
    tenant = FakeTenant({("GET", "/api/v2/tickets/1"): httpx.Response(429, headers={"Retry-After": "12"})})
    async with client(tenant) as fs:
        with pytest.raises(RateLimited) as e:
            await fs.get("tickets/1")
    assert isinstance(e.value, TransientError) and e.value.retry_after == 12.0


@pytest.mark.parametrize("status", [500, 502, 503, 504])
async def test_5xx_is_transient(status):
    tenant = FakeTenant({("POST", "/api/v2/tickets/1/notes"): httpx.Response(status)})
    async with client(tenant) as fs:
        with pytest.raises(TransientError):
            await fs.post("tickets/1/notes", {"body": "x"})


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409])
async def test_other_4xx_is_permanent_and_quotes_freshservice(status):
    payload = {"description": "Validation failed", "errors": [{"field": "approver_id", "message": "Invalid"}]}
    tenant = FakeTenant({("POST", "/api/v2/tickets/1/approvals"): ok(payload, status=status)})
    async with client(tenant) as fs:
        with pytest.raises(ConnectorError) as e:
            await fs.post("tickets/1/approvals", {"approver_id": 1})
    assert not isinstance(e.value, TransientError | UnknownOutcome)
    assert e.value.status == status and "Validation failed" in str(e.value) and "approver_id" in str(e.value)


async def test_a_read_that_times_out_is_transient():
    tenant = FakeTenant({("GET", "/api/v2/tickets/1"): httpx.ReadTimeout("slow")})
    async with client(tenant) as fs:
        with pytest.raises(TransientError):
            await fs.get("tickets/1")


@pytest.mark.parametrize("exc", [httpx.ReadTimeout("slow"), httpx.WriteTimeout("slow"),
                                 httpx.RemoteProtocolError("dropped"), httpx.ReadError("reset")])
async def test_a_write_that_may_have_been_sent_is_an_unknown_outcome(exc):
    tenant = FakeTenant({("POST", "/api/v2/tickets/1/notes"): exc})
    async with client(tenant) as fs:
        with pytest.raises(UnknownOutcome):
            await fs.post("tickets/1/notes", {"body": "x"})


@pytest.mark.parametrize("exc", [httpx.ConnectTimeout("no route"), httpx.ConnectError("refused"),
                                 httpx.PoolTimeout("busy")])
async def test_a_write_that_never_left_is_transient_not_unknown(exc):
    tenant = FakeTenant({("POST", "/api/v2/tickets/1/notes"): exc})
    async with client(tenant) as fs:
        with pytest.raises(TransientError) as e:
            await fs.post("tickets/1/notes", {"body": "x"})
    assert not isinstance(e.value, UnknownOutcome)


async def test_redirects_are_not_followed():
    tenant = FakeTenant({("GET", "/api/v2/tickets/1"): httpx.Response(302, headers={"location": "https://x.example/"})})
    async with client(tenant) as fs:
        with pytest.raises(ConnectorError):
            await fs.get("tickets/1")
    assert len(tenant.requests) == 1


async def test_the_api_key_never_appears_in_errors_or_repr():
    tenant = FakeTenant({("GET", "/api/v2/tickets/1"): ok({"description": "nope"}, status=403)})
    fs = client(tenant)
    with pytest.raises(ConnectorError) as e:
        await fs.get("tickets/1")
    await fs.aclose()
    assert API_KEY not in str(e.value) and API_KEY not in repr(fs)


async def test_one_pooled_http_client_serves_every_call():
    tenant = FakeTenant({("GET", "/api/v2/tickets/1"): ok({"ticket": {"id": 1}})})
    async with client(tenant) as fs:
        first = fs.http
        await fs.get("tickets/1")
        await fs.get("tickets/1")
        assert fs.http is first and not first.is_closed
    assert first.is_closed
