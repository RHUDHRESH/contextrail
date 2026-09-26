"""The /v1 API router. Stage routers (runs, webhooks, connectors, approvals) are included here as they land."""

from fastapi import APIRouter, Request

from contextrail import __version__

router = APIRouter(prefix="/v1")


@router.get("")
async def api_root() -> dict:
    return {"service": "contextrail-engine", "version": __version__, "api": "v1"}


@router.get("/connectors")
async def connectors(request: Request) -> dict:
    """Every connector and door with its honest mode: LIVE / FIXTURE / ONE-WAY, or planned (CLAUDE.md §0 rule 4)."""
    return request.app.state.registry.describe(request.app.state.settings)
