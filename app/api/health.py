"""Liveness endpoint with configuration and database status."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text

from app import __version__
from app.config import get_business_rules, get_settings

router = APIRouter(tags=["system"])


class DatabaseStatus(BaseModel):
    dialect: str | None
    status: str
    detail: str | None = None


class HealthResponse(BaseModel):
    status: str
    app: str
    version: str
    environment: str
    business_rules_version: str
    database: DatabaseStatus


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    settings = get_settings()
    rules = get_business_rules()
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        db = DatabaseStatus(dialect=None, status="not_initialised")
    else:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            db = DatabaseStatus(dialect=engine.dialect.name, status="ok")
        except Exception as exc:  # pragma: no cover - depends on environment
            db = DatabaseStatus(dialect=engine.dialect.name, status="error", detail=str(exc))
    return HealthResponse(
        status="ok" if db.status in ("ok", "not_initialised") else "degraded",
        app=settings.app_name,
        version=__version__,
        environment=settings.environment,
        business_rules_version=rules.version,
        database=db,
    )
