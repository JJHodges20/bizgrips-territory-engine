"""Opportunity Score, Opportunity Units and territory aggregation (SCORING_SPEC.md).

Pure functions over ``ZctaRecord`` plus ``BusinessRules``: no I/O, no clock, no randomness.
Components are evaluated in ``COMPONENT_NAMES`` order and rounded only at the end, so the same
inputs always give byte-identical output. Scores are comparative indices for sales
intelligence, never predictions of marketing performance.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from app.config.business_rules import COMPONENT_NAMES, BusinessRules, ComponentRamp
from app.schemas.market import ZctaRecord
from app.schemas.scoring import (
    OU_INSUFFICIENT_DATA,
    UNSCORED_INSUFFICIENT_HOUSEHOLDS,
    UNSCORED_MISSING_REQUIRED_PREFIX,
    ComponentScore,
    MetricComparison,
    OpportunityUnits,
    OuFactors,
    TerritoryComparison,
    TerritoryMetrics,
    TerritoryScore,
    TerritoryTotals,
    ZctaScore,
)

COMPONENT_DISPLAY_DECIMALS = 2
SHARE_DISPLAY_DECIMALS = 6


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


# ---- component ramps (section 3) --------------------------------------------------------------


def ramp_score(value: float | None, ramp: ComponentRamp) -> float | None:
    """Map a metric value to 0..100 through the ramp; None stays None."""
    if value is None:
        return None
    if ramp.scale == "log10":
        if value <= 0:
            return 0.0
        position = (math.log10(value) - math.log10(ramp.floor)) / (
            math.log10(ramp.ceiling) - math.log10(ramp.floor)
        )
    else:
        position = (value - ramp.floor) / (ramp.ceiling - ramp.floor)
    return clamp(100.0 * position, 0.0, 100.0)


def _components(
    metrics: dict[str, float | None], rules: BusinessRules
) -> dict[str, ComponentScore]:
    weights = rules.scoring.weights.as_dict()
    out: dict[str, ComponentScore] = {}
    for name in COMPONENT_NAMES:
        ramp = rules.scoring.components.get(name)
        value = metrics.get(ramp.metric)
        score = ramp_score(value, ramp)
        out[name] = ComponentScore(
            metric=ramp.metric,
            value=None if value is None else round(value, SHARE_DISPLAY_DECIMALS),
            score=None if score is None else round(score, COMPONENT_DISPLAY_DECIMALS),
            weight=weights[name],
            missing=score is None,
        )
    return out


def _weighted_score(
    metrics: dict[str, float | None], rules: BusinessRules
) -> tuple[float | None, dict[str, ComponentScore], float, list[str], str | None]:
    """Shared by ZCTA and territory scoring: (score, components, completeness, missing, reason).

    The score is computed from unrounded component values in a fixed order; the reported
    component scores are rounded for display only.
    """
    scoring = rules.scoring
    weights = scoring.weights.as_dict()
    components = _components(metrics, rules)
    raw: dict[str, float | None] = {}
    for name in COMPONENT_NAMES:
        ramp = scoring.components.get(name)
        raw[name] = ramp_score(metrics.get(ramp.metric), ramp)
    missing = [name for name in COMPONENT_NAMES if raw[name] is None]
    completeness = round(sum(weights[name] for name in COMPONENT_NAMES if raw[name] is not None), 6)
    for name in scoring.required_components:
        if raw[name] is None:
            reason = UNSCORED_MISSING_REQUIRED_PREFIX + name.upper()
            return None, components, completeness, missing, reason
    weighted = 0.0
    for name in COMPONENT_NAMES:
        if raw[name] is not None:
            weighted += weights[name] * raw[name]
    if scoring.missing_data_policy == "renormalize":
        if completeness <= 0:
            return None, components, completeness, missing, "NO_COMPONENTS"
        score = weighted / completeness
    else:  # "zero": missing components score 0, weights unchanged
        score = weighted
    return round(score, scoring.rounding_decimals), components, completeness, missing, None


# ---- Opportunity Units (section 6) ------------------------------------------------------------


def opportunity_units(record: ZctaRecord, rules: BusinessRules) -> OpportunityUnits:
    ou_rules = rules.opportunity_units
    owner = record.owner_occupied_households
    result = OpportunityUnits(zcta=record.zcta, base_owner_households=owner)
    if owner is None:
        result.reason = OU_INSUFFICIENT_DATA
        result.missing_factors = ["age", "housing_age", "purchasing_power"]
        return result

    missing: list[str] = []
    neutral = ou_rules.missing_factor_policy == "neutral"

    share_45 = record.owner_45_plus_share
    if share_45 is not None:
        age = ou_rules.age_45_plus_floor + (1.0 - ou_rules.age_45_plus_floor) * share_45
    elif owner == 0:
        age = 0.0
    elif ou_rules.age_45_plus_floor > 0:
        age = ou_rules.age_45_plus_floor
        missing.append("age")
    else:
        result.reason = OU_INSUFFICIENT_DATA
        result.missing_factors = ["age"]
        return result

    hf = ou_rules.housing_age_factor
    pre_2000 = record.pre_2000_share
    if pre_2000 is None:
        housing = 1.0 if neutral else hf.floor
        missing.append("housing_age")
    else:
        housing = hf.floor + (1.0 - hf.floor) * min(pre_2000 / hf.share_at_full_credit, 1.0)

    pf = ou_rules.purchasing_power_factor
    income = record.median_household_income
    if income is None:
        purchasing = 1.0 if neutral else pf.floor
        missing.append("purchasing_power")
    else:
        span = pf.income_at_full_credit - pf.income_at_floor
        position = (income - pf.income_at_floor) / span
        purchasing = clamp(pf.floor + (1.0 - pf.floor) * position, pf.floor, 1.0)

    result.factors = OuFactors(
        age=round(age, SHARE_DISPLAY_DECIMALS),
        housing_age=round(housing, SHARE_DISPLAY_DECIMALS),
        purchasing_power=round(purchasing, SHARE_DISPLAY_DECIMALS),
    )
    result.missing_factors = missing
    result.opportunity_units = round(owner * age * housing * purchasing, ou_rules.rounding_decimals)
    return result


# ---- ZCTA score (sections 4-5) -----------------------------------------------------------------

_METRIC_NAMES = (
    "owner_occupancy_share",
    "owner_45_plus_share",
    "pre_2000_share",
    "median_household_income",
    "households_per_sq_mile",
)


def score_zcta(record: ZctaRecord, rules: BusinessRules) -> ZctaScore:
    scoring = rules.scoring
    metrics = {name: record.metric(name) for name in _METRIC_NAMES}
    score, components, completeness, missing, reason = _weighted_score(metrics, rules)
    households = record.total_households
    if households is None or households < scoring.min_households_for_scoring:
        score, reason = None, UNSCORED_INSUFFICIENT_HOUSEHOLDS
    ou = opportunity_units(record, rules)
    return ZctaScore(
        zcta=record.zcta,
        score=score,
        tier=scoring.tier_for(score),
        components=components,
        data_completeness=completeness,
        missing_components=missing,
        unscored_reason=reason,
        opportunity_units=ou.opportunity_units,
        ou_factors=ou.factors,
        missing_factors=ou.missing_factors,
        ou_reason=ou.reason,
        config_version=rules.version,
    )


# ---- territory aggregation (section 7) --------------------------------------------------------

_TOTAL_FIELDS = (
    "total_population",
    "total_households",
    "owner_occupied_households",
    "owner_households_age_45_plus",
    "total_housing_units",
    "homes_built_before_2000",
    "land_area_sq_miles",
)


def _paired_ratio(records: list[ZctaRecord], numerator: str, denominator: str) -> float | None:
    """Ratio of sums over the ZCTAs where both fields are present; None if no denominator."""
    num = den = 0.0
    for record in records:
        n, d = getattr(record, numerator), getattr(record, denominator)
        if n is not None and d is not None:
            num += n
            den += d
    return num / den if den > 0 else None


def territory_totals(records: list[ZctaRecord]) -> TerritoryTotals:
    sums: dict[str, float] = dict.fromkeys(_TOTAL_FIELDS, 0.0)
    missing: dict[str, list[str]] = {}
    for record in records:
        for field in _TOTAL_FIELDS:
            value = getattr(record, field)
            if value is None:
                missing.setdefault(field, []).append(record.zcta)
            else:
                sums[field] += value
    return TerritoryTotals(
        zcta_count=len(records),
        total_population=int(sums["total_population"]),
        total_households=int(sums["total_households"]),
        owner_occupied_households=int(sums["owner_occupied_households"]),
        owner_households_age_45_plus=int(sums["owner_households_age_45_plus"]),
        total_housing_units=int(sums["total_housing_units"]),
        homes_built_before_2000=int(sums["homes_built_before_2000"]),
        land_area_sq_miles=sums["land_area_sq_miles"],
        missing_by_field=missing,
    )


def territory_metrics(records: list[ZctaRecord]) -> TerritoryMetrics:
    weighted_income = weight = 0.0
    for record in records:
        if record.median_household_income is not None and record.total_households:
            weighted_income += record.median_household_income * record.total_households
            weight += record.total_households
    return TerritoryMetrics(
        owner_occupancy_share=_paired_ratio(
            records, "owner_occupied_households", "total_households"
        ),
        owner_45_plus_share=_paired_ratio(
            records, "owner_households_age_45_plus", "owner_occupied_households"
        ),
        pre_2000_share=_paired_ratio(records, "homes_built_before_2000", "total_housing_units"),
        households_per_sq_mile=_paired_ratio(records, "total_households", "land_area_sq_miles"),
        median_household_income=weighted_income / weight if weight > 0 else None,
    )


def score_territory(records: Iterable[ZctaRecord], rules: BusinessRules) -> TerritoryScore:
    """Score the territory from its summed metrics; OU is the sum of ZCTA OU (None counts 0)."""
    ordered = sorted(records, key=lambda r: r.zcta)
    totals = territory_totals(ordered)
    metrics = territory_metrics(ordered)
    score, components, completeness, missing, reason = _weighted_score(metrics.model_dump(), rules)
    if totals.total_households < rules.scoring.min_households_for_scoring:
        score, reason = None, UNSCORED_INSUFFICIENT_HOUSEHOLDS
    zcta_scores = [score_zcta(record, rules) for record in ordered]
    units = 0.0
    missing_ou: list[str] = []
    for zs in zcta_scores:
        if zs.opportunity_units is None:
            missing_ou.append(zs.zcta)
        else:
            units += zs.opportunity_units
    return TerritoryScore(
        zctas=[r.zcta for r in ordered],
        totals=totals,
        metrics=metrics,
        score=score,
        tier=rules.scoring.tier_for(score),
        components=components,
        data_completeness=completeness,
        missing_components=missing,
        unscored_reason=reason,
        opportunity_units=round(units, rules.opportunity_units.rounding_decimals),
        missing_ou_zctas=missing_ou,
        zcta_tiers={zs.zcta: zs.tier for zs in zcta_scores},
        config_version=rules.version,
    )


# ---- side-by-side comparison (section 7) ------------------------------------------------------

_COMPARED = (
    ("opportunity_units", "higher"),
    ("score", "higher"),
    ("total_households", "higher"),
    ("owner_occupied_households", "higher"),
    ("owner_households_age_45_plus", "higher"),
    ("land_area_sq_miles", "lower"),
    ("zcta_count", "lower"),
)


def _lookup(territory: TerritoryScore, name: str) -> float | None:
    if name in ("opportunity_units", "score"):
        return getattr(territory, name)
    return getattr(territory.totals, name)


def compare_territories(a: TerritoryScore, b: TerritoryScore) -> TerritoryComparison:
    """Side-by-side comparison; ``better`` says which territory wins each measure."""
    comparisons: dict[str, MetricComparison] = {}
    for name, preference in _COMPARED:
        va, vb = _lookup(a, name), _lookup(b, name)
        if va is None or vb is None:
            comparisons[name] = MetricComparison(a=va, b=vb)
            continue
        delta = vb - va
        if math.isclose(va, vb, rel_tol=1e-9, abs_tol=1e-9):
            better = "tie"
        elif (delta > 0) == (preference == "higher"):
            better = "b"
        else:
            better = "a"
        comparisons[name] = MetricComparison(a=va, b=vb, delta=delta, better=better)
    ratio = b.opportunity_units / a.opportunity_units if a.opportunity_units > 0 else None
    summary = (
        f"A: {a.opportunity_units:,.0f} OU, score {a.score} ({a.tier}), "
        f"{a.totals.zcta_count} ZCTAs; B: {b.opportunity_units:,.0f} OU, score {b.score} "
        f"({b.tier}), {b.totals.zcta_count} ZCTAs."
    )
    return TerritoryComparison(
        a=a,
        b=b,
        comparisons=comparisons,
        ou_ratio_b_to_a=ratio,
        same_tier=a.tier == b.tier,
        summary=summary,
    )
