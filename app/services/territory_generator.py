"""Territory generator (TERRITORY_ALGORITHM.md section 1, Milestone 5).

Pure: a request, a MarketGraph, a RegistrySnapshot, the rules and ``as_of`` in; a
TerritoryProposal out. Never mutates the registry. The priority order is fixed: availability,
contiguity, serviceability, opportunity quality (score discounted by distance), target size.
Every ordering key ends with the ZCTA code, so identical inputs give identical output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.config.business_rules import BusinessRules
from app.enums import TerritorySizeClass
from app.schemas.registry import RegistrySnapshot
from app.schemas.territory import (
    ExcludedZip,
    ProposalAggregates,
    ProposalFailure,
    ProposalZip,
    TargetInfo,
    TerritoryProposal,
    TerritoryRequest,
)
from app.services.conflicts import classify_zips, nearest_available
from app.services.market import MarketGraph
from app.services.registry import availability_for
from app.services.scoring import score_territory

FLAG_UNSERVICEABLE_START = "UNSERVICEABLE_LAND_AREA"
FLAG_CONTAINS_UNSERVICEABLE = "CONTAINS_UNSERVICEABLE"
FLAG_FRONTIER_EXHAUSTED = "FRONTIER_EXHAUSTED"
FLAG_NO_CANDIDATE_FITS_BAND = "NO_CANDIDATE_FITS_BAND"
FLAG_MAX_ZCTAS_REACHED = "MAX_ZCTAS_REACHED"
FLAG_EXCEEDS_MAX_SIZE = "EXCEEDS_MAX_SIZE"
FLAG_CROSSES_STATE_LINE = "CROSSES_STATE_LINE"
FLAG_RADIUS_CLAMPED = "RADIUS_CLAMPED"


@dataclass
class _Context:
    request: TerritoryRequest
    market: MarketGraph
    registry: RegistrySnapshot
    rules: BusinessRules
    as_of: date
    size_class: TerritorySizeClass
    radius: float
    allow_cross_state: bool
    start: str
    zips: list[ProposalZip] = field(default_factory=list)
    excluded: dict[str, ExcludedZip] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    explanation: list[str] = field(default_factory=list)
    pending_requested: list[str] = field(default_factory=list)

    @property
    def members(self) -> list[str]:
        return [z.zcta for z in self.zips]

    @property
    def opportunity_units(self) -> float:
        return sum(z.opportunity_units or 0.0 for z in self.zips)

    def flag(self, name: str) -> None:
        if name not in self.flags:
            self.flags.append(name)

    def exclude(self, zcta: str, reason: str, detail: str) -> None:
        if zcta not in self.excluded:  # one reason per ZCTA: the first that applied
            self.excluded[zcta] = ExcludedZip(zcta=zcta, reason=reason, detail=detail)

    def miles(self, zcta: str) -> float:
        return self.market.distance_miles(self.start, zcta) or 0.0

    def tier_rank(self, tier: str) -> int:
        order = self.rules.scoring.tier_order
        return order.index(tier) if tier in order else len(order)

    def exclusion_reason(self, zcta: str) -> tuple[str, str] | None:
        """First rule that keeps a ZCTA out, in the algorithm's priority order."""
        if not self.market.has(zcta):
            return "NO_MARKET_DATA", "no market record for this code"
        state = availability_for(zcta, self.registry, client_id=self.request.client_id)
        if state.is_conflict and state.blocking is not None:
            info = state.blocking
            detail = (
                f"{info.status.value} for territory {info.territory_id} "
                f"({info.client_business_name})"
            )
            if info.expired:
                detail += ", reservation expired"
            return f"BLOCKED_{info.status.value}", detail
        score = self.market.scores[zcta]
        if score.score is None or score.opportunity_units is None:
            return "UNSCORED", score.unscored_reason or score.ou_reason or "no score"
        min_tier = self.rules.generator.min_tier_for_auto_selection
        if self.tier_rank(score.tier) > self.tier_rank(min_tier):
            return "BELOW_MIN_TIER", f"tier {score.tier} is below the {min_tier} minimum"
        if zcta in self.market.unserviceable:
            area = self.market.records[zcta].land_area_sq_miles or 0.0
            cap = self.rules.serviceability.max_zcta_land_area_sq_miles
            return "UNSERVICEABLE_LAND_AREA", f"{area:,.0f} sq mi exceeds the {cap:,.0f} sq mi cap"
        miles = self.miles(zcta)
        if miles > self.radius:
            return "OUTSIDE_SERVICE_RADIUS", f"{miles:.1f} mi from start; radius {self.radius:g} mi"
        start_state = self.market.state(self.start)
        if not self.allow_cross_state and self.market.state(zcta) != start_state:
            return "CROSS_STATE_DISALLOWED", f"{self.market.state(zcta)} differs from {start_state}"
        return None

    def add(self, zcta: str, reason: str, explanation: str) -> None:
        score = self.market.scores[zcta]
        self.zips.append(
            ProposalZip(
                zcta=zcta,
                order=len(self.zips) + 1,
                reason=reason,  # type: ignore[arg-type]
                explanation=explanation,
                score=score.score,
                tier=score.tier,
                opportunity_units=score.opportunity_units,
                miles_from_start=round(self.miles(zcta), 2),
                state=self.market.state(zcta),
            )
        )
        self.explanation.append(explanation)

    def is_adjacent(self, zcta: str) -> bool:
        return bool(self.market.neighbours(zcta) & set(self.members))

    def rank_key(self, zcta: str) -> tuple:
        score = self.market.scores[zcta]
        miles = self.miles(zcta)
        penalty = self.rules.generator.distance_penalty_points_per_mile
        keys: list[float | str] = [-((score.score or 0.0) - penalty * miles)]
        for breaker in self.rules.generator.tie_breakers:
            if breaker == "distance_asc":
                keys.append(miles)
            elif breaker == "opportunity_units_desc":
                keys.append(-(score.opportunity_units or 0.0))
            else:
                keys.append(zcta)
        return tuple(keys)


