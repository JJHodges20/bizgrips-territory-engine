"""Evaluate a hand-picked ZIP grouping (Milestone 8 map selections) without writing anything."""

from __future__ import annotations

from datetime import date

from app.config.business_rules import BusinessRules
from app.enums import TerritorySizeClass
from app.schemas.market import ZctaRecord
from app.schemas.registry import RegistrySnapshot
from app.schemas.territory import GroupEvaluation, GroupZip, ProposalAggregates, TargetInfo
from app.services.conflict_checker import check_conflicts
from app.services.market import MarketGraph
from app.services.registry import availability_for
from app.services.scoring import score_territory


def build_aggregates(records: list[ZctaRecord], rules: BusinessRules) -> ProposalAggregates:
    territory = score_territory(records, rules)

    def total(name: str) -> int:
        return int(sum(getattr(r, name) or 0 for r in records))

    return ProposalAggregates(
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


def target_status(units: float, size_class: TerritorySizeClass, rules: BusinessRules) -> TargetInfo:
    sizes = rules.territory_sizes
    band = sizes.bands.get(size_class.value)
    if units < sizes.minimum_viable_units:
        status = "BELOW_MINIMUM_VIABLE"
    elif units < band.target_min:
        status = "BELOW_TARGET"
    elif units <= band.target_max * (1 + sizes.target_tolerance):
        status = "WITHIN_TARGET"
    else:
        status = "ABOVE_TARGET"
    return TargetInfo(
        size_class=size_class,
        band_min=band.target_min,
        band_max=band.target_max,
        tolerance=sizes.target_tolerance,
        minimum_viable=sizes.minimum_viable_units,
        status=status,  # type: ignore[arg-type]
    )


def evaluate_group(
    zips: list[str],
    market: MarketGraph,
    registry: RegistrySnapshot,
    rules: BusinessRules,
    as_of: date,
    *,
    size_class: TerritorySizeClass | None = None,
    client_id: str | None = None,
) -> GroupEvaluation:
    size = size_class or TerritorySizeClass(rules.territory_sizes.default_size_class.upper())
    codes = list(dict.fromkeys(z.strip() for z in zips if z and z.strip()))
    known = [z for z in codes if market.has(z)]
    unknown = [z for z in codes if not market.has(z)]
    conflicts = check_conflicts(known, market, registry, rules, client_id=client_id)
    per_zip: list[GroupZip] = []
    for zcta in known:
        record, score = market.records[zcta], market.scores[zcta]
        state = availability_for(zcta, registry, client_id=client_id)
        per_zip.append(
            GroupZip(
                zcta=zcta,
                primary_city=record.primary_city,
                state=record.state,
                tier=score.tier,
                score=score.score,
                opportunity_units=score.opportunity_units,
                owner_occupied_households=record.owner_occupied_households,
                availability=state.availability.value,
                blocking_territory_id=state.blocking.territory_id if state.blocking else None,
                blocking_client=state.blocking.client_business_name if state.blocking else None,
                unserviceable=zcta in market.unserviceable,
            )
        )
    flags: list[str] = []
    aggregates = target = None
    if known:
        records = [market.records[z] for z in known]
        aggregates = build_aggregates(records, rules)
        target = target_status(aggregates.opportunity_units, size, rules)
        flags.append(target.status)
        sizes = rules.territory_sizes
        if (
            aggregates.opportunity_units > sizes.absolute_max_units
            or len(known) > sizes.max_zctas_per_territory
        ):
            flags.append("EXCEEDS_MAX_SIZE")
        if len({r.state for r in records if r.state}) > 1:
            flags.append("CROSSES_STATE_LINE")
        if any(z.unserviceable for z in per_zip):
            flags.append("CONTAINS_UNSERVICEABLE")
        if any(z.tier == rules.scoring.unscored_tier for z in per_zip):
            flags.append("CONTAINS_UNSCORED")
    if not conflicts.contiguous:
        flags.append("NOT_CONTIGUOUS")
    if conflicts.conflict_count:
        flags.append("CONTAINS_BLOCKED")
    if unknown:
        flags.append("CONTAINS_UNKNOWN")
    return GroupEvaluation(
        zips=known,
        unknown_zips=unknown,
        size_class=size,
        as_of=as_of,
        rules_version=rules.version,
        aggregates=aggregates,
        target=target,
        contiguous=conflicts.contiguous,
        components=conflicts.components,
        conflicts=conflicts,
        per_zip=per_zip,
        flags=flags,
        can_save=bool(known) and conflicts.conflict_count == 0 and not unknown,
    )
