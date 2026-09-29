"""ZCTA market data and the rook-adjacency graph (DATA_DICTIONARY.md sections 1-2)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ZctaMarket(Base):
    __tablename__ = "zcta_markets"

    # Geography
    zcta: Mapped[str] = mapped_column(String(5), primary_key=True)
    postal_zip: Mapped[str | None] = mapped_column(String(5))
    primary_city: Mapped[str | None] = mapped_column(String(120))
    state: Mapped[str | None] = mapped_column(String(2), index=True)
    state_fips: Mapped[str | None] = mapped_column(String(2))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    land_area_sq_miles: Mapped[float | None] = mapped_column(Float)
    water_area_sq_miles: Mapped[float | None] = mapped_column(Float)
    geometry_geojson: Mapped[str | None] = mapped_column(Text)
    # WGS84 bounding box of the boundary (Milestone 8 map viewport queries)
    bbox_min_lon: Mapped[float | None] = mapped_column(Float)
    bbox_min_lat: Mapped[float | None] = mapped_column(Float)
    bbox_max_lon: Mapped[float | None] = mapped_column(Float)
    bbox_max_lat: Mapped[float | None] = mapped_column(Float)

    # Households
    total_population: Mapped[int | None] = mapped_column(Integer)
    total_households: Mapped[int | None] = mapped_column(Integer)
    owner_occupied_households: Mapped[int | None] = mapped_column(Integer)
    renter_occupied_households: Mapped[int | None] = mapped_column(Integer)
    owner_occupancy_percent: Mapped[float | None] = mapped_column(Float)

    # Homeowner age
    owner_households_age_45_plus: Mapped[int | None] = mapped_column(Integer)
    owner_households_age_55_plus: Mapped[int | None] = mapped_column(Integer)
    owner_households_age_65_plus: Mapped[int | None] = mapped_column(Integer)

    # Housing stock
    total_housing_units: Mapped[int | None] = mapped_column(Integer)
    homes_built_before_2000: Mapped[int | None] = mapped_column(Integer)
    homes_built_before_1990: Mapped[int | None] = mapped_column(Integer)
    homes_built_before_1980: Mapped[int | None] = mapped_column(Integer)

    # Economics
    median_household_income: Mapped[int | None] = mapped_column(Integer)
    median_home_value: Mapped[int | None] = mapped_column(Integer)

    # Derived + scoring cache (recomputed by scripts/score_all.py in Milestone 3)
    households_per_sq_mile: Mapped[float | None] = mapped_column(Float)
    opportunity_score: Mapped[float | None] = mapped_column(Float)
    market_tier: Mapped[str | None] = mapped_column(String(1), index=True)
    opportunity_units: Mapped[float | None] = mapped_column(Float)
    score_config_version: Mapped[str | None] = mapped_column(String(32))
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unserviceable_land_area: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )

    # Provenance
    demographics_import_id: Mapped[int | None] = mapped_column(ForeignKey("data_source_imports.id"))
    geography_import_id: Mapped[int | None] = mapped_column(ForeignKey("data_source_imports.id"))
    source_release: Mapped[str | None] = mapped_column(String(64))
    last_updated: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_zcta_markets_city_state", "primary_city", "state"),
        Index("ix_zcta_markets_bbox", "bbox_min_lat", "bbox_max_lat", "bbox_min_lon"),
        CheckConstraint("length(zcta) = 5", name="zcta_five_digits"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ZctaMarket {self.zcta} {self.primary_city}, {self.state}>"


class ZctaAdjacency(Base):
    """One row per unordered adjacent pair, stored with zcta_a < zcta_b."""

    __tablename__ = "zcta_adjacency"

    zcta_a: Mapped[str] = mapped_column(
        String(5), ForeignKey("zcta_markets.zcta"), primary_key=True
    )
    zcta_b: Mapped[str] = mapped_column(
        String(5), ForeignKey("zcta_markets.zcta"), primary_key=True
    )
    shared_boundary_length_m: Mapped[float | None] = mapped_column(Float)
    geography_import_id: Mapped[int | None] = mapped_column(ForeignKey("data_source_imports.id"))

    __table_args__ = (
        CheckConstraint("zcta_a < zcta_b", name="ordered_pair"),
        Index("ix_zcta_adjacency_zcta_b", "zcta_b"),
    )

    @staticmethod
    def ordered(a: str, b: str) -> tuple[str, str]:
        return (a, b) if a < b else (b, a)
