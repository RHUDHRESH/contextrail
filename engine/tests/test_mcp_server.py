"""The MCP door's transport (T181): Streamable HTTP at exactly /mcp inside the engine, behind ENGINE_TOKEN."""

import pytest
from mcp_helpers import MCP_TOKEN, app_with, http, mcp_over_http, running

INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                   "clientInfo": {"name": "t", "version": "0"}}}
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


@pytest.fixture
def app_factory(migrated_db):
    """MCP lifespan tests use their own migrated database, not a local PostgreSQL service."""
    return lambda **kw: app_with(database_url=migrated_db, **kw)


async def test_an_mcp_client_connects_at_slash_mcp_with_the_engine_token(app_factory):
    app = app_factory()
    async with running(app), mcp_over_http(app) as client:
        assert client.server_capabilities.tools is not None
        await client.list_tools()   # the round trip works; the tools themselves arrive with T182-T188


@pytest.mark.parametrize("token", [None, "wrong-token", MCP_TOKEN + "x"])
async def test_missing_or_wrong_bearer_is_refused(token, app_factory):
    app = app_factory()
    async with running(app), http(app, token, **MCP_HEADERS) as c:
        r = await c.post("/mcp", json=INIT)
    assert r.status_code == 401
    assert r.headers["www-authenticate"].startswith("Bearer")


@pytest.mark.parametrize("configured", ["", "change-me"])
async def test_mcp_stays_closed_until_engine_token_is_set(configured, app_factory):
    app = app_factory(engine_token=configured)
    async with running(app), http(app, configured, **MCP_HEADERS) as c:
        r = await c.post("/mcp", json=INIT)
    assert r.status_code == 503 and "ENGINE_TOKEN" in r.json()["detail"]


async def test_a_foreign_host_header_is_refused(app_factory):
    """DNS-rebinding protection: only the PUBLIC_URL host and localhost may address /mcp."""
    app = app_factory()
    async with running(app), http(app, Host="evil.example", **MCP_HEADERS) as c:
        r = await c.post("/mcp", json=INIT)
    assert r.status_code == 421


async def test_mcp_answers_503_until_the_lifespan_has_started(app_factory):
    app = app_factory()
    async with http(app, **MCP_HEADERS) as c:
        r = await c.post("/mcp", json=INIT)
    assert r.status_code == 503


async def test_the_rest_of_the_engine_is_unaffected(app_factory):
    app = app_factory()
    async with running(app), http(app, None) as c:
        assert (await c.get("/health")).status_code == 200
        assert (await c.get("/v1")).json()["api"] == "v1"
