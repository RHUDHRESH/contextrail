"""FastAPI entry point: `uvicorn contextrail.main:app`."""

from fastapi import FastAPI

from contextrail import __version__
from contextrail.api import router as v1_router
from contextrail.connectors.registry import build_registry
from contextrail.errors import install_error_handlers
from contextrail.logs import configure_logging
from contextrail.policy.loader import load_rules
from contextrail.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    app = FastAPI(
        title="ContextRail engine",
        version=__version__,
        description="Business process automation, powered by AI: policy-governed, approval-aware, verified by read-back.",
    )
    app.state.settings = settings
    # Fail fast: an engine with an invalid or skipped rule would change verdicts silently (T054).
    app.state.rules = load_rules()
    app.state.registry = build_registry()
    install_error_handlers(app)

    @app.get("/health", tags=["ops"])
    async def health() -> dict:
        return {"status": "ok", "version": __version__}

    app.include_router(v1_router)
    return app


app = create_app()
