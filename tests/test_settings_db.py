"""Settings defaults and database URL resolution."""

from __future__ import annotations

from app.config.settings import PROJECT_ROOT, Settings
from app.db import resolve_database_url


def test_defaults_point_at_project_files(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    settings = Settings(_env_file=None)
    assert settings.database_url == "sqlite:///data/processed/territory.db"
    assert settings.business_rules_path.exists()
    assert settings.census_variables_path.exists()
    assert settings.fixtures_dir == PROJECT_ROOT / "data" / "fixtures"
    assert settings.is_sqlite


def test_relative_sqlite_paths_resolve_under_project_root() -> None:
    resolved = resolve_database_url("sqlite:///data/processed/unit-test.db")
    assert resolved.get_backend_name() == "sqlite"
    assert resolved.database == (PROJECT_ROOT / "data" / "processed" / "unit-test.db").as_posix()
    assert (PROJECT_ROOT / "data" / "processed").is_dir()


def test_memory_and_postgres_urls_are_untouched() -> None:
    assert resolve_database_url("sqlite://").database is None
    assert resolve_database_url("sqlite:///:memory:").database == ":memory:"
    pg = "postgresql+psycopg://bizgrips:bizgrips@localhost:5432/bizgrips_territory"
    assert resolve_database_url(pg).render_as_string(hide_password=False) == pg
