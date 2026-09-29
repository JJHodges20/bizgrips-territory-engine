"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from app import __version__
from app.api import config as config_api
from app.api import conflicts as conflicts_api
from app.api import health as health_api
from app.api import imports as imports_api
from app.api import market as market_api
from app.api import registry as registry_api
from app.api import territories as territories_api
from app.api import zctas as zctas_api
from app.config.settings import Settings, get_settings
from app.db import create_db_engine, create_session_factory
from app.services.registry import RegistryError

DESCRIPTION = (
    "Internal BizGrips territory intelligence: public-data market scoring, contiguous territory "
    "recommendations, exclusivity registry and conflict checks. The engine recommends; humans "
    "approve. Scores are comparative indices, not performance guarantees."
)


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    """Build the app. Pass an ``engine`` to serve an existing database (tests use an in-memory
    SQLite engine); otherwise one is created from settings and disposed on shutdown."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owns_engine = engine is None
        app.state.engine = engine or create_db_engine(settings.database_url)
        app.state.session_factory = create_session_factory(app.state.engine)
        try:
            yield
        finally:
            if owns_engine:
                app.state.engine.dispose()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
    )
    app.include_router(health_api.router)
    app.include_router(config_api.router)
    app.include_router(zctas_api.router)
    app.include_router(imports_api.router)
    app.include_router(territories_api.router)
    app.include_router(registry_api.router)
    app.include_router(conflicts_api.router)
    app.include_router(market_api.router)

    @app.exception_handler(RegistryError)
    async def registry_error(_request: Request, exc: RegistryError) -> JSONResponse:
        detail: dict = {"code": exc.code, "message": exc.message}
        if exc.details is not None:
            detail["details"] = exc.details
        return JSONResponse(status_code=exc.status_code, content={"detail": detail})

    return app


app = create_app()
