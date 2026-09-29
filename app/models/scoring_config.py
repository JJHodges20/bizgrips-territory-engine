"""Snapshot of each business-rules version used for scoring (DATA_DICTIONARY.md section 5)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.config.business_rules import BusinessRules
from app.models.base import Base, utcnow


class ScoringConfig(Base):
    __tablename__ = "scoring_configs"

    config_version: Mapped[str] = mapped_column(String(32), primary_key=True)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)

    owner_household_weight: Mapped[float] = mapped_column(Float, nullable=False)
    age_45_plus_weight: Mapped[float] = mapped_column(Float, nullable=False)
    housing_age_weight: Mapped[float] = mapped_column(Float, nullable=False)
    income_weight: Mapped[float] = mapped_column(Float, nullable=False)
    serviceability_weight: Mapped[float] = mapped_column(Float, nullable=False)

    small_target_min: Mapped[float] = mapped_column(Float, nullable=False)
    small_target_max: Mapped[float] = mapped_column(Float, nullable=False)
    standard_target_min: Mapped[float] = mapped_column(Float, nullable=False)
    standard_target_max: Mapped[float] = mapped_column(Float, nullable=False)
    large_target_min: Mapped[float] = mapped_column(Float, nullable=False)
    large_target_max: Mapped[float] = mapped_column(Float, nullable=False)

    full_config_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    @classmethod
    def from_rules(cls, rules: BusinessRules) -> ScoringConfig:
        w = rules.scoring.weights
        b = rules.territory_sizes.bands
        return cls(
            config_version=rules.version,
            effective_date=rules.effective_date,
            owner_household_weight=w.owner_concentration,
            age_45_plus_weight=w.owner_age_45_plus,
            housing_age_weight=w.housing_age,
            income_weight=w.purchasing_power,
            serviceability_weight=w.serviceability,
            small_target_min=b.small.target_min,
            small_target_max=b.small.target_max,
            standard_target_min=b.standard.target_min,
            standard_target_max=b.standard.target_max,
            large_target_min=b.large.target_min,
            large_target_max=b.large.target_max,
            full_config_json=rules.model_dump(mode="json"),
        )
