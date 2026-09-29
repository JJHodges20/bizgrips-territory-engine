"""Sales-call market checker (TERRITORY_ALGORITHM.md section 3, Milestone 7).

One input (starting ZIP, pasted ZIP list, or city + state) becomes the full sales view: market
availability, the suggested territory, ZIP lists with the blocking clients (internal use),
replacement ZIPs, market statistics and factual talking points. Pure: the caller loads the
MarketGraph and RegistrySnapshot (and, for city queries, the candidate records).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date

from app.config.business_rules import BusinessRules
from app.schemas.market import ZctaRecord
from app.schemas.market_check import MarketCheck, MarketQuery, MarketStats, ResolvedQuery
from app.schemas.registry import RegistrySnapshot
from app.schemas.territory import ConflictEntry, Suggestion, TerritoryProposal, TerritoryRequest
from app.services.conflict_checker import check_conflicts
from app.services.conflicts import classify_zips
from app.services.market import MarketGraph
from app.services.scoring import score_territory, score_zcta
from app.services.territory_generator import generate_territory

# Words that must never appear in generated talking points (wording review).
FORBIDDEN_WORDS = (
    "lead",
    "leads",
    "cost",
    "sales",
    "guarantee",
    "guaranteed",
    "expected",
    "roi",
    "revenue",
    "conversion",
    "will generate",
)
_ZIP = re.compile(r"^\d{5}$")


def normalise_zips(values: Iterable[str]) -> tuple[list[str], list[str]]:
    """(well-formed codes in order without repeats, malformed tokens)."""
    codes: list[str] = []
    bad: list[str] = []
    for raw in values:
        token = str(raw).strip()
        if _ZIP.match(token):
            if token not in codes:
                codes.append(token)
        elif token:
            bad.append(token)
    return codes, bad


def resolve_city(
    candidates: Iterable[ZctaRecord], rules: BusinessRules
) -> tuple[str | None, list[str]]:
    """Highest-OU candidate becomes the starting ZIP (ties by code); all codes are returned."""
    ranked = sorted(
        candidates,
        key=lambda r: (-(score_zcta(r, rules).opportunity_units or 0.0), r.zcta),
    )
    codes = [r.zcta for r in ranked]
    return (codes[0] if codes else None), codes


def resolve_query(
    query: MarketQuery, market: MarketGraph, *, city_start: str | None, city_candidates: list[str]
) -> ResolvedQuery:
    if query.method == "starting_zip":
        start = query.starting_zip
        known = market.has(start)  # type: ignore[arg-type]
        return ResolvedQuery(
            method="starting_zip",
            starting_zip=start,
            unknown_zips=[] if known else [start],  # type: ignore[list-item]
            note=f"Starting ZIP {start}." if known else f"No market data for {start}.",
        )
    if query.method == "requested_zips":
        codes, bad = normalise_zips(query.requested_zips)
        known = [z for z in codes if market.has(z)]
        unknown = [z for z in codes if not market.has(z)] + bad
        start = known[0] if known else None
        note = (
            f"{len(known)} pasted ZIPs matched market data; starting from {start}."
            if start
            else "None of the pasted ZIPs has market data (PO-box and unique ZIPs have no ZCTA)."
        )
        return ResolvedQuery(
            method="requested_zips",
            starting_zip=start,
            requested_zips=known,
            unknown_zips=unknown,
            note=note,
        )
    label = f"{query.city}, {(query.state or '').upper()}"
    if city_start is None:
        return ResolvedQuery(method="city_state", note=f"No ZCTA has primary city {label}.")
    return ResolvedQuery(
        method="city_state",
        starting_zip=city_start,
        city_candidates=city_candidates,
        note=(
            f"{len(city_candidates)} ZCTAs list {label} as primary city; "
            f"{city_start} has the most Opportunity Units and is the starting ZIP."
        ),
    )


def market_stats(records: list[ZctaRecord], rules: BusinessRules) -> MarketStats:
    territory = score_territory(records, rules)

    def total(name: str) -> int:
        return int(sum(getattr(r, name) or 0 for r in records))

    def share(numerator: str, denominator: str) -> float | None:
        num = den = 0.0
        for r in records:
            n, d = getattr(r, numerator), getattr(r, denominator)
            if n is not None and d is not None:
                num += n
                den += d
        return round(num / den, 4) if den > 0 else None

    return MarketStats(
        zcta_count=len(records),
        total_households=territory.totals.total_households,
        owner_occupied_households=territory.totals.owner_occupied_households,
        owner_households_age_45_plus=territory.totals.owner_households_age_45_plus,
        owner_households_age_55_plus=total("owner_households_age_55_plus"),
        owner_households_age_65_plus=total("owner_households_age_65_plus"),
        pre_2000_share=share("homes_built_before_2000", "total_housing_units"),
        pre_1990_share=share("homes_built_before_1990", "total_housing_units"),
        pre_1980_share=share("homes_built_before_1980", "total_housing_units"),
        median_household_income=territory.metrics.median_household_income,
        opportunity_score=territory.score,
        market_tier=territory.tier,
        opportunity_units=territory.opportunity_units,
        land_area_sq_miles=round(territory.totals.land_area_sq_miles, 2),
    )


# ---- talking points (facts only) ------------------------------------------------------------


def about(number: float | int) -> str:
    """'about 41,200': rounded to 100 above 1,000, to 10 below."""
    step = 100 if number >= 1000 else 10
    return f"about {int(round(number / step) * step):,}"


def pct(value: float | None) -> str:
    return "an unknown share" if value is None else f"{value:.0%}"


def talking_points(
    availability: str,
    stats: MarketStats | None,
    proposal: TerritoryProposal | None,
    entries: list[ConflictEntry],
    replacements: list[Suggestion],
    note: str,
    requested: Iterable[str] = (),
) -> list[str]:
    points: list[str] = []
    if availability == "NO_MARKET_DATA":
        return [f"No market data for this input. {note}"]
    if proposal is not None and proposal.status == "PROPOSED":
        n = len(proposal.zips)
        band = proposal.target
        if availability == "AVAILABLE":
            points.append(
                f"We currently have availability in this market: the proposed {n}-ZIP territory "
                f"has no conflicts and reaches the {band.size_class.value.title()} target band."
            )
        else:
            reasons: list[str] = []
            if entries:
                reasons.append(f"{len(entries)} requested ZIP(s) are held by other clients")
            if band and band.status not in ("WITHIN_TARGET", "ABOVE_TARGET"):
                reasons.append(f"the proposal is {band.status.replace('_', ' ').lower()}")
            points.append(
                f"Part of this market is available: the proposed {n}-ZIP territory can be "
                f"reserved, but {' and '.join(reasons) or 'review is needed'}."
            )
    elif availability == "UNAVAILABLE" and entries:
        first = entries[0]
        points.append(
            f"The starting ZIP {first.zcta} is {first.status.value.replace('_', ' ').lower()} "
            f"for {first.client_business_name} (internal); it cannot be offered."
        )
    if stats is not None:
        scope = "proposed territory" if stats.zcta_count > 1 else "starting ZIP"
        plural = "s" if stats.zcta_count != 1 else ""
        points.append(
            f"The {scope} ({stats.zcta_count} ZIP{plural}) contains "
            f"{about(stats.owner_occupied_households)} owner-occupied households, "
            f"{about(stats.owner_households_age_45_plus)} of them with a householder age 45 or "
            f"older, and {pct(stats.pre_2000_share)} of homes were built before 2000."
        )
        if stats.pre_1990_share is not None and stats.pre_1980_share is not None:
            points.append(
                f"About {pct(stats.pre_1990_share)} of homes predate 1990 and "
                f"{pct(stats.pre_1980_share)} predate 1980."
            )
        if stats.median_household_income is not None:
            points.append(
                f"Median household income across the {scope} is about "
                f"${stats.median_household_income:,.0f} (household-weighted)."
            )
        if stats.opportunity_score is not None:
            points.append(
                f"Opportunity Score {stats.opportunity_score:.0f} (Tier {stats.market_tier}), a "
                "comparative index of owner concentration, homeowner age, housing age, purchasing "
                f"power and density; {stats.opportunity_units:,.0f} Opportunity Units."
            )
    if entries and availability != "UNAVAILABLE":
        asked = set(requested)

        def held(items: list[ConflictEntry]) -> str:
            return ", ".join(
                f"{e.zcta} ({e.status.value.replace('_', ' ').lower()}, {e.client_business_name})"
                for e in items
            )

        wanted = [e for e in entries if e.zcta in asked]
        nearby = [e for e in entries if e.zcta not in asked]
        if wanted:
            points.append(f"Requested ZIPs held by other clients (internal): {held(wanted)}.")
        if nearby:
            points.append(
                f"Nearby ZIPs held by other clients and left out of the proposal (internal): "
                f"{held(nearby)}."
            )
    if replacements:
        alternatives = ", ".join(dict.fromkeys(s.zcta for s in replacements))
        points.append(f"Nearest available alternatives: {alternatives}.")
    elif not entries and proposal is not None:
        points.append("Conflicts: none.")
    points.append("A territory becomes protected only after a named approver reserves it.")
    return points


# ---- assembly ---------------------------------------------------------------------------------


def check_market(
    query: MarketQuery,
    market: MarketGraph,
    registry: RegistrySnapshot,
    rules: BusinessRules,
    as_of: date,
    *,
    city_start: str | None = None,
    city_candidates: Iterable[str] = (),
) -> MarketCheck:
    resolution = resolve_query(
        query, market, city_start=city_start, city_candidates=list(city_candidates)
    )
    base = {
        "query": query,
        "resolution": resolution,
        "as_of": as_of,
        "rules_version": rules.version,
    }
    start = resolution.starting_zip
    if start is None or not market.has(start):
        return MarketCheck(
            market_availability="NO_MARKET_DATA",
            talking_points=talking_points("NO_MARKET_DATA", None, None, [], [], resolution.note),
            **base,
        )
    requested = resolution.requested_zips
    proposal = generate_territory(
        TerritoryRequest(
            client_name=query.client_name,
            client_id=query.client_id,
            starting_zip=start,
            size_class=query.size_class,
            requested_zips=requested,
        ),
        market,
        registry,
        rules,
        as_of,
    )
    conflicts = None
    if requested:
        conflicts = (
            proposal.conflicts
            if proposal.status == "PROPOSED"
            else check_conflicts(requested, market, registry, rules, client_id=query.client_id)
        )
    failed = proposal.status == "FAILED"
    blocked = {e.zcta for e in proposal.excluded if e.reason.startswith("BLOCKED_")}
    if failed and proposal.failure and proposal.failure.code == "START_ZIP_UNAVAILABLE":
        blocked.add(start)
    classified = classify_zips(
        sorted(blocked | set(requested)), market, registry, client_id=query.client_id
    )
    entries = [*classified.reserved, *classified.protected, *classified.pending_release]
    replacements: list[Suggestion] = []
    seen: set[str] = set()
    candidates = list(conflicts.suggestions) if conflicts else []
    if failed and proposal.failure:
        candidates.extend(proposal.failure.suggestions)
    for suggestion in candidates:
        if suggestion.zcta not in seen:
            seen.add(suggestion.zcta)
            replacements.append(suggestion)
    if failed:
        code = proposal.failure.code if proposal.failure else "NO_MARKET_DATA"
        availability = "UNAVAILABLE" if code == "START_ZIP_UNAVAILABLE" else "NO_MARKET_DATA"
        stats = market_stats([market.records[start]], rules)
        suggested = None
    else:
        target_ok = proposal.target is not None and proposal.target.status in (
            "WITHIN_TARGET",
            "ABOVE_TARGET",
        )
        no_conflicts = conflicts is None or conflicts.conflict_count == 0
        availability = "AVAILABLE" if target_ok and no_conflicts else "PARTIALLY_AVAILABLE"
        stats = market_stats([market.records[z] for z in proposal.zip_codes], rules)
        suggested = proposal
    available = set(proposal.zip_codes) | set(classified.available)
    return MarketCheck(
        market_availability=availability,  # type: ignore[arg-type]
        suggested_territory=suggested,
        available_zips=sorted(available),
        reserved_zips=classified.reserved,
        protected_zips=classified.protected,
        pending_release_zips=classified.pending_release,
        replacement_zips=replacements,
        conflicts=conflicts,
        market_stats=stats,
        talking_points=talking_points(
            availability, stats, suggested, entries, replacements, resolution.note, requested
        ),
        **base,
    )
