"""Shared pytest fixtures. Tests never touch a real database file: SQLite in memory only."""

from __future__ import annotations

import os

# Must run before anything imports app.config.settings (which caches Settings).
os.environ["DATABASE_URL"] = "sqlite://"

import pytest  # noqa: E402
from sqlalchemy import Engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.config import BusinessRules, load_business_rules  # noqa: E402
from app.db import create_db_engine, create_session_factory, init_db  # noqa: E402


@pytest.fixture
def engine() -> Engine:
    engine = create_db_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Session:
    factory = create_session_factory(engine)
    with factory() as session:
        yield session


@pytest.fixture(scope="session")
def rules() -> BusinessRules:
    return load_business_rules()
