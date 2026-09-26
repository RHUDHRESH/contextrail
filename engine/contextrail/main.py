"""FastAPI entry point: `uvicorn contextrail.main:app`."""

from fastapi import FastAPI

from contextrail import __version__
from contextrail.api import router as v1_router
from contextrail.app_state import Platform, build_platform
from contextrail.errors import install_error_handlers
from contextrail.logs import configure_logging
from contextrail.policy.loader import load_rules
from contextrail.settings import Settings, get_settings


def create_app(settings: Settings | None = None, *, platform: Platform | None = None) -> FastAPI:
    """Build the API. `platform` injects a prebuilt object graph (tests); otherwise one is built from settings."""
    settings = settings or (platform.settings if platform else get_settings())
    configure_logging(settings.log_level, json=settings.log_json)
    # Fail fast: an engine with an invalid or skipped rule would change verdicts silently (T054).
    platform = platform or build_platform(settings, rules=load_rules())
    app = FastAPI(
        title="ContextRail engine",
        version=__version__,
        description="Business process automation, powered by AI: policy-governed, approval-aware, verified by read-back.",
        lifespan=platform.lifespan,
    )
    app.state.settings = settings
    app.state.platform = platform
    app.state.rules = platform.rules
    app.state.registry = platform.registry
    install_error_handlers(app)

    @app.get("/health", tags=["ops"])
    async def health() -> dict:
        return {"status": "ok", "version": __version__}

    app.include_router(v1_router)
    return app


app = create_app()
