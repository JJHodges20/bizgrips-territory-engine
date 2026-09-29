"""Conflict checker core (TERRITORY_ALGORITHM.md section 2).

Milestone 5 ships the classification the generator needs for requested ZIPs; Milestone 6 adds
replacement suggestions and the endpoint. Pure: market graph + registry snapshot in, result out.
"""

from __future__ import annotations

from app.enums import AssignmentStatus
from app.schemas.registry import FLAG_RESERVATION_EXPIRED, RegistrySnapshot
from app.schemas.territory import ConflictEntry, ConflictResult, Suggestion
from app.services.market import MarketGraph
from app.services.registry import availability_for


def classify_zips(
    zips: list[str],
    market: MarketGraph,
    registry: RegistrySnapshot,
    *,
    client_id: str | None = None,
) -> ConflictResult:
    """Sort a ZIP list into available / reserved / protected / pending / own / unknown."""
    codes = list(dict.fromkeys(zips))  # keep order, drop repeats
    result = ConflictResult(requested_count=len(codes))
    for zcta in codes:
        if not market.has(zcta):
            result.unknown.append(zcta)
            continue
        state = availability_for(zcta, registry, client_id=client_id)
        info = state.blocking
        if state.own:
            result.own.append(zcta)
            continue
        if not state.is_conflict or info is None:
            result.available.append(zcta)
            continue
        entry = ConflictEntry(
            zcta=zcta,
            territory_id=info.territory_id,
            client_business_name=info.client_business_name,
            status=info.status,
            expires_at=info.reservation_expires_at,
            expired=info.expired,
            release_date=info.release_date,
            contract_end_date=info.contract_end_date,
        )
        if info.status == AssignmentStatus.RESERVED:
            result.reserved.append(entry)
            if info.expired:
                result.flags[zcta] = FLAG_RESERVATION_EXPIRED
        elif info.status == AssignmentStatus.ACTIVE_PROTECTED:
            result.protected.append(entry)
        else:
            result.pending_release.append(entry)
    result.conflict_count = (
        len(result.reserved) + len(result.protected) + len(result.pending_release)
    )
    known = [z for z in codes if z not in result.unknown]
    result.components = market.components(known)
    result.contiguous = len(result.components) <= 1
    return result


def nearest_available(
    for_zcta: str,
    market: MarketGraph,
    registry: RegistrySnapshot,
    *,
    client_id: str | None,
    limit: int,
    exclude: frozenset[str] = frozenset(),
    must_touch: frozenset[str] | None = None,
) -> list[Suggestion]:
    """Available, scored, serviceable ZCTAs nearest to ``for_zcta`` (distance, then score,
    then code). ``must_touch`` restricts candidates to neighbours of those ZCTAs."""
    if limit <= 0 or not market.has(for_zcta):
        return []
    candidates: list[tuple[float, float, str]] = []
    for zcta in market.records:
        if zcta == for_zcta or zcta in exclude or zcta in market.unserviceable:
            continue
        if must_touch is not None and not (market.neighbours(zcta) & must_touch):
            continue
        score = market.scores[zcta]
        if score.score is None:
            continue
        if availability_for(zcta, registry, client_id=client_id).is_conflict:
            continue
        miles = market.distance_miles(for_zcta, zcta)
        if miles is None:
            continue
        candidates.append((miles, -score.score, zcta))
    candidates.sort()
    return [
        Suggestion(
            for_zcta=for_zcta,
            zcta=zcta,
            miles=round(miles, 2),
            score=market.scores[zcta].score,
            tier=market.scores[zcta].tier,
        )
        for miles, _neg, zcta in candidates[:limit]
    ]