def _fail(ctx: _Context, failure: ProposalFailure) -> TerritoryProposal:
    return TerritoryProposal(
        status="FAILED",
        failure=failure,
        client_name=ctx.request.client_name,
        client_id=ctx.request.client_id,
        starting_zip=ctx.start,
        size_class=ctx.size_class,
        rules_version=ctx.rules.version,
        as_of=ctx.as_of,
        explanation=[failure.message],
    )


def _seed_requested(ctx: _Context) -> None:
    """Add deferred requested ZIPs that became adjacent; repeat until nothing changes."""
    changed = True
    while changed and ctx.pending_requested:
        changed = False
        for zcta in list(ctx.pending_requested):
            reason = ctx.exclusion_reason(zcta)
            if reason is not None:
                ctx.exclude(zcta, *reason)
                ctx.pending_requested.remove(zcta)
                continue
            if ctx.is_adjacent(zcta):
                score = ctx.market.scores[zcta]
                ctx.add(
                    zcta,
                    "REQUESTED",
                    f"{zcta} included: requested by prospect, adjacent, Tier {score.tier} "
                    f"(score {score.score}), {ctx.miles(zcta):.1f} mi from start.",
                )
                ctx.pending_requested.remove(zcta)
                changed = True


def _expand(ctx: _Context) -> None:
    sizes = ctx.rules.territory_sizes
    band = sizes.bands.get(ctx.size_class.value)
    cap = band.target_max * (1 + sizes.target_tolerance)
    while ctx.opportunity_units < band.target_min:
        if len(ctx.zips) >= sizes.max_zctas_per_territory:
            ctx.flag(FLAG_MAX_ZCTAS_REACHED)
            return
        members = set(ctx.members)
        frontier = sorted({n for z in members for n in ctx.market.neighbours(z)} - members)
        eligible: list[str] = []
        for zcta in frontier:
            if zcta in ctx.excluded:
                continue
            reason = ctx.exclusion_reason(zcta)
            if reason is not None:
                ctx.exclude(zcta, *reason)
            else:
                eligible.append(zcta)
        if not eligible:
            ctx.flag(FLAG_FRONTIER_EXHAUSTED)
            return
        ranked = sorted(eligible, key=ctx.rank_key)
        chosen = None
        for zcta in ranked:
            units = ctx.market.scores[zcta].opportunity_units or 0.0
            if ctx.opportunity_units + units <= cap:
                chosen = zcta
                break
        if chosen is None:
            ctx.flag(FLAG_NO_CANDIDATE_FITS_BAND)
            for zcta in ranked:
                ctx.exclude(zcta, "WOULD_EXCEED_BAND", f"would push OU above {cap:,.0f}")
            return
        score = ctx.market.scores[chosen]
        after = ctx.opportunity_units + (score.opportunity_units or 0.0)
        ctx.add(
            chosen,
            "SELECTED",
            f"{chosen} selected: adjacent, available, Tier {score.tier} (score {score.score}), "
            f"{ctx.miles(chosen):.1f} mi from start; territory at {after:,.0f} of "
            f"{band.target_min:,.0f}-{band.target_max:,.0f} OU.",
        )
        _seed_requested(ctx)


