"""The MCP door (CLAUDE.md §13.4, checklist T181): ContextRail's tools for other agents, over Streamable HTTP at /mcp.

The server is the `mcp` 2.x SDK's MCPServer (FastMCP was renamed, D-008). It lives inside the engine's FastAPI app
at exactly `/mcp`, so Claude Code, Freddy or any MCP client reaches the same Door, rail and RunView as every other
door. Like every door, it decides nothing (D-005): the tools in mcp_tools.py only call the Door, the rail's sealed
capsule store and RunView.

Transport, as read from the installed SDK (mcp/server/lowlevel/server.py, streamable_http_manager.py):
- `streamable_http_app()` builds a Starlette app plus a StreamableHTTPSessionManager whose `run()` may be entered
  once per manager. A mounted app's own lifespan never runs, so the host app must run the manager. Here a router
  lifespan (merged into the app's lifespan by `include_router`) builds a fresh app and manager each time the engine
  starts, which also lets tests start the same app more than once.
- Auth is the SDK's bearer middleware with a TokenVerifier that compares ENGINE_TOKEN in constant time. An empty or
  placeholder ('change-me') token closes /mcp with 503, as the REST door does, rather than leaving it open. It is a
  static bearer, not OAuth: no authorization-server or protected-resource metadata routes are served.
- DNS-rebinding protection allows only the PUBLIC_URL host and localhost.
"""

from __future__ import annotations

import contextlib
import hmac
import json
from collections.abc import AsyncIterator
from urllib.parse import urlsplit

from fastapi import APIRouter, FastAPI
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp, Receive, Scope, Send

from contextrail import __version__
from contextrail.agentic.knowledge import KnowledgeSearch, RuleIndex
from contextrail.settings import Settings
from contextrail.surfaces.door import Door
from contextrail.surfaces.mcp_tools import ContextRailTools

MCP_PATH = "/mcp"
_PLACEHOLDER_TOKEN = "change-me"
INSTRUCTIONS = (
    "ContextRail governs enterprise requests (access, onboarding, refunds): it fetches the subject by ID, seals one "
    "case file, applies written policy (ALLOW, HOLD for a named approver, or REFUSE with the clause quoted), and "
    "executes only allowed or approved work, verified by read-back. Carry the capsule handle {run_id, digest} "
    "between tools. Report verdicts exactly as returned; never reinterpret a REFUSE. Approvals happen only in a "
    "human approver's door (Slack, Teams, email, Freshservice), never through these tools."
)


def engine_token_configured(settings: Settings) -> bool:
    token = settings.engine_token.get_secret_value()
    return bool(token) and token != _PLACEHOLDER_TOKEN


class EngineTokenVerifier:
    """The SDK's TokenVerifier protocol over ENGINE_TOKEN: one trusted bearer, compared in constant time."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def verify_token(self, token: str) -> AccessToken | None:
        if not engine_token_configured(self._settings):
            return None
        expected = self._settings.engine_token.get_secret_value()
        if not hmac.compare_digest(token.encode(), expected.encode()):
            return None
        return AccessToken(token=token, client_id="engine-token", scopes=[])


def transport_security(settings: Settings) -> TransportSecuritySettings:
    """Host/Origin allow-list: the public host (behind Caddy) and localhost for local clients."""
    public = urlsplit(settings.public_url)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[public.netloc, "127.0.0.1:*", "localhost:*", "[::1]:*"],
        allowed_origins=[f"{public.scheme}://{public.netloc}", "http://127.0.0.1:*", "http://localhost:*",
                         "http://[::1]:*"],
    )


def build_mcp_server(settings: Settings, tools: ContextRailTools | None = None) -> MCPServer:
    server = MCPServer(
        "contextrail",
        title="ContextRail",
        version=__version__,
        instructions=INSTRUCTIONS,
        token_verifier=EngineTokenVerifier(settings),
        # AuthSettings requires an issuer URL; nothing uses it here, because no OAuth routes or protected-resource
        # metadata are served (resource_server_url=None). The bearer check is EngineTokenVerifier alone.
        auth=AuthSettings(issuer_url=settings.public_url, resource_server_url=None),
    )
    if tools is not None:
        tools.register(server)
    return server


async def _problem(send: Send, status: int, title: str, detail: str) -> None:
    body = json.dumps({"type": "about:blank", "title": title, "status": status, "instance": MCP_PATH,
                       "detail": detail}).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/problem+json"),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


class McpEndpoint:
    """The ASGI app routed at /mcp. It forwards to the Streamable HTTP app built by the running lifespan.

    An ASGI object, not a function: Starlette treats a plain function endpoint as GET-only request/response."""

    def __init__(self, server: MCPServer, settings: Settings) -> None:
        self.server, self.settings = server, settings
        self._http: ASGIApp | None = None

    @contextlib.asynccontextmanager
    async def lifespan(self, _app) -> AsyncIterator[None]:
        self._http = self.server.streamable_http_app(streamable_http_path=MCP_PATH,
                                                     transport_security=transport_security(self.settings))
        try:
            async with self.server.session_manager.run():
                yield
        finally:
            self._http = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not engine_token_configured(self.settings):
            await _problem(send, 503, "Service unavailable",
                           "ENGINE_TOKEN is not configured; /mcp stays closed until it is set")
            return
        if self._http is None:
            await _problem(send, 503, "Service unavailable", "the MCP transport has not started")
            return
        await self._http(scope, receive, send)


def app_door(app: FastAPI) -> Door | None:
    """The engine's one Door: from the composition root (app.state.platform) when it exists, else app.state.door."""
    platform = getattr(app.state, "platform", None)
    return platform.door if platform is not None else getattr(app.state, "door", None)


def app_knowledge(app: FastAPI) -> KnowledgeSearch | None:
    """The wired knowledge index (app.state.knowledge), else the fallback index over the engine's loaded rules."""
    index = getattr(app.state, "knowledge", None)
    if index is None and getattr(app.state, "rules", None) is not None:
        index = app.state.knowledge = RuleIndex(app.state.rules)
    return index


def mount_mcp(app: FastAPI, settings: Settings) -> MCPServer:
    """Serve the MCP door at /mcp inside `app`. The only line main.py needs."""
    tools = ContextRailTools(door=lambda: app_door(app), knowledge=lambda: app_knowledge(app))
    server = build_mcp_server(settings, tools)
    endpoint = McpEndpoint(server, settings)
    router = APIRouter(lifespan=endpoint.lifespan)
    router.add_route(MCP_PATH, endpoint, include_in_schema=False)
    app.include_router(router)
    app.state.mcp = server
    return server
