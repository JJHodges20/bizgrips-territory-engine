"""Typed, validated access to app/config/business_rules.yaml.

Every tunable business number is loaded through this module so that scoring, territory
generation and the registry never carry hard-coded constants. Validation fails fast on
inconsistent configuration (weights not summing to 1, overlapping size bands, unknown tiers).
"""

from __future__ import annotations

import math
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.enums import AssignmentStatus, TerritoryStatus

COMPONENT_NAMES: tuple[str, ...] = (
    "owner_concentration",
    "owner_age_45_plus",
    "housing_age",
    "purchasing_power",
    "serviceability",
)

MetricName = Literal[
    "owner_occupancy_share",
    "owner_45_plus_share",
    "pre_2000_share",
    "median_household_income",
    "households_per_sq_mile",
]

TieBreaker = Literal["distance_asc", "opportunity_units_desc", "zcta_asc"]
SizeClassName = Literal["small", "standard", "large"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --------------------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------------------


class ScoringWeights(StrictModel):
    owner_concentration: float = Field(ge=0, le=1)
    owner_age_45_plus: float = Field(ge=0, le=1)
    housing_age: float = Field(ge=0, le=1)
    purchasing_power: float = Field(ge=0, le=1)
    serviceability: float = Field(ge=0, le=1)

    def as_dict(self) -> dict[str, float]:
        return {name: getattr(self, name) for name in COMPONENT_NAMES}

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> ScoringWeights:
        total = sum(self.as_dict().values())
        if not math.isclose(total, 1.0, abs_tol=1e-6):
            raise ValueError(f"scoring.weights must sum to 1.0, got {total:.6f}")
        return self


class ComponentRamp(StrictModel):
    """Maps a metric to 0..100 via a clamped linear or log10 ramp (SCORING_SPEC.md section 3)."""

    metric: MetricName
    scale: Literal["linear", "log10"] = "linear"
    floor: float
    ceiling: float

    @model_validator(mode="after")
    def _ordered(self) -> ComponentRamp:
        if self.floor >= self.ceiling:
            raise ValueError(f"ramp floor ({self.floor}) must be below ceiling ({self.ceiling})")
        if self.scale == "log10" and self.floor <= 0:
            raise ValueError("log10 ramps need a positive floor")
        return self


class ScoringComponents(StrictModel):
    owner_concentration: ComponentRamp
    owner_age_45_plus: ComponentRamp
    housing_age: ComponentRamp
    purchasing_power: ComponentRamp
    serviceability: ComponentRamp

    def get(self, name: str) -> ComponentRamp:
        if name not in COMPONENT_NAMES:
            raise KeyError(name)
        return getattr(self, name)


class ScoringRules(StrictModel):
    weights: ScoringWeights
    components: ScoringComponents
    missing_data_policy: Literal["renormalize", "zero"] = "renormalize"
    required_components: tuple[str, ...] = ("owner_concentration",)
    min_households_for_scoring: int = Field(ge=0)
    tiers: dict[str, float]
    unscored_tier: str = "U"
    rounding_decimals: int = Field(ge=0, le=6)

    @model_validator(mode="after")
    def _consistent(self) -> ScoringRules:
        unknown = [c for c in self.required_components if c not in COMPONENT_NAMES]
        if unknown:
            raise ValueError(f"unknown required_components: {unknown}")
        if not self.tiers:
            raise ValueError("scoring.tiers must define at least one tier")
        thresholds = list(self.tiers.values())
        if any(a <= b for a, b in zip(thresholds, thresholds[1:], strict=False)):
            raise ValueError("scoring.tiers thresholds must be strictly descending in file order")
        if thresholds[-1] > 0:
            raise ValueError("the lowest tier threshold must be <= 0 so every score gets a tier")
        if self.unscored_tier in self.tiers:
            raise ValueError("unscored_tier must not also be a scored tier")
        return self

    def tier_for(self, score: float | None) -> str:
        """Return the tier letter for a score; None maps to the unscored tier."""
        if score is None:
            return self.unscored_tier
        for tier, threshold in self.tiers.items():
            if score >= threshold:
                return tier
        return self.unscored_tier

    @property
    def tier_order(self) -> tuple[str, ...]:
        """Tiers from best to worst, excluding the unscored tier."""
        return tuple(self.tiers.keys())


# --------------------------------------------------------------------------------------
# Opportunity Units
# --------------------------------------------------------------------------------------


class HousingAgeFactor(StrictModel):
    floor: float = Field(ge=0, le=1)
    share_at_full_credit: float = Field(gt=0, le=1)


class PurchasingPowerFactor(StrictModel):
    floor: float = Field(ge=0, le=1)
    income_at_floor: float = Field(ge=0)
    income_at_full_credit: float = Field(gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> PurchasingPowerFactor:
        if self.income_at_full_credit <= self.income_at_floor:
            raise ValueError("income_at_full_credit must exceed income_at_floor")
        return self


class OpportunityUnitRules(StrictModel):
    age_45_plus_floor: float = Field(ge=0, le=1)
    housing_age_factor: HousingAgeFactor
    purchasing_power_factor: PurchasingPowerFactor
    missing_factor_policy: Literal["neutral", "floor"] = "neutral"
    rounding_decimals: int = Field(ge=0, le=6)


# --------------------------------------------------------------------------------------
# Territory sizes
# --------------------------------------------------------------------------------------


class SizeBand(StrictModel):
    target_min: float = Field(ge=0)
    target_max: float = Field(gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> SizeBand:
        if self.target_min >= self.target_max:
            raise ValueError("target_min must be below target_max")
        return self


class SizeBands(StrictModel):
    small: SizeBand
    standard: SizeBand
    large: SizeBand

    def get(self, size_class: str) -> SizeBand:
        key = size_class.lower()
        if key not in ("small", "standard", "large"):
            raise KeyError(size_class)
        return getattr(self, key)

    @model_validator(mode="after")
    def _ascending(self) -> SizeBands:
        if self.small.target_max > self.standard.target_min:
            raise ValueError("small and standard bands overlap")
        if self.standard.target_max > self.large.target_min:
            raise ValueError("standard and large bands overlap")
        return self


class TerritorySizeRules(StrictModel):
    bands: SizeBands
    default_size_class: SizeClassName = "standard"
    minimum_viable_units: float = Field(ge=0)
    absolute_max_units: float = Field(gt=0)
    max_zctas_per_territory: int = Field(gt=0)
    target_tolerance: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _consistent(self) -> TerritorySizeRules:
        if self.minimum_viable_units > self.bands.small.target_min:
            raise ValueError("minimum_viable_units cannot exceed the small band's target_min")
        if self.absolute_max_units < self.bands.large.target_max:
            raise ValueError("absolute_max_units must be at least the large band's target_max")
        return self


# --------------------------------------------------------------------------------------
# Serviceability, generator, registry
# --------------------------------------------------------------------------------------


class ServiceabilityRules(StrictModel):
    default_service_radius_miles: float = Field(gt=0)
    max_service_radius_miles: float = Field(gt=0)
    max_zcta_land_area_sq_miles: float = Field(gt=0)
    allow_cross_state: bool = True

    @model_validator(mode="after")
    def _radius(self) -> ServiceabilityRules:
        if self.default_service_radius_miles > self.max_service_radius_miles:
            raise ValueError("default_service_radius_miles cannot exceed max_service_radius_miles")
        return self


class GeneratorRules(StrictModel):
    distance_penalty_points_per_mile: float = Field(ge=0)
    min_tier_for_auto_selection: str
    tie_breakers: tuple[TieBreaker, ...]
    replacement_suggestions: int = Field(ge=0)

    @model_validator(mode="after")
    def _total_order(self) -> GeneratorRules:
        if not self.tie_breakers or self.tie_breakers[-1] != "zcta_asc":
            raise ValueError("tie_breakers must end with zcta_asc so ordering is total")
        if len(set(self.tie_breakers)) != len(self.tie_breakers):
            raise ValueError("tie_breakers must not repeat")
        return self


class RegistryRules(StrictModel):
    blocking_statuses: tuple[AssignmentStatus, ...]
    reservation_days: int = Field(gt=0)
    reservation_extension_days: int = Field(ge=0)
    max_reservation_extensions: int = Field(ge=0)
    release_notice_days: int = Field(ge=0)
    buffer_zone_required: bool = False
    approval_required_for: tuple[TerritoryStatus, ...]
    allowed_exceptions: tuple[str, ...]

    @model_validator(mode="after")
    def _consistent(self) -> RegistryRules:
        if AssignmentStatus.ACTIVE_PROTECTED not in self.blocking_statuses:
            raise ValueError("ACTIVE_PROTECTED must always be a blocking status")
        if AssignmentStatus.RELEASED in self.blocking_statuses:
            raise ValueError("RELEASED can never block")
        if TerritoryStatus.ACTIVE_PROTECTED not in self.approval_required_for:
            raise ValueError("ACTIVE_PROTECTED must always require approval")
        return self


# --------------------------------------------------------------------------------------
# Root
# --------------------------------------------------------------------------------------


class BusinessRules(StrictModel):
    version: str
    effective_date: date
    notes: str | None = None
    scoring: ScoringRules
    opportunity_units: OpportunityUnitRules
    territory_sizes: TerritorySizeRules
    serviceability: ServiceabilityRules
    generator: GeneratorRules
    registry: RegistryRules

    @model_validator(mode="after")
    def _cross_section(self) -> BusinessRules:
        tier = self.generator.min_tier_for_auto_selection
        if tier not in self.scoring.tiers:
            raise ValueError(
                f"generator.min_tier_for_auto_selection {tier!r} is not one of the scored tiers"
            )
        return self


def load_business_rules(path: Path | str | None = None) -> BusinessRules:
    """Load and validate the rules file. Raises pydantic.ValidationError on bad configuration."""
    from app.config.settings import get_settings  # local import to avoid a cycle at import time

    rules_path = Path(path) if path is not None else get_settings().business_rules_path
    with open(rules_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{rules_path} did not contain a mapping")
    return BusinessRules.model_validate(data)


@lru_cache
def get_business_rules() -> BusinessRules:
    """Process-wide cached rules from the configured path."""
    return load_business_rules()
