"""Score cache and scoring-config snapshots (DATA_DICTIONARY sections 1 and 5)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config.business_rules import BusinessRules
from app.models import ScoringConfig, ZctaMarket
from app.schemas.market import ZctaRecord
from app.schemas.scoring import ZctaScore


def all_market_records(session: Session) -> list[ZctaRecord]:
    """Every ZCTA as plain data, ordered by code (scoring never touches ORM rows)."""
    rows = session.scalars(select(ZctaMarket).order_by(ZctaMarket.zcta))
    return [ZctaRecord.from_row(row) for row in rows]


def record_scoring_config(session: Session, rules: BusinessRules) -> ScoringConfig:
    """Snapshot the rules version used for a scoring run (idempotent per version)."""
    existing = session.get(ScoringConfig, rules.version)
    if existing is not None:
        return existing
    snapshot = ScoringConfig.from_rules(rules)
    session.add(snapshot)
    session.flush()
    return snapshot


def write_score_cache(
    session: Session,
    scores: Iterable[ZctaScore],
    *,
    config_version: str,
    scored_at: datetime,
    chunk_size: int = 5000,
) -> int:
    """Cache score, tier and OU on zcta_markets (bulk UPDATE by primary key). Returns rows."""
    rows = [
        {
            "zcta": score.zcta,
            "opportunity_score": score.score,
            "market_tier": score.tier,
            "opportunity_units": score.opportunity_units,
            "score_config_version": config_version,
            "scored_at": scored_at,
        }
        for score in scores
    ]
    for start in range(0, len(rows), chunk_size):
        session.execute(update(ZctaMarket), rows[start : start + chunk_size])
    session.flush()
    return len(rows)


def tier_distribution(session: Session) -> dict[str, int]:
    rows = session.execute(
        select(ZctaMarket.market_tier, func.count()).group_by(ZctaMarket.market_tier)
    )
    return {(tier if tier is not None else "unscored"): int(count) for tier, count in rows}


def cached_score_summary(session: Session) -> dict[str, float | int | None]:
    total_ou = session.scalar(select(func.sum(ZctaMarket.opportunity_units)))
    scored = session.scalar(
        select(func.count())
        .select_from(ZctaMarket)
        .where(ZctaMarket.opportunity_score.is_not(None))
    )
    return {"scored_zctas": int(scored or 0), "total_opportunity_units": total_ou}
