"""FastAPI entry point: `uvicorn contextrail.main:app`."""

from fastapi import FastAPI

from contextrail import __version__
from contextrail.api import router as v1_router
from contextrail.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="ContextRail engine",
        version=__version__,
        description="Business process automation, powered by AI: policy-governed, approval-aware, verified by read-back.",
    )
    app.state.settings = settings

    @app.get("/health", tags=["ops"])
    async def health() -> dict:
        return {"status": "ok", "version": __version__}

    app.include_router(v1_router)
    return app


app = create_app()
