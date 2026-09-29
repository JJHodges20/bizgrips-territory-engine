"""Response models for the read API. Field names mirror DATA_DICTIONARY.md / app.models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.market import ZctaRecord
from app.schemas.scoring import ZctaScore

# Columns whose NULL means "missing source data" (postal_zip / primary_city NULL are meaningful).
MARKET_DATA_FIELDS: tuple[str, ...] = (
    "state",
    "latitude",
    "longitude",
    "land_area_sq_miles",
    "total_population",
    "total_households",
    "owner_occupied_households",
    "renter_occupied_households",
    "owner_households_age_45_plus",
    "owner_households_age_55_plus",
    "owner_households_age_65_plus",
    "total_housing_units",
    "homes_built_before_2000",
    "homes_built_before_1990",
    "homes_built_before_1980",
    "median_household_income",
    "median_home_value",
)


class ZctaShares(BaseModel):
    """Derived shares (SCORING_SPEC section 2); None when a component is missing or zero."""

    owner_occupancy_share: float | None = None
    owner_45_plus_share: float | None = None
    pre_2000_share: float | None = None


class ZctaListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    zcta: str
    postal_zip: str | None = None
    primary_city: str | None = None
    state: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    land_area_sq_miles: float | None = None
    total_households: int | None = None
    owner_occupied_households: int | None = None
    owner_households_age_45_plus: int | None = None
    median_household_income: int | None = None
    households_per_sq_mile: float | None = None
    opportunity_score: float | None = None
    market_tier: str | None = None
    opportunity_units: float | None = None
    unserviceable_land_area: bool = False


class ZctaResponse(ZctaListItem):
    """One ZCTA: every stored column plus derived shares and explicit missing-data list."""

    state_fips: str | None = None
    water_area_sq_miles: float | None = None
    total_population: int | None = None
    renter_occupied_households: int | None = None
    owner_occupancy_percent: float | None = None
    owner_households_age_55_plus: int | None = None
    owner_households_age_65_plus: int | None = None
    total_housing_units: int | None = None
    homes_built_before_2000: int | None = None
    homes_built_before_1990: int | None = None
    homes_built_before_1980: int | None = None
    median_home_value: int | None = None
    score_config_version: str | None = None
    scored_at: datetime | None = None
    demographics_import_id: int | None = None
    geography_import_id: int | None = None
    source_release: str | None = None
    last_updated: datetime | None = None
    geometry_geojson: str | None = Field(
        default=None, description="only with include_geometry=true"
    )
    shares: ZctaShares = Field(default_factory=ZctaShares)
    missing_fields: list[str] = Field(
        default_factory=list, description="stored columns that are NULL in the source data"
    )

    @classmethod
    def from_row(cls, row: Any, *, include_geometry: bool = False) -> ZctaResponse:
        record = ZctaRecord.from_row(row)
        response = cls.model_validate(row)
        response.shares = ZctaShares(
            owner_occupancy_share=_round(record.owner_occupancy_share),
            owner_45_plus_share=_round(record.owner_45_plus_share),
            pre_2000_share=_round(record.pre_2000_share),
        )
        response.missing_fields = [
            name for name in MARKET_DATA_FIELDS if getattr(row, name, None) is None
        ]
        if not include_geometry:
            response.geometry_geojson = None
        return response


def _round(value: float | None, decimals: int = 4) -> float | None:
    return None if value is None else round(value, decimals)


class ZctaListResponse(BaseModel):
    items: list[ZctaListItem]
    total: int
    limit: int
    offset: int
    filters: dict[str, str | None]


class NeighborItem(ZctaListItem):
    shared_boundary_length_m: float | None = None


class NeighborsResponse(BaseModel):
    zcta: str
    count: int
    neighbors: list[NeighborItem]


class ImportRecord(BaseModel):
    """One row of data_source_imports (DATA_DICTIONARY section 6)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    dataset: str
    vintage: str
    release_label: str | None = None
    source_url: str | None = None
    variables_json: dict[str, Any] | None = None
    record_count: int | None = None
    checksum: str | None = None
    imported_at: datetime
    notes: str | None = None


class ImportsResponse(BaseModel):
    items: list[ImportRecord]
    total: int
    limit: int
    offset: int


class FieldProvenanceRecord(BaseModel):
    """One row of data_field_provenance (DATA_DICTIONARY section 7)."""

    model_config = ConfigDict(from_attributes=True)

    field_name: str
    dataset: str
    vintage: str
    table_id: str | None = None
    variables_json: list[str] | None = None
    import_id: int | None = None
    updated_at: datetime


class FieldProvenanceResponse(BaseModel):
    items: list[FieldProvenanceRecord]


class CachedScore(BaseModel):
    """What scripts/score_all.py last cached on the row (may lag the live computation)."""

    opportunity_score: float | None = None
    market_tier: str | None = None
    opportunity_units: float | None = None
    score_config_version: str | None = None
    scored_at: datetime | None = None


class ZctaScoreResponse(ZctaScore):
    """Live score from the current rules plus the cached values for comparison."""

    cached: CachedScore
    disclaimer: str = (
        "Comparative index from public Census data for sales intelligence; not a prediction "
        "or guarantee of marketing performance."
    )
