"""Data provenance tables (DATA_DICTIONARY.md sections 6-7)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class DataSourceImport(Base):
    """One row per import run of one dataset."""

    __tablename__ = "data_source_imports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    vintage: Mapped[str] = mapped_column(String(16), nullable=False)
    release_label: Mapped[str | None] = mapped_column(String(200))
    source_url: Mapped[str | None] = mapped_column(Text)
    variables_json: Mapped[dict | None] = mapped_column(JSON)
    record_count: Mapped[int | None] = mapped_column(Integer)
    checksum: Mapped[str | None] = mapped_column(String(64))
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    notes: Mapped[str | None] = mapped_column(Text)


class DataFieldProvenance(Base):
    """Which import last wrote each demographic/geography column of zcta_markets."""

    __tablename__ = "data_field_provenance"

    field_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset: Mapped[str] = mapped_column(String(64), nullable=False)
    vintage: Mapped[str] = mapped_column(String(16), nullable=False)
    table_id: Mapped[str | None] = mapped_column(String(16))
    variables_json: Mapped[list | None] = mapped_column(JSON)
    import_id: Mapped[int | None] = mapped_column(ForeignKey("data_source_imports.id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
