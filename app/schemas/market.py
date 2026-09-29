"""ZctaRecord: the plain-data view of one ZCTA that domain services operate on.

Every count may be None (missing in the source). Derived shares return None when they cannot
be computed, so callers never see silent zeros.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ZctaRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zcta: str = Field(pattern=r"^\d{5}$")
    postal_zip: str | None = Field(default=None, pattern=r"^\d{5}$")
    primary_city: str | None = None
    state: str | None = Field(default=None, min_length=2, max_length=2)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    land_area_sq_miles: float | None = Field(default=None, ge=0)

    total_population: int | None = Field(default=None, ge=0)
    total_households: int | None = Field(default=None, ge=0)
    owner_occupied_households: int | None = Field(default=None, ge=0)
    renter_occupied_households: int | None = Field(default=None, ge=0)
    owner_households_age_45_plus: int | None = Field(default=None, ge=0)
    owner_households_age_55_plus: int | None = Field(default=None, ge=0)
    owner_households_age_65_plus: int | None = Field(default=None, ge=0)
    total_housing_units: int | None = Field(default=None, ge=0)
    homes_built_before_2000: int | None = Field(default=None, ge=0)
    homes_built_before_1990: int | None = Field(default=None, ge=0)
    homes_built_before_1980: int | None = Field(default=None, ge=0)
    median_household_income: int | None = Field(default=None, ge=0)
    median_home_value: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _internally_consistent(self) -> ZctaRecord:
        checks = (
            ("owner_occupied_households", "total_households"),
            ("renter_occupied_households", "total_households"),
            ("total_households", "total_housing_units"),
            ("owner_households_age_45_plus", "owner_occupied_households"),
            ("owner_households_age_55_plus", "owner_households_age_45_plus"),
            ("owner_households_age_65_plus", "owner_households_age_55_plus"),
            ("homes_built_before_2000", "total_housing_units"),
            ("homes_built_before_1990", "homes_built_before_2000"),
            ("homes_built_before_1980", "homes_built_before_1990"),
        )
        for smaller, larger in checks:
            a, b = getattr(self, smaller), getattr(self, larger)
            if a is not None and b is not None and a > b:
                raise ValueError(f"{self.zcta}: {smaller} ({a}) exceeds {larger} ({b})")
        return self

    # ---- derived metrics (SCORING_SPEC.md section 2) ---------------------------------

    @staticmethod
    def _ratio(numerator: float | None, denominator: float | None) -> float | None:
        if numerator is None or denominator is None or denominator <= 0:
            return None
        return numerator / denominator

    @property
    def owner_occupancy_share(self) -> float | None:
        return self._ratio(self.owner_occupied_households, self.total_households)

    @property
    def owner_45_plus_share(self) -> float | None:
        return self._ratio(self.owner_households_age_45_plus, self.owner_occupied_households)

    @property
    def pre_2000_share(self) -> float | None:
        return self._ratio(self.homes_built_before_2000, self.total_housing_units)

    @property
    def households_per_sq_mile(self) -> float | None:
        return self._ratio(self.total_households, self.land_area_sq_miles)

    def metric(self, name: str) -> float | None:
        """Look up a metric by the name used in business_rules.yaml component ramps."""
        if name == "median_household_income":
            return (
                None
                if self.median_household_income is None
                else float(self.median_household_income)
            )
        if name in (
            "owner_occupancy_share",
            "owner_45_plus_share",
            "pre_2000_share",
            "households_per_sq_mile",
        ):
            return getattr(self, name)
        raise KeyError(name)

    def to_orm_kwargs(self) -> dict[str, Any]:
        """Column values for app.models.ZctaMarket, including derived percentages."""
        data = self.model_dump()
        share = self.owner_occupancy_share
        data["owner_occupancy_percent"] = None if share is None else round(share * 100, 2)
        data["households_per_sq_mile"] = self.households_per_sq_mile
        return data
