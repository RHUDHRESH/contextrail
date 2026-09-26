"""Freshservice MCP, read-only (T137, CLAUDE.md §12: "Use it for Claude-driven exploration. Writes that must not
fail stay on REST.").

support.freshservice.com, "Model Context Protocol (MCP) integration in Freshservice" (GA 2026-09-10): endpoint
https://<subdomain>.freshservice.com/mcp over Streamable HTTP; API-key auth sends "Authorization: <api-key>";
12 read tools (fetch*) and 8 write tools (create*/update*). The server adds no authorization of its own.
Tests run against an in-process MCPServer that offers the documented tool names; no network.
"""

import httpx2
import pytest
from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations

from contextrail.connectors.base import ConnectorError
from contextrail.connectors.freshservice_mcp import (
    READ_ONLY_TOOLS,
    FreshserviceMCP,
    ReadOnlyViolation,
    mcp_url,
)
from contextrail.settings import Settings

WRITE_TOOLS = {"createTicket", "updateTicket", "createTicketNote", "createAsset", "updateAsset",
               "createOnboardingRequest", "createOffboardingRequest", "createSolutionArticle"}


def fake_tenant_server(calls: list[str], *, lying_read_tool: bool = False) -> MCPServer:
    server = MCPServer("fake-freshservice")

    @server.tool(name="fetchTicket")
    def fetch_ticket(ticket_id: int) -> dict:
        calls.append("fetchTicket")
        return {"id": ticket_id, "subject": "Access request (ContextRail)", "source": 2}

    @server.tool(name="fetchAgents", annotations=ToolAnnotations(readOnlyHint=not lying_read_tool))
    def fetch_agents() -> list:
        calls.append("fetchAgents")
        return [{"id": 7000000301, "email": "meera.iyer@northbeam.example"}]

    @server.tool(name="createTicket")
    def create_ticket(subject: str) -> dict:
        calls.append("createTicket")  # must never run through this client
        return {"id": 1}

    @server.tool(name="deleteEverything")
    def delete_everything() -> str:
        calls.append("deleteEverything")
        return "gone"

    return server


def test_the_allowlist_is_exactly_the_documented_read_tools():
    assert READ_ONLY_TOOLS == {"fetchTickets", "fetchTicket", "fetchAssets", "fetchAsset", "fetchAgents",
                               "fetchAgent", "fetchRequesters", "fetchRequester", "fetchServiceCatalogItems",
                               "fetchSolutionArticles", "fetchWorkspaces", "fetchLocations"}
    assert not READ_ONLY_TOOLS & WRITE_TOOLS


def test_the_endpoint_is_the_tenant_mcp_url():
    assert mcp_url("https://Northbeam.freshservice.com/") == "https://northbeam.freshservice.com/mcp"
    with pytest.raises(ValueError):
        mcp_url("support.northbeam.example")  # custom domains are not supported for MCP


async def test_from_settings_is_live_only_with_credentials_and_sends_the_raw_api_key():
    assert FreshserviceMCP.from_settings(Settings(_env_file=None)) is None
    s = Settings(_env_file=None, fs_domain="northbeam.freshservice.com", fs_api_key="fake-mcp-key-for-tests")
    mcp = FreshserviceMCP.from_settings(s)
    try:
        assert (mcp.mode, mcp.url) == ("LIVE", "https://northbeam.freshservice.com/mcp")
        assert mcp.http.headers["authorization"] == "fake-mcp-key-for-tests"  # as the Freshservice article shows
        assert "fake-mcp-key-for-tests" not in repr(mcp)
    finally:
        await mcp.aclose()


async def test_a_read_tool_is_called_and_its_output_is_untrusted_text():
    calls: list[str] = []
    async with FreshserviceMCP(fake_tenant_server(calls), mode="FIXTURE") as mcp:
        out = await mcp.call("fetchTicket", {"ticket_id": 4412})
    assert calls == ["fetchTicket"]
    assert (out.tool, out.mode, out.trust, out.is_error) == ("fetchTicket", "FIXTURE", "untrusted", False)
    assert '"id": 4412' in out.text


@pytest.mark.parametrize("tool", ["createTicket", "deleteEverything", "fetch_ticket", ""])
async def test_anything_not_on_the_read_list_is_refused_before_it_reaches_the_server(tool):
    calls: list[str] = []
    async with FreshserviceMCP(fake_tenant_server(calls), mode="FIXTURE") as mcp:
        with pytest.raises(ReadOnlyViolation):
            await mcp.call(tool, {"subject": "x"})
    assert calls == []


async def test_a_listed_read_tool_the_server_marks_as_not_read_only_is_refused():
    calls: list[str] = []
    async with FreshserviceMCP(fake_tenant_server(calls, lying_read_tool=True), mode="FIXTURE") as mcp:
        with pytest.raises(ReadOnlyViolation, match="read-only"):
            await mcp.call("fetchAgents", {})
    assert calls == []


async def test_a_read_tool_the_server_does_not_offer_is_an_error():
    async with FreshserviceMCP(fake_tenant_server([]), mode="FIXTURE") as mcp:
        with pytest.raises(ConnectorError, match="fetchAssets"):
            await mcp.call("fetchAssets", {})


async def test_only_offered_read_tools_are_listed():
    async with FreshserviceMCP(fake_tenant_server([]), mode="FIXTURE") as mcp:
        assert await mcp.list_read_tools() == ["fetchAgents", "fetchTicket"]


async def test_over_streamable_http_every_request_carries_the_api_key():
    """The URL path (the LIVE one) end to end, served in-process by an ASGI transport: no network."""
    calls: list[str] = []
    server = fake_tenant_server(calls)
    app, seen = server.streamable_http_app(), []

    async def spy(scope, receive, send):
        if scope["type"] == "http":
            seen.append(dict(scope["headers"]).get(b"authorization"))
        await app(scope, receive, send)

    http = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=spy), headers={"Authorization": "fake-key"})
    async with (server.session_manager.run(),
                FreshserviceMCP("http://127.0.0.1:8000/mcp", mode="LIVE", http=http) as mcp):
        out = await mcp.call("fetchTicket", {"ticket_id": 4412})
        with pytest.raises(ReadOnlyViolation):
            await mcp.call("createTicket", {"subject": "x"})
    await http.aclose()
    assert (out.mode, '"id": 4412' in out.text, calls) == ("LIVE", True, ["fetchTicket"])
    assert seen and set(seen) == {b"fake-key"}


async def test_calls_need_an_open_session():
    mcp = FreshserviceMCP(fake_tenant_server([]), mode="FIXTURE")
    with pytest.raises(RuntimeError):
        await mcp.call("fetchTicket", {"ticket_id": 1})
