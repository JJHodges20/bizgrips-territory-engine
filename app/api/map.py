"""Map data for the territory workspace (Milestone 8): viewport GeoJSON, shapes, locate."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Path, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import SessionDep
from app.api.territories import make_service
from app.models import ZctaMarket
from app.repositories.markets import list_city_rows
from app.repositories.registry import load_snapshot
from app.schemas.registry import RegistrySnapshot
from app.services.registry import availability_for, territory_flags

router = APIRouter(prefix="/map", tags=["map"])
AS_OF = Query(None, description="registry date; defaults to today (UTC)")
MAX_BBOX_DEGREES = 4.0
MAX_FEATURES = 3000
_CODE = re.compile(r"^\d{5}$")


def _bad(code: str, message: str, status: int = 400) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def parse_bbox(bbox: str) -> tuple[float, float, float, float]:
    try:
        parts = [float(p) for p in bbox.split(",")]
    except ValueError as exc:
        raise _bad("BAD_BBOX", "bbox must be minLon,minLat,maxLon,maxLat") from exc
    if len(parts) != 4:
        raise _bad("BAD_BBOX", "bbox must be minLon,minLat,maxLon,maxLat")
    min_lon, min_lat, max_lon, max_lat = parts
    if not (-180 <= min_lon < max_lon <= 180 and -90 <= min_lat < max_lat <= 90):
        raise _bad("BAD_BBOX", "bbox out of range or inverted")
    if max_lon - min_lon > MAX_BBOX_DEGREES or max_lat - min_lat > MAX_BBOX_DEGREES:
        raise _bad("BBOX_TOO_LARGE", "Zoom in: the viewport spans more than 4 degrees.")
    return min_lon, min_lat, max_lon, max_lat


def feature_for(
    row: ZctaMarket, snapshot: RegistrySnapshot, client_id: str | None
) -> dict[str, Any] | None:
    if not row.geometry_geojson:
        return None
    state = availability_for(row.zcta, snapshot, client_id=client_id)
    info = state.blocking
    return {
        "type": "Feature",
        "id": row.zcta,
        "geometry": json.loads(row.geometry_geojson),
        "properties": {
            "zcta": row.zcta,
            "primary_city": row.primary_city,
            "state": row.state,
            "market_tier": row.market_tier,
            "opportunity_score": row.opportunity_score,
            "opportunity_units": row.opportunity_units,
            "total_households": row.total_households,
            "owner_occupied_households": row.owner_occupied_households,
            "owner_households_age_45_plus": row.owner_households_age_45_plus,
            "median_household_income": row.median_household_income,
            "unserviceable_land_area": bool(row.unserviceable_land_area),
            "availability": state.availability.value,
            "own": state.own,
            "territory_id": info.territory_id if info else None,
            "client_business_name": info.client_business_name if info else None,
            "blocking_status": info.status.value if info else None,
            "flags": state.flags,
        },
    }


def rows_in_bbox(session: Session, box: tuple[float, float, float, float]) -> list[ZctaMarket]:
    min_lon, min_lat, max_lon, max_lat = box
    stmt = (
        select(ZctaMarket)
        .where(
            ZctaMarket.bbox_min_lon <= max_lon,
            ZctaMarket.bbox_max_lon >= min_lon,
            ZctaMarket.bbox_min_lat <= max_lat,
            ZctaMarket.bbox_max_lat >= min_lat,
        )
        .order_by(ZctaMarket.zcta)
        .limit(MAX_FEATURES + 1)
    )
    return list(session.scalars(stmt))


@router.get("/zctas")
def zctas_in_view(
    session: SessionDep,
    bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat"),
    client_id: str | None = Query(None, max_length=64),
    as_of: date | None = AS_OF,
) -> JSONResponse:
    """ZCTAs intersecting the viewport as GeoJSON with score, tier, OU and availability."""
    box = parse_bbox(bbox)
    effective = as_of or datetime.now(UTC).date()
    rows = rows_in_bbox(session, box)
    if len(rows) > MAX_FEATURES:
        raise _bad("TOO_MANY_FEATURES", f"Zoom in: more than {MAX_FEATURES:,} ZCTAs in view.")
    snapshot = load_snapshot(session, effective, [r.zcta for r in rows])
    features = []
    without_geometry = 0
    for row in rows:
        feature = feature_for(row, snapshot, client_id)
        if feature is None:
            without_geometry += 1
        else:
            features.append(feature)
    meta = {
        "count": len(features),
        "without_geometry": without_geometry,
        "as_of": effective.isoformat(),
        "bbox": list(box),
    }
    return JSONResponse({"type": "FeatureCollection", "features": features, "meta": meta})


def bounds_of(rows: list[ZctaMarket]) -> list[list[float]] | None:
    """[[min_lat, min_lon], [max_lat, max_lon]] from stored boxes, else from centroids."""
    boxed = [r for r in rows if r.bbox_min_lat is not None]
    if boxed:
        return [
            [min(r.bbox_min_lat for r in boxed), min(r.bbox_min_lon for r in boxed)],
            [max(r.bbox_max_lat for r in boxed), max(r.bbox_max_lon for r in boxed)],
        ]
    points = [r for r in rows if r.latitude is not None and r.longitude is not None]
    if not points:
        return None
    return [
        [min(r.latitude for r in points), min(r.longitude for r in points)],
        [max(r.latitude for r in points), max(r.longitude for r in points)],
    ]


@router.get("/territories/{territory_id}")
def territory_shape(
    session: SessionDep,
    territory_id: str = Path(pattern=r"^T-\d{6}$"),
    as_of: date | None = AS_OF,
) -> JSONResponse:
    """A territory's ZCTAs as GeoJSON plus its bounds and summary, for highlighting."""
    effective = as_of or datetime.now(UTC).date()
    record = make_service(session, effective).get(territory_id)
    rows = list(session.scalars(select(ZctaMarket).where(ZctaMarket.zcta.in_(record.zips))))
    snapshot = load_snapshot(session, effective, record.zips)
    features = [f for f in (feature_for(r, snapshot, None) for r in rows) if f is not None]
    return JSONResponse(
        {
            "type": "FeatureCollection",
            "features": features,
            "territory": {
                "territory_id": record.territory_id,
                "client_id": record.client_id,
                "client_business_name": record.client_business_name,
                "status": record.status.value,
                "zips": record.zips,
                "flags": territory_flags(record, effective),
            },
            "bounds": bounds_of(rows),
            "meta": {"count": len(features), "without_geometry": len(rows) - len(features)},
        }
    )


