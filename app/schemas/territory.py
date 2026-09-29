"""Territory generator and conflict checker schemas (TERRITORY_ALGORITHM.md sections 1-2)."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.enums import AssignmentStatus, TerritorySizeClass

ProposalStatus = Literal["PROPOSED", "FAILED"]
TargetStatus = Literal["BELOW_MINIMUM_VIABLE", "BELOW_TARGET", "WITHIN_TARGET", "ABOVE_TARGET"]
ZipReason = Literal["STARTING_ZIP", "REQUESTED", "SELECTED"]

# Exclusion reasons, in the order the generator tests them.
EXCLUSION_REASONS = (
    "NO_MARKET_DATA",
    "BLOCKED_RESERVED",
    "BLOCKED_ACTIVE_PROTECTED",
    "BLOCKED_PENDING_RELEASE",
    "UNSCORED",
    "BELOW_MIN_TIER",
    "UNSERVICEABLE_LAND_AREA",
    "OUTSIDE_SERVICE_RADIUS",
    "CROSS_STATE_DISALLOWED",
    "NOT_CONTIGUOUS",
    "WOULD_EXCEED_BAND",
)


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TerritoryRequest(StrictSchema):
    client_name: str = Field(min_length=1, max_length=200)
    client_id: str | None = Field(default=None, max_length=64)
    starting_zip: str = Field(pattern=r"^\d{5}$")
    size_class: TerritorySizeClass | None = None
    requested_zips: list[str] = Field(default_factory=list)
    max_service_distance_miles: float | None = Field(default=None, gt=0)
    allow_cross_state: bool | None = None


class ProposalZip(StrictSchema):
    zcta: str
    order: int
    reason: ZipReason
    explanation: str
    score: float | None = None
    tier: str
    opportunity_units: float | None = None
    miles_from_start: float
    state: str | None = None


class ExcludedZip(StrictSchema):
    zcta: str
    reason: str
    detail: str


class ProposalAggregates(StrictSchema):
    zcta_count: int
    total_population: int
    total_households: int
    owner_occupied_households: int
    owner_households_age_45_plus: int
    owner_households_age_55_plus: int
    owner_households_age_65_plus: int
    total_housing_units: int
    homes_built_before_2000: int
    homes_built_before_1990: int
    homes_built_before_1980: int
    median_household_income: float | None = None  # household-weighted mean of ZCTA medians
    land_area_sq_miles: float
    opportunity_units: float
    opportunity_score: float | None = None
    market_tier: str


class TargetInfo(StrictSchema):
    size_class: TerritorySizeClass
    band_min: float
    band_max: float
    tolerance: float
    minimum_viable: float
    status: TargetStatus


class Suggestion(StrictSchema):
    for_zcta: str
    zcta: str
    miles: float
    score: float | None = None
    tier: str


class ProposalFailure(StrictSchema):
    code: str
    message: str
    blocking_territory_id: str | None = None
    blocking_status: AssignmentStatus | None = None
    suggestions: list[Suggestion] = Field(default_factory=list)


class ConflictEntry(StrictSchema):
    zcta: str
    territory_id: str
    client_business_name: str
    status: AssignmentStatus
    expires_at: date | None = None
    expired: bool = False
    release_date: date | None = None
    contract_end_date: date | None = None


class ConflictResult(StrictSchema):
    """Outcome of checking a ZIP list against the registry (algorithm section 2)."""

    requested_count: int = 0
    available: list[str] = Field(default_factory=list)
    reserved: list[ConflictEntry] = Field(default_factory=list)
    protected: list[ConflictEntry] = Field(default_factory=list)
    pending_release: list[ConflictEntry] = Field(default_factory=list)
    own: list[str] = Field(default_factory=list)
    unknown: list[str] = Field(default_factory=list)
    conflict_count: int = 0
    contiguous: bool = True
    components: list[list[str]] = Field(default_factory=list)
    flags: dict[str, str] = Field(default_factory=dict)  # zcta -> RESERVATION_EXPIRED
    suggestions: list[Suggestion] = Field(default_factory=list)


class ConflictCheckRequest(StrictSchema):
    zips: list[str] = Field(min_length=1, max_length=200)
    client_id: str | None = Field(default=None, max_length=64)

    @field_validator("zips")
    @classmethod
    def _five_digits(cls, zips: list[str]) -> list[str]:
        bad = [z for z in zips if len(z) != 5 or not z.isdigit()]
        if bad:
            raise ValueError(f"not 5-digit ZCTA codes: {bad}")
        return zips


class ConflictCheckResponse(ConflictResult):
    as_of: date
    client_id: str | None = None
    checked: list[str] = Field(default_factory=list)
    disclaimer: str = (
        "Availability reflects the registry at as_of; only a human-approved registry action "
        "changes ZIP state."
    )


class TerritoryProposal(StrictSchema):
    status: ProposalStatus
    failure: ProposalFailure | None = None
    client_name: str
    client_id: str | None = None
    starting_zip: str
    size_class: TerritorySizeClass
    rules_version: str
    as_of: date
    zips: list[ProposalZip] = Field(default_factory=list)
    excluded: list[ExcludedZip] = Field(default_factory=list)
    aggregates: ProposalAggregates | None = None
    target: TargetInfo | None = None
    conflicts: ConflictResult = Field(default_factory=ConflictResult)
    flags: list[str] = Field(default_factory=list)
    explanation: list[str] = Field(default_factory=list)
    approval_required: bool = True
    territory_id: str | None = None  # set when the proposal was persisted as PROPOSED
    disclaimer: str = (
        "Recommendation from public Census data and configured rules; a named person must "
        "approve it. Scores and Opportunity Units are comparative indices, not forecasts."
    )

    @property
    def zip_codes(self) -> list[str]:
        return [z.zcta for z in self.zips]

    def fingerprint(self) -> str:
        """sha256 of the canonical JSON (everything but the persisted id)."""
        payload = self.model_dump(mode="json", exclude={"territory_id"})
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---- custom groupings (Milestone 8) -----------------------------------------------------------


class GroupEvaluateRequest(StrictSchema):
    zips: list[str] = Field(min_length=1, max_length=200)
    client_id: str | None = Field(default=None, max_length=64)
    size_class: TerritorySizeClass | None = None


class GroupZip(StrictSchema):
    zcta: str
    primary_city: str | None = None
    state: str | None = None
    tier: str
    score: float | None = None
    opportunity_units: float | None = None
    owner_occupied_households: int | None = None
    availability: str
    blocking_territory_id: str | None = None
    blocking_client: str | None = None
    unserviceable: bool = False


class GroupEvaluation(StrictSchema):
    """A hand-picked ZIP grouping scored like a territory (never written to the registry)."""

    zips: list[str]
    unknown_zips: list[str] = Field(default_factory=list)
    size_class: TerritorySizeClass
    as_of: date
    rules_version: str
    aggregates: ProposalAggregates | None = None
    target: TargetInfo | None = None
    contiguous: bool
    components: list[list[str]] = Field(default_factory=list)
    conflicts: ConflictResult
    per_zip: list[GroupZip] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    can_save: bool
    approval_required: bool = True
    disclaimer: str = (
        "Comparative indices from public Census data and configured rules; not a prediction "
        "or guarantee of marketing performance. A named person must approve any territory."
    )
