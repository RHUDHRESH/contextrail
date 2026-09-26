"""Test helpers for the MCP door: an engine app with /mcp served on the test's own event loop.

httpx2 is the HTTP client the `mcp` SDK uses. Its ASGI transport runs the app in-process, so the MCP session
manager, the rail's database pool and the test all share one loop. The app's lifespan is entered explicitly,
because an ASGI transport does not run it (the session manager lives in that lifespan).
"""

from __future__ import annotations

import contextlib

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from contextrail.main import create_app
from contextrail.settings import Settings

MCP_TOKEN = "test-mcp-token"  # a test value, not a credential
BASE = "http://testserver"


def settings(**kw) -> Settings:
    return Settings(_env_file=None, **{"engine_token": MCP_TOKEN, "public_url": BASE, **kw})


def http(app, token: str | None = MCP_TOKEN, **headers) -> httpx2.AsyncClient:
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE, headers=headers)


@contextlib.asynccontextmanager
async def running(app):
    """Run the app's lifespan (which starts the MCP session manager) around the test body."""
    async with app.router.lifespan_context(app):
        yield app


@contextlib.asynccontextmanager
async def mcp_over_http(app, token: str = MCP_TOKEN):
    """An MCP client talking Streamable HTTP to /mcp, exactly as Claude Code would."""
    async with Client(streamable_http_client(f"{BASE}/mcp", http_client=http(app, token))) as client:
        yield client


def app_with(**kw):
    return create_app(settings(**kw))