@router.get("/locate")
def locate(session: SessionDep, q: str = Query(..., min_length=1, max_length=200)) -> JSONResponse:
    """Resolve a ZIP or 'City, ST' to a centre and bounds for the map."""
    text = q.strip()
    if _CODE.match(text):
        row = session.get(ZctaMarket, text)
        if row is None or row.latitude is None:
            raise _bad("NO_MARKET_DATA", f"No market data for {text}.", 404)
        label = f"{text} {row.primary_city or ''}, {row.state or ''}".strip(" ,")
        return JSONResponse(
            {
                "kind": "zcta",
                "label": label,
                "zctas": [text],
                "center": [row.latitude, row.longitude],
                "bounds": bounds_of([row]),
            }
        )
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if len(parts) < 2 or len(parts[-1]) != 2:
        raise _bad("BAD_QUERY", "Enter a 5-digit ZIP or 'City, ST'.", 422)
    rows = [r for r in list_city_rows(session, ", ".join(parts[:-1]), parts[-1]) if r.latitude]
    if not rows:
        raise _bad("NO_MARKET_DATA", f"No ZCTA has primary city {text}.", 404)
    return JSONResponse(
        {
            "kind": "city",
            "label": f"{rows[0].primary_city}, {rows[0].state}",
            "zctas": [r.zcta for r in rows],
            "center": [
                sum(r.latitude for r in rows) / len(rows),
                sum(r.longitude for r in rows) / len(rows),
            ],
            "bounds": bounds_of(rows),
        }
    )
