"""Sales-call market checker schemas (TERRITORY_ALGORITHM.md section 3)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.enums import TerritorySizeClass
from app.schemas.territory import ConflictEntry, ConflictResult, Suggestion, TerritoryProposal

MarketAvailability = Literal["AVAILABLE", "PARTIALLY_AVAILABLE", "UNAVAILABLE", "NO_MARKET_DATA"]
QueryMethod = Literal["starting_zip", "requested_zips", "city_state"]

DISCLAIMER = (
    "Figures are public Census estimates and configured comparative indices. They describe the "
    "market; they do not predict or guarantee marketing performance. Client names are for "
    "internal use only. A named person must approve any territory."
)


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MarketQuery(StrictSchema):
    """Exactly one of: a starting ZIP, a pasted ZIP list, or city + state."""

    starting_zip: str | None = Field(default=None, pattern=r"^\d{5}$")
    requested_zips: list[str] = Field(default_factory=list, max_length=200)
    city: str | None = Field(default=None, min_length=1, max_length=120)
    state: str | None = Field(default=None, min_length=2, max_length=2)
    size_class: TerritorySizeClass | None = None
    client_id: str | None = Field(default=None, max_length=64)
    client_name: str = Field(default="Prospect", min_length=1, max_length=200)

    @model_validator(mode="after")
    def _exactly_one_input(self) -> MarketQuery:
        modes = [
            self.starting_zip is not None,
            bool(self.requested_zips),
            bool(self.city or self.state),
        ]
        if sum(modes) != 1:
            raise ValueError("provide exactly one of starting_zip, requested_zips, or city+state")
        if (self.city is None) != (self.state is None):
            raise ValueError("city and state must be given together")
        return self

    @property
    def method(self) -> QueryMethod:
        if self.starting_zip is not None:
            return "starting_zip"
        return "requested_zips" if self.requested_zips else "city_state"


class ResolvedQuery(StrictSchema):
    method: QueryMethod
    starting_zip: str | None = None
    requested_zips: list[str] = Field(default_factory=list)
    unknown_zips: list[str] = Field(default_factory=list)
    city_candidates: list[str] = Field(default_factory=list)
    note: str


class MarketStats(StrictSchema):
    zcta_count: int
    total_households: int
    owner_occupied_households: int
    owner_households_age_45_plus: int
    owner_households_age_55_plus: int
    owner_households_age_65_plus: int
    pre_2000_share: float | None = None
    pre_1990_share: float | None = None
    pre_1980_share: float | None = None
    median_household_income: float | None = None
    opportunity_score: float | None = None
    market_tier: str
    opportunity_units: float
    land_area_sq_miles: float


class MarketCheck(StrictSchema):
    market_availability: MarketAvailability
    query: MarketQuery
    resolution: ResolvedQuery
    as_of: date
    rules_version: str
    suggested_territory: TerritoryProposal | None = None
    available_zips: list[str] = Field(default_factory=list)
    reserved_zips: list[ConflictEntry] = Field(default_factory=list)
    protected_zips: list[ConflictEntry] = Field(default_factory=list)
    pending_release_zips: list[ConflictEntry] = Field(default_factory=list)
    replacement_zips: list[Suggestion] = Field(default_factory=list)
    conflicts: ConflictResult | None = None
    market_stats: MarketStats | None = None
    talking_points: list[str] = Field(default_factory=list)
    approval_required: bool = True
    disclaimer: str = DISCLAIMER
