"""Read access to zcta_markets and zcta_adjacency. Returns ZctaRecord (plain data), never ORM
rows, so services stay free of sessions."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import ZctaAdjacency, ZctaMarket
from app.schemas.market import ZctaRecord


def get_market(session: Session, zcta: str) -> ZctaRecord | None:
    row = session.get(ZctaMarket, zcta)
    return None if row is None else ZctaRecord.from_row(row)


def get_markets(session: Session, zctas: Iterable[str]) -> dict[str, ZctaRecord]:
    codes = sorted(set(zctas))
    if not codes:
        return {}
    rows = session.scalars(select(ZctaMarket).where(ZctaMarket.zcta.in_(codes)))
    return {row.zcta: ZctaRecord.from_row(row) for row in rows}


def list_markets_by_state(session: Session, state: str) -> list[ZctaRecord]:
    rows = session.scalars(
        select(ZctaMarket).where(ZctaMarket.state == state.upper()).order_by(ZctaMarket.zcta)
    )
    return [ZctaRecord.from_row(row) for row in rows]


def search_markets_by_city(
    session: Session, query: str, *, state: str | None = None, limit: int = 50
) -> list[ZctaRecord]:
    """Case-insensitive prefix match on primary_city, optionally within one state."""
    pattern = query.strip().lower() + "%"
    stmt = select(ZctaMarket).where(func.lower(ZctaMarket.primary_city).like(pattern))
    if state:
        stmt = stmt.where(ZctaMarket.state == state.upper())
    stmt = stmt.order_by(ZctaMarket.state, ZctaMarket.primary_city, ZctaMarket.zcta).limit(limit)
    return [ZctaRecord.from_row(row) for row in session.scalars(stmt)]


def neighbour_zctas(session: Session, zcta: str) -> list[str]:
    """Rook-adjacent ZCTAs (both directions of the stored ordered pair), sorted."""
    rows = session.execute(
        select(ZctaAdjacency.zcta_a, ZctaAdjacency.zcta_b).where(
            or_(ZctaAdjacency.zcta_a == zcta, ZctaAdjacency.zcta_b == zcta)
        )
    )
    return sorted(b if a == zcta else a for a, b in rows)


def count_markets(session: Session) -> int:
    return int(session.scalar(select(func.count()).select_from(ZctaMarket)) or 0)


# ---- ORM-row access for the API (serialisation needs every column) ----------------------------


def get_market_row(session: Session, zcta: str) -> ZctaMarket | None:
    return session.get(ZctaMarket, zcta)


def list_market_rows(
    session: Session,
    *,
    state: str | None = None,
    city: str | None = None,
    tier: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[ZctaMarket], int]:
    """Filtered page of ZCTA rows ordered by code, plus the total matching count."""
    conditions = []
    if state:
        conditions.append(ZctaMarket.state == state.upper())
    if city:
        conditions.append(func.lower(ZctaMarket.primary_city).like(city.strip().lower() + "%"))
    if tier:
        conditions.append(ZctaMarket.market_tier == tier.upper())
    total = session.scalar(select(func.count()).select_from(ZctaMarket).where(*conditions))
    rows = session.scalars(
        select(ZctaMarket).where(*conditions).order_by(ZctaMarket.zcta).limit(limit).offset(offset)
    ).all()
    return list(rows), int(total or 0)


def neighbour_rows(session: Session, zcta: str) -> list[tuple[ZctaMarket, float | None]]:
    """Rook-adjacent ZCTA rows with the shared boundary length, ordered by code."""
    stmt = (
        select(ZctaMarket, ZctaAdjacency.shared_boundary_length_m)
        .join(
            ZctaAdjacency,
            or_(
                (ZctaAdjacency.zcta_a == zcta) & (ZctaAdjacency.zcta_b == ZctaMarket.zcta),
                (ZctaAdjacency.zcta_b == zcta) & (ZctaAdjacency.zcta_a == ZctaMarket.zcta),
            ),
        )
        .order_by(ZctaMarket.zcta)
    )
    return [(row, length) for row, length in session.execute(stmt)]


def list_city_rows(session: Session, city: str, state: str) -> list[ZctaMarket]:
    """ZCTAs whose primary city equals ``city`` in ``state`` (case-insensitive); when there is
    no exact match, prefix matches are returned instead."""
    exact = select(ZctaMarket).where(
        func.lower(ZctaMarket.primary_city) == city.strip().lower(),
        ZctaMarket.state == state.upper(),
    )
    rows = list(session.scalars(exact.order_by(ZctaMarket.zcta)))
    if rows:
        return rows
    prefix = select(ZctaMarket).where(
        func.lower(ZctaMarket.primary_city).like(city.strip().lower() + "%"),
        ZctaMarket.state == state.upper(),
    )
    return list(session.scalars(prefix.order_by(ZctaMarket.zcta)))
