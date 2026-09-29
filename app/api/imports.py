"""Provenance: import runs and which import last wrote each field (DATA_DICTIONARY sections 6-7)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import SessionDep
from app.repositories.provenance import list_field_provenance, list_imports
from app.schemas.api import (
    FieldProvenanceRecord,
    FieldProvenanceResponse,
    ImportRecord,
    ImportsResponse,
)

router = APIRouter(prefix="/imports", tags=["provenance"])


@router.get("", response_model=ImportsResponse)
def imports(
    session: SessionDep,
    dataset: str | None = Query(None, description="e.g. acs/acs5, cb_zcta520_500k, fixture"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> ImportsResponse:
    """Import runs, newest first."""
    rows, total = list_imports(session, dataset=dataset, limit=limit, offset=offset)
    return ImportsResponse(
        items=[ImportRecord.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/fields", response_model=FieldProvenanceResponse)
def field_provenance(session: SessionDep) -> FieldProvenanceResponse:
    """Which dataset, vintage, table and import last wrote each zcta_markets column."""
    rows = list_field_provenance(session)
    return FieldProvenanceResponse(items=[FieldProvenanceRecord.model_validate(r) for r in rows])
