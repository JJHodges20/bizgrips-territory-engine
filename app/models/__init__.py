"""SQLAlchemy ORM models. Import this package so Base.metadata knows every table."""

from app.models.base import Base, TimestampMixin, utcnow
from app.models.provenance import DataFieldProvenance, DataSourceImport
from app.models.scoring_config import ScoringConfig
from app.models.territory import Territory, TerritoryZipAssignment
from app.models.zcta import ZctaAdjacency, ZctaMarket

__all__ = [
    "Base",
    "DataFieldProvenance",
    "DataSourceImport",
    "ScoringConfig",
    "Territory",
    "TerritoryZipAssignment",
    "TimestampMixin",
    "ZctaAdjacency",
    "ZctaMarket",
    "utcnow",
]
