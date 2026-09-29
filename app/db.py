"""Engine and session helpers. SQLite by default; PostgreSQL via DATABASE_URL."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import URL, Engine, create_engine, event, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import PROJECT_ROOT, get_settings
from app.models import Base


def resolve_database_url(url: str | URL) -> URL:
    """Parse a database URL. Relative SQLite file paths become absolute under the project root,
    and the containing folder is created so a first run needs no manual setup."""
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite" and parsed.database and parsed.database != ":memory:":
        db_path = Path(parsed.database)
        if not db_path.is_absolute():
            db_path = PROJECT_ROOT / db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        parsed = parsed.set(database=db_path.as_posix())
    return parsed


def create_db_engine(url: str | URL | None = None, **engine_kwargs: Any) -> Engine:
    resolved = resolve_database_url(url or get_settings().database_url)
    engine = create_engine(resolved, **engine_kwargs)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    """Create all tables directly. Development/test convenience; deployments use Alembic."""
    Base.metadata.create_all(engine)
