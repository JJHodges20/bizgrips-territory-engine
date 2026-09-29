"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import Engine

from app import __version__
from app.api import config as config_api
from app.api import health as health_api
from app.api import imports as imports_api
from app.api import zctas as zctas_api
from app.config.settings import Settings, get_settings
from app.db import create_db_engine, create_session_factory

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
    return app


app = create_app()
