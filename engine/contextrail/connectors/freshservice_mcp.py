"""Freshservice MCP, read-only (checklist T137, CLAUDE.md §12): exploration through the tenant's hosted server.

Checked 2026-09-26 against support.freshservice.com, "Model Context Protocol (MCP) integration in Freshservice"
(generally available since 2026-09-10) and "Freshworks MCP security":
- Endpoint `https://<subdomain>.freshservice.com/mcp` over Streamable HTTP. Custom domains are not supported.
- API-key auth sends the header `Authorization: <api-key>`: the raw key, as in the article's Claude Code, Cursor
  and VS Code configurations. That is not REST's Basic scheme. OAuth 2.0 is the recommended alternative.
- 20 tools: 12 read (fetch*, below) and 8 write (createTicket, updateTicket, createTicketNote, createAsset,
  updateAsset, createOnboardingRequest, createOffboardingRequest, createSolutionArticle).
- "The MCP server does not implement its own authorization layer": a call can do whatever the key's user can.
- Plans cap MCP actions (25/50/100 per minute, and per year).

This client is the read-only tool. Only the 12 documented read tools can be called. Anything else is refused
before a request is sent, as is a listed tool the server itself annotates as not read-only. Writes stay on REST
(§12). Output is exploration material and is returned as untrusted text (P6); the rail never decides from it.
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from typing import Any, Literal, Self

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from pydantic import BaseModel, ConfigDict

from contextrail.connectors.base import ConnectorError, Mode
from contextrail.connectors.freshservice import base_url
from contextrail.settings import Settings

READ_ONLY_TOOLS = frozenset({
    "fetchTickets", "fetchTicket", "fetchAssets", "fetchAsset", "fetchAgents", "fetchAgent", "fetchRequesters",
    "fetchRequester", "fetchServiceCatalogItems", "fetchSolutionArticles", "fetchWorkspaces", "fetchLocations",
})
TIMEOUT = httpx2.Timeout(30.0, read=60.0)


class ReadOnlyViolation(ConnectorError):
    """A tool that is not a documented read tool, or that the server marks as not read-only."""


class McpToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool: str
    text: str
    structured: Any = None
    is_error: bool
    mode: Mode
    trust: Literal["untrusted"] = "untrusted"  # exploration output: data, never instructions or decisions


def mcp_url(domain: str) -> str:
    """https://<tenant>.freshservice.com/mcp, with the same domain guard as the REST client."""
    return base_url(domain).removesuffix("/api/v2") + "/mcp"


class FreshserviceMCP:
    """`async with FreshserviceMCP(...) as mcp:` keeps one MCP session for a burst of exploratory reads.

    `server` is the endpoint URL (LIVE), or an in-process MCPServer / Transport (tests and demos, labelled by
    `mode`).
    """

    name = "freshservice_mcp"

    def __init__(self, server: Any, *, mode: Mode, http: httpx2.AsyncClient | None = None) -> None:
        self.server, self.mode, self.http = server, mode, http
        self.url = server if isinstance(server, str) else None
        self._stack: AsyncExitStack | None = None
        self._client: Client | None = None
        self._tools: dict[str, Any] | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> FreshserviceMCP | None:
        """LIVE when Freshservice is configured; None otherwise (there is no MCP to explore without a tenant)."""
        if not settings.freshservice_configured:
            return None
        http = httpx2.AsyncClient(headers={"Authorization": settings.fs_api_key.get_secret_value()}, timeout=TIMEOUT)
        return cls(mcp_url(settings.fs_domain), mode="LIVE", http=http)

    def __repr__(self) -> str:
        return f"FreshserviceMCP({self.url or type(self.server).__name__!r}, mode={self.mode!r})"

    async def __aenter__(self) -> Self:
        self._stack = AsyncExitStack()
        target = streamable_http_client(self.url, http_client=self.http) if self.url else self.server
        self._client = await self._stack.enter_async_context(Client(target))
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = self._client = self._tools = None

    async def aclose(self) -> None:
        await self.__aexit__()
        if self.http is not None:
            await self.http.aclose()

    def _session(self) -> Client:
        if self._client is None:
            raise RuntimeError("open the MCP session first: async with FreshserviceMCP(...) as mcp")
        return self._client

    async def _offered(self) -> dict[str, Any]:
        if self._tools is None:
            self._tools = {t.name: t for t in (await self._session().list_tools()).tools}
        return self._tools

    async def list_read_tools(self) -> list[str]:
        """The documented read tools this server actually offers (write tools are never shown)."""
        return sorted(name for name, tool in (await self._offered()).items() if _readable(name, tool))

    async def call(self, tool: str, arguments: dict | None = None) -> McpToolResult:
        """Call one read tool. Anything else is refused here, before the server sees it."""
        if tool not in READ_ONLY_TOOLS:
            raise ReadOnlyViolation(f"{tool!r} is not one of Freshservice MCP's documented read tools")
        offered = (await self._offered()).get(tool)
        if offered is None:
            raise ConnectorError(f"the Freshservice MCP server does not offer {tool!r}")
        if not _readable(tool, offered):
            raise ReadOnlyViolation(f"the server marks {tool!r} as not read-only; refused")
        result = await self._session().call_tool(tool, arguments or {})
        text = "\n".join(c.text for c in result.content if getattr(c, "type", None) == "text")
        return McpToolResult(tool=tool, text=text, structured=result.structured_content,
                             is_error=bool(result.is_error), mode=self.mode)


def _readable(name: str, tool: Any) -> bool:
    hints = getattr(tool, "annotations", None)
    return name in READ_ONLY_TOOLS and not (hints is not None and hints.read_only_hint is False)