def _evaluate(ctx: _Context) -> TerritoryProposal:
    sizes = ctx.rules.territory_sizes
    band = sizes.bands.get(ctx.size_class.value)
    records = [ctx.market.records[z] for z in ctx.members]
    territory = score_territory(records, ctx.rules)

    def total(field_name: str) -> int:
        return int(sum(getattr(r, field_name) or 0 for r in records))

    aggregates = ProposalAggregates(
        zcta_count=len(records),
        total_population=territory.totals.total_population,
        total_households=territory.totals.total_households,
        owner_occupied_households=territory.totals.owner_occupied_households,
        owner_households_age_45_plus=territory.totals.owner_households_age_45_plus,
        owner_households_age_55_plus=total("owner_households_age_55_plus"),
        owner_households_age_65_plus=total("owner_households_age_65_plus"),
        total_housing_units=territory.totals.total_housing_units,
        homes_built_before_2000=territory.totals.homes_built_before_2000,
        homes_built_before_1990=total("homes_built_before_1990"),
        homes_built_before_1980=total("homes_built_before_1980"),
        median_household_income=territory.metrics.median_household_income,
        land_area_sq_miles=round(territory.totals.land_area_sq_miles, 3),
        opportunity_units=territory.opportunity_units,
        opportunity_score=territory.score,
        market_tier=territory.tier,
    )
    units = territory.opportunity_units
    if units < sizes.minimum_viable_units:
        status = "BELOW_MINIMUM_VIABLE"
    elif units < band.target_min:
        status = "BELOW_TARGET"
    elif units <= band.target_max * (1 + sizes.target_tolerance):
        status = "WITHIN_TARGET"
    else:
        status = "ABOVE_TARGET"
    ctx.flag(status)
    if units > sizes.absolute_max_units or len(records) > sizes.max_zctas_per_territory:
        ctx.flag(FLAG_EXCEEDS_MAX_SIZE)
    if len({r.state for r in records if r.state}) > 1:
        ctx.flag(FLAG_CROSSES_STATE_LINE)
    if any(z in ctx.market.unserviceable for z in ctx.members):
        ctx.flag(FLAG_CONTAINS_UNSERVICEABLE)
    for zcta in ctx.pending_requested:
        ctx.exclude(zcta, "NOT_CONTIGUOUS", "never adjacent to the proposed territory")
    for item in ctx.excluded.values():
        ctx.explanation.append(f"{item.zcta} excluded: {item.detail} [{item.reason}].")
    return TerritoryProposal(
        status="PROPOSED",
        client_name=ctx.request.client_name,
        client_id=ctx.request.client_id,
        starting_zip=ctx.start,
        size_class=ctx.size_class,
        rules_version=ctx.rules.version,
        as_of=ctx.as_of,
        zips=ctx.zips,
        excluded=sorted(ctx.excluded.values(), key=lambda e: e.zcta),
        aggregates=aggregates,
        target=TargetInfo(
            size_class=ctx.size_class,
            band_min=band.target_min,
            band_max=band.target_max,
            tolerance=sizes.target_tolerance,
            minimum_viable=sizes.minimum_viable_units,
            status=status,  # type: ignore[arg-type]
        ),
        conflicts=classify_zips(
            ctx.request.requested_zips, ctx.market, ctx.registry, client_id=ctx.request.client_id
        ),
        flags=ctx.flags,
        explanation=ctx.explanation,
    )


def generate_territory(
    request: TerritoryRequest,
    market: MarketGraph,
    registry: RegistrySnapshot,
    rules: BusinessRules,
    as_of: date,
) -> TerritoryProposal:
    size_class = request.size_class or TerritorySizeClass(
        rules.territory_sizes.default_size_class.upper()
    )
    max_radius = rules.serviceability.max_service_radius_miles
    requested_radius = request.max_service_distance_miles
    radius = min(requested_radius or rules.serviceability.default_service_radius_miles, max_radius)
    allow_cross = (
        request.allow_cross_state
        if request.allow_cross_state is not None
        else rules.serviceability.allow_cross_state
    )
    ctx = _Context(
        request=request,
        market=market,
        registry=registry,
        rules=rules,
        as_of=as_of,
        size_class=size_class,
        radius=radius,
        allow_cross_state=allow_cross,
        start=request.starting_zip,
    )
    if requested_radius is not None and requested_radius > max_radius:
        ctx.flag(FLAG_RADIUS_CLAMPED)
        ctx.explanation.append(f"Service radius clamped to the {max_radius:g} mi maximum.")

    start = request.starting_zip
    if not market.has(start):
        failure = ProposalFailure(code="NO_MARKET_DATA", message=f"No market data for {start}.")
        return _fail(ctx, failure)
    state = availability_for(start, registry, client_id=request.client_id)
    if state.is_conflict and state.blocking is not None:
        info = state.blocking
        failure = ProposalFailure(
            code="START_ZIP_UNAVAILABLE",
            message=(
                f"{start} is {info.status.value} for territory {info.territory_id} "
                f"({info.client_business_name})."
            ),
            blocking_territory_id=info.territory_id,
            blocking_status=info.status,
            suggestions=nearest_available(
                start,
                market,
                registry,
                client_id=request.client_id,
                limit=rules.generator.replacement_suggestions,
            ),
        )
        return _fail(ctx, failure)
    ctx.add(start, "STARTING_ZIP", f"{start} included: starting ZIP.")
    if start in market.unserviceable:
        ctx.flag(FLAG_UNSERVICEABLE_START)
        area = market.records[start].land_area_sq_miles or 0.0
        cap = rules.serviceability.max_zcta_land_area_sq_miles
        ctx.explanation.append(
            f"{start} covers {area:,.0f} sq mi, above the {cap:,.0f} sq mi cap; a human decides."
        )
    ctx.pending_requested = [z for z in dict.fromkeys(request.requested_zips) if z != start]
    _seed_requested(ctx)
    _expand(ctx)
    return _evaluate(ctx)
