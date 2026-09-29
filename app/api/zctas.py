"""ZCTA market data (DATA_DICTIONARY sections 1-2). Read-only."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path, Query

from app.api.deps import SessionDep
from app.enums import MarketTier
from app.repositories.markets import get_market_row, list_market_rows, neighbour_rows
from app.schemas.api import (
    NeighborItem,
    NeighborsResponse,
    ZctaListItem,
    ZctaListResponse,
    ZctaResponse,
)

router = APIRouter(prefix="/zctas", tags=["zctas"])

ZCTA_PATH = Path(pattern=r"^\d{5}$", description="5-digit ZCTA code")


def _not_found(zcta: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "code": "NO_MARKET_DATA",
            "zcta": zcta,
            "message": (
                f"No market data for {zcta}. ZCTAs approximate postal ZIPs; PO-box and "
                "unique ZIPs have no ZCTA."
            ),
        },
    )


@router.get("", response_model=ZctaListResponse)
def list_zctas(
    session: SessionDep,
    state: str | None = Query(None, min_length=2, max_length=2, description="USPS code"),
    city: str | None = Query(None, min_length=1, max_length=120, description="city prefix"),
    tier: MarketTier | None = Query(None, description="market tier A-D, U = unscored"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> ZctaListResponse:
    """ZCTAs filtered by state, primary-city prefix and/or market tier, ordered by code."""
    rows, total = list_market_rows(
        session,
        state=state,
        city=city,
        tier=tier.value if tier else None,
        limit=limit,
        offset=offset,
    )
    return ZctaListResponse(
        items=[ZctaListItem.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
        filters={"state": state.upper() if state else None, "city": city, "tier": tier},
    )


@router.get(
    "/{zcta}", response_model=ZctaResponse, responses={404: {"description": "unknown ZCTA"}}
)
def get_zcta(
    session: SessionDep,
    zcta: str = ZCTA_PATH,
    include_geometry: bool = Query(False, description="also return the GeoJSON polygon"),
) -> ZctaResponse:
    """Every stored field for one ZCTA plus derived shares and the list of missing fields."""
    row = get_market_row(session, zcta)
    if row is None:
        raise _not_found(zcta)
    return ZctaResponse.from_row(row, include_geometry=include_geometry)


@router.get("/{zcta}/neighbors", response_model=NeighborsResponse)
def neighbors(session: SessionDep, zcta: str = ZCTA_PATH) -> NeighborsResponse:
    """Rook-adjacent ZCTAs (shared boundary length > 0), ordered by code."""
    if get_market_row(session, zcta) is None:
        raise _not_found(zcta)
    items = [
        NeighborItem.model_validate(row, from_attributes=True).model_copy(
            update={"shared_boundary_length_m": length}
        )
        for row, length in neighbour_rows(session, zcta)
    ]
    return NeighborsResponse(zcta=zcta, count=len(items), neighbors=items)
