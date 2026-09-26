"""The /v1 API router. Stage routers (runs, webhooks, connectors, approvals) are included here as they land."""

from fastapi import APIRouter

from contextrail import __version__

router = APIRouter(prefix="/v1")


@router.get("")
async def api_root() -> dict:
    return {"service": "contextrail-engine", "version": __version__, "api": "v1"}
