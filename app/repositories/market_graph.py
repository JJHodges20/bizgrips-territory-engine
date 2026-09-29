"""Load a MarketGraph around a starting ZCTA from the database."""

from __future__ import annotations

import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.business_rules import BusinessRules
from app.models import ZctaAdjacency, ZctaMarket
from app.schemas.market import ZctaRecord
from app.services.market import MarketGraph, haversine_miles

MILES_PER_DEGREE_LAT = 69.0


def load_market_graph(
    session: Session, center: str, radius_miles: float, rules: BusinessRules
) -> MarketGraph | None:
    """ZCTAs whose centroid lies within ``radius_miles`` of the centre (plus a margin so the
    centre's neighbours beyond the radius are present and can be reported), with adjacency."""
    origin = session.get(ZctaMarket, center)
    if origin is None:
        return None
    if origin.latitude is None or origin.longitude is None:
        records = [ZctaRecord.from_row(origin)]
    else:
        reach = radius_miles * 1.5 + 5.0
        dlat = reach / MILES_PER_DEGREE_LAT
        dlon = reach / (MILES_PER_DEGREE_LAT * max(math.cos(math.radians(origin.latitude)), 0.1))
        rows = session.scalars(
            select(ZctaMarket).where(
                ZctaMarket.latitude.between(origin.latitude - dlat, origin.latitude + dlat),
                ZctaMarket.longitude.between(origin.longitude - dlon, origin.longitude + dlon),
            )
        )
        records = [
            ZctaRecord.from_row(row)
            for row in rows
            if haversine_miles(origin.latitude, origin.longitude, row.latitude, row.longitude)
            <= reach
        ]
    codes = {r.zcta for r in records}
    pairs = session.execute(
        select(ZctaAdjacency.zcta_a, ZctaAdjacency.zcta_b).where(
            ZctaAdjacency.zcta_a.in_(codes), ZctaAdjacency.zcta_b.in_(codes)
        )
    ).all()
    return MarketGraph.build(records, [(a, b) for a, b in pairs], rules)


def load_market_graph_for_zips(
    session: Session, zips: list[str], radius_miles: float, rules: BusinessRules
) -> MarketGraph:
    """ZCTAs around every known ZIP in ``zips`` (bounding box of their centroids expanded by
    the radius) with adjacency; an empty graph when none of the ZIPs has a record."""
    codes = sorted({z for z in zips})
    anchors = list(
        session.scalars(
            select(ZctaMarket).where(
                ZctaMarket.zcta.in_(codes),
                ZctaMarket.latitude.is_not(None),
                ZctaMarket.longitude.is_not(None),
            )
        )
    )
    if not anchors:
        known = session.scalars(select(ZctaMarket).where(ZctaMarket.zcta.in_(codes)))
        return MarketGraph.build([ZctaRecord.from_row(r) for r in known], [], rules)
    reach = radius_miles * 1.5 + 5.0
    lats = [row.latitude for row in anchors]
    lons = [row.longitude for row in anchors]
    dlat = reach / MILES_PER_DEGREE_LAT
    cos_lat = max(math.cos(math.radians(sum(lats) / len(lats))), 0.1)
    dlon = reach / (MILES_PER_DEGREE_LAT * cos_lat)
    rows = session.scalars(
        select(ZctaMarket).where(
            ZctaMarket.latitude.between(min(lats) - dlat, max(lats) + dlat),
            ZctaMarket.longitude.between(min(lons) - dlon, max(lons) + dlon),
        )
    )
    records = [ZctaRecord.from_row(row) for row in rows]
    present = {r.zcta for r in records}
    pairs = session.execute(
        select(ZctaAdjacency.zcta_a, ZctaAdjacency.zcta_b).where(
            ZctaAdjacency.zcta_a.in_(present), ZctaAdjacency.zcta_b.in_(present)
        )
    ).all()
    return MarketGraph.build(records, [(a, b) for a, b in pairs], rules)
