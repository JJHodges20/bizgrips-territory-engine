"""Sales-call market checker: JSON endpoint and the minimal internal HTML page (Milestone 7)."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.api.deps import SessionDep
from app.api.sales_page import render_sales_page
from app.config import get_business_rules
from app.config.business_rules import BusinessRules
from app.enums import TerritorySizeClass
from app.repositories.market_graph import load_market_graph, load_market_graph_for_zips
from app.repositories.markets import list_city_rows
from app.repositories.registry import load_snapshot
from app.schemas.market import ZctaRecord
from app.schemas.market_check import MarketCheck, MarketQuery
from app.services.market import MarketGraph
from app.services.market_checker import check_market, normalise_zips, resolve_city

router = APIRouter(tags=["sales"])
AS_OF = Query(None, description="registry date; defaults to today (UTC)")
_CODES = re.compile(r"\d{5}")


def run_market_check(
    session: Session, query: MarketQuery, rules: BusinessRules, as_of: date
) -> MarketCheck:
    """Load what the pure checker needs (graph, registry, city candidates) and run it."""
    radius = rules.serviceability.default_service_radius_miles
    city_start: str | None = None
    city_candidates: list[str] = []
    if query.method == "starting_zip":
        market = load_market_graph(session, query.starting_zip, radius, rules)  # type: ignore[arg-type]
    elif query.method == "requested_zips":
        codes, _bad = normalise_zips(query.requested_zips)
        market = load_market_graph_for_zips(session, codes, radius, rules)
    else:
        rows = list_city_rows(session, query.city or "", query.state or "")
        city_start, city_candidates = resolve_city([ZctaRecord.from_row(r) for r in rows], rules)
        market = load_market_graph(session, city_start, radius, rules) if city_start else None
    if market is None:
        market = MarketGraph.build([], [], rules)
    registry = load_snapshot(session, as_of)
    return check_market(
        query,
        market,
        registry,
        rules,
        as_of,
        city_start=city_start,
        city_candidates=city_candidates,
    )


def parse_free_text(q: str) -> MarketQuery | None:
    """One input box: '80123' | '80123, 80127 80128' | 'Littleton, CO'."""
    text = q.strip()
    if not text:
        return None
    codes = _CODES.findall(text)
    if codes and not re.sub(r"[\d\s,;]", "", text):
        unique = list(dict.fromkeys(codes))
        if len(unique) == 1:
            return MarketQuery(starting_zip=unique[0])
        return MarketQuery(requested_zips=unique)
    parts = [p.strip() for p in re.split(r",", text) if p.strip()]
    if len(parts) >= 2 and len(parts[-1]) == 2 and parts[-1].isalpha():
        return MarketQuery(city=", ".join(parts[:-1]), state=parts[-1].upper())
    return None


@router.post("/market/check", response_model=MarketCheck)
def market_check(session: SessionDep, body: MarketQuery, as_of: date | None = AS_OF) -> MarketCheck:
    """The sales view for one starting ZIP, a pasted ZIP list, or a city + state."""
    return run_market_check(session, body, get_business_rules(), as_of or datetime.now(UTC).date())


@router.get("/sales", response_class=HTMLResponse, include_in_schema=False)
def sales_page(
    session: SessionDep,
    q: str = Query("", max_length=2000),
    size_class: TerritorySizeClass | None = None,
    client_id: str | None = Query(None, max_length=64),
    as_of: date | None = AS_OF,
) -> HTMLResponse:
    """Minimal internal page: one input box, one submit, the full sales view."""
    check: MarketCheck | None = None
    error: str | None = None
    query = parse_free_text(q) if q else None
    if q and query is None:
        error = "Enter a 5-digit ZIP, a list of ZIPs, or 'City, ST'."
    elif query is not None:
        query = query.model_copy(update={"size_class": size_class, "client_id": client_id})
        check = run_market_check(
            session, query, get_business_rules(), as_of or datetime.now(UTC).date()
        )
    return HTMLResponse(render_sales_page(q, check, error))
