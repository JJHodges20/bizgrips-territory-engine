"""Output schemas of the scoring service (SCORING_SPEC.md section 10). Plain data, no ORM."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

UNSCORED_INSUFFICIENT_HOUSEHOLDS = "INSUFFICIENT_HOUSEHOLDS"
UNSCORED_MISSING_REQUIRED_PREFIX = "MISSING_REQUIRED_"
OU_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

FactorName = Literal["age", "housing_age", "purchasing_power"]


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ComponentScore(StrictSchema):
    """One ramp evaluation: the metric it reads, the value seen, the 0-100 score, its weight."""

    metric: str
    value: float | None = None
    score: float | None = None
    weight: float
    missing: bool = False


class OuFactors(StrictSchema):
    age: float | None = None
    housing_age: float | None = None
    purchasing_power: float | None = None


class OpportunityUnits(StrictSchema):
    """Comparative index of desirable homeowner households; never a sales forecast."""

    zcta: str
    opportunity_units: float | None = None
    base_owner_households: int | None = None
    factors: OuFactors = Field(default_factory=OuFactors)
    missing_factors: list[str] = Field(default_factory=list)
    reason: str | None = None  # OU_INSUFFICIENT_DATA when opportunity_units is None


class ZctaScore(StrictSchema):
    zcta: str
    score: float | None = None
    tier: str
    components: dict[str, ComponentScore]
    data_completeness: float
    missing_components: list[str] = Field(default_factory=list)
    unscored_reason: str | None = None
    opportunity_units: float | None = None
    ou_factors: OuFactors = Field(default_factory=OuFactors)
    missing_factors: list[str] = Field(default_factory=list)
    ou_reason: str | None = None
    config_version: str

    @property
    def is_scored(self) -> bool:
        return self.score is not None


class TerritoryTotals(StrictSchema):
    """Sums over the territory's ZCTAs; a field's sum skips ZCTAs where it is missing."""

    zcta_count: int
    total_population: int = 0
    total_households: int = 0
    owner_occupied_households: int = 0
    owner_households_age_45_plus: int = 0
    total_housing_units: int = 0
    homes_built_before_2000: int = 0
    land_area_sq_miles: float = 0.0
    missing_by_field: dict[str, list[str]] = Field(
        default_factory=dict, description="field -> ZCTAs where it is missing"
    )


class TerritoryMetrics(StrictSchema):
    """Territory-level metrics from paired totals (both numerator and denominator present)."""

    owner_occupancy_share: float | None = None
    owner_45_plus_share: float | None = None
    pre_2000_share: float | None = None
    households_per_sq_mile: float | None = None
    median_household_income: float | None = None  # household-weighted mean of ZCTA medians


class TerritoryScore(StrictSchema):
    zctas: list[str]
    totals: TerritoryTotals
    metrics: TerritoryMetrics
    score: float | None = None
    tier: str
    components: dict[str, ComponentScore]
    data_completeness: float
    missing_components: list[str] = Field(default_factory=list)
    unscored_reason: str | None = None
    opportunity_units: float
    missing_ou_zctas: list[str] = Field(default_factory=list)
    zcta_tiers: dict[str, str] = Field(default_factory=dict)
    config_version: str


class MetricComparison(StrictSchema):
    a: float | None = None
    b: float | None = None
    delta: float | None = None  # b - a
    better: Literal["a", "b", "tie", "unknown"] = "unknown"


class TerritoryComparison(StrictSchema):
    """Side-by-side view of two proposed territories (Phase 3 definition of done)."""

    a: TerritoryScore
    b: TerritoryScore
    comparisons: dict[str, MetricComparison]
    ou_ratio_b_to_a: float | None = None
    same_tier: bool
    summary: str
