"""The /v1 API router and runtime capability discovery."""

from pathlib import Path

from fastapi import APIRouter, Request

from contextrail import __version__
from contextrail.surfaces.mcp_server import engine_token_configured
from contextrail.surfaces.slack_app import EVENTS_PATH
from contextrail.surfaces.webhooks import MAX_BODY_BYTES, TOLERANCE_SECONDS
from contextrail.surfaces.webhooks import router as webhooks_router

router = APIRouter(prefix="/v1")
well_known_router = APIRouter()


@router.get("")
async def api_root() -> dict:
    return {"service": "contextrail-engine", "version": __version__, "api": "v1"}


@router.get("/connectors")
async def connectors(request: Request) -> dict:
    """Every connector and door with its honest mode: LIVE / FIXTURE / ONE-WAY, or planned (CLAUDE.md §0 rule 4)."""
    return request.app.state.registry.describe(request.app.state.settings)


async def build_capability_manifest(request: Request) -> dict:
    """Describe only capabilities present in this app instance, without publishing credentials."""
    app = request.app
    settings = app.state.settings
    token_ready = engine_token_configured(settings)
    doors = []
    if token_ready:
        doors.extend([{"name": "http", "path": "/v1/runs"}, {"name": "mcp", "path": "/mcp"}])
    if settings.slack_configured:
        doors.append({"name": "slack", "path": EVENTS_PATH})
    if settings.fs_webhook_secret.get_secret_value():
        doors.append({"name": "freshservice_webhook", "path": "/v1/webhooks/freshservice"})

    # Skill files are not copied into every engine installation. Report only those actually present.
    skills_dir = Path(__file__).resolve().parents[2] / "skills"
    skills = sorted(p.parent.name for p in skills_dir.glob("*/SKILL.md"))
    mcp = getattr(app.state, "mcp", None)
    tools = ([{"name": tool.name, "transport": "/mcp", "enabled": token_ready}
              for tool in await mcp.list_tools()] if mcp else [])
    connectors = app.state.registry.describe(settings)["connectors"]
    limits = {
        "freshservice_webhook_body_bytes": MAX_BODY_BYTES,
        "freshservice_webhook_clock_skew_seconds": TOLERANCE_SECONDS,
    }
    if any(connector["name"] == "freshservice" and connector["mode"] == "LIVE"
           for connector in connectors):
        limits["freshservice_requests_per_minute"] = settings.fs_rate_limit_per_min
    return {
        "name": "ContextRail",
        "version": __version__,
        "skills": skills,
        "tools": tools,
        "doors": doors,
        "connectors": connectors,
        "policy_rules": sorted(rule.id for rule in app.state.rules),
        "limits": limits,
    }


@router.get("/capabilities")
async def capabilities(request: Request) -> dict:
    return await build_capability_manifest(request)


@well_known_router.get("/.well-known/agent.json")
async def agent_card(request: Request) -> dict:
    """The same runtime manifest for clients that discover agents at the well-known path."""
    return await build_capability_manifest(request)


router.include_router(webhooks_router)  # /v1/webhooks/freshservice (T132)
