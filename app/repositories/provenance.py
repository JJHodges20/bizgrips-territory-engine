"""Read access to the provenance tables."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import DataFieldProvenance, DataSourceImport


def list_imports(
    session: Session, *, dataset: str | None = None, limit: int = 100, offset: int = 0
) -> tuple[list[DataSourceImport], int]:
    """Import runs newest first (by id), optionally for one dataset, plus the total count."""
    conditions = [DataSourceImport.dataset == dataset] if dataset else []
    total = session.scalar(select(func.count()).select_from(DataSourceImport).where(*conditions))
    rows = session.scalars(
        select(DataSourceImport)
        .where(*conditions)
        .order_by(DataSourceImport.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return list(rows), int(total or 0)


def list_field_provenance(session: Session) -> list[DataFieldProvenance]:
    return list(
        session.scalars(select(DataFieldProvenance).order_by(DataFieldProvenance.field_name))
    )
