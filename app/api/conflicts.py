"""Conflict check endpoint (Milestone 6): a ZIP list against the registry, with replacements."""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import APIRouter, Query

from app.api.deps import SessionDep
from app.config import get_business_rules
from app.repositories.market_graph import load_market_graph_for_zips
from app.repositories.registry import load_snapshot
from app.schemas.territory import ConflictCheckRequest, ConflictCheckResponse
from app.services.conflict_checker import check_conflicts

router = APIRouter(prefix="/conflicts", tags=["registry"])


@router.post("/check", response_model=ConflictCheckResponse)
def conflict_check(
    session: SessionDep,
    body: ConflictCheckRequest,
    as_of: date | None = Query(None, description="registry date; defaults to today (UTC)"),
) -> ConflictCheckResponse:
    """Which of these ZIPs are available, reserved, protected or pending release for this
    prospect; whether the list is contiguous; nearest available replacements for conflicts."""
    rules = get_business_rules()
    effective_as_of = as_of or datetime.now(UTC).date()
    market = load_market_graph_for_zips(
        session, body.zips, rules.serviceability.default_service_radius_miles, rules
    )
    registry = load_snapshot(session, effective_as_of)
    result = check_conflicts(body.zips, market, registry, rules, client_id=body.client_id)
    return ConflictCheckResponse(
        **result.model_dump(),
        as_of=effective_as_of,
        client_id=body.client_id,
        checked=list(dict.fromkeys(body.zips)),
    )
