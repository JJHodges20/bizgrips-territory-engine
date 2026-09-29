"""Environment settings from .env or environment variables. Business rules live in YAML."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

CONFIG_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CONFIG_DIR.parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "BizGrips Territory Engine"
    environment: str = "development"
    log_level: str = "INFO"

    # Relative SQLite paths are resolved against the project root by app.db.resolve_database_url.
    database_url: str = "sqlite:///data/processed/territory.db"

    census_api_key: str | None = None

    business_rules_path: Path = CONFIG_DIR / "business_rules.yaml"
    census_variables_path: Path = CONFIG_DIR / "census_variables.yaml"
    fixtures_dir: Path = PROJECT_ROOT / "data" / "fixtures"
    raw_data_dir: Path = PROJECT_ROOT / "data" / "raw"
    processed_data_dir: Path = PROJECT_ROOT / "data" / "processed"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
