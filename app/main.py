"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api import config as config_api
from app.api import health as health_api
from app.config.settings import Settings, get_settings
from app.db import create_db_engine

DESCRIPTION = (
    "Internal BizGrips territory intelligence: public-data market scoring, contiguous territory "
    "recommendations, exclusivity registry and conflict checks. The engine recommends; humans "
    "approve. Scores are comparative indices, not performance guarantees."
)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = create_db_engine(settings.database_url)
        try:
            yield
        finally:
            app.state.engine.dispose()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
    )
    app.include_router(health_api.router)
    app.include_router(config_api.router)
    return app


app = create_app()
