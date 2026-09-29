"""Territory registry tables (DATA_DICTIONARY.md sections 3-4).

`territory_zip_assignments.uq_active_zip` is a partial unique index: a ZIP may appear at most
once with a blocking status, so the database itself refuses to protect one ZIP for two clients.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.enums import (
    BLOCKING_ASSIGNMENT_STATUSES,
    AssignmentStatus,
    TerritorySizeClass,
    TerritoryStatus,
)
from app.models.base import Base, TimestampMixin


def _sql_in(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


BLOCKING_STATUS_SQL = _sql_in(tuple(s.value for s in BLOCKING_ASSIGNMENT_STATUSES))


class Territory(TimestampMixin, Base):
    __tablename__ = "territories"

    territory_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    client_business_name: Mapped[str] = mapped_column(String(200), nullable=False)
    starting_zip: Mapped[str] = mapped_column(String(5), nullable=False)
    territory_size_class: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    approved_by: Mapped[str | None] = mapped_column(String(120))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reservation_date: Mapped[date | None] = mapped_column(Date)
    reservation_expires_at: Mapped[date | None] = mapped_column(Date)
    reservation_extensions: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    contract_start_date: Mapped[date | None] = mapped_column(Date)
    contract_end_date: Mapped[date | None] = mapped_column(Date)
    release_date: Mapped[date | None] = mapped_column(Date)

    exceptions_json: Mapped[list | None] = mapped_column(JSON)
    generation_snapshot_json: Mapped[dict | None] = mapped_column(JSON)
    notes: Mapped[str | None] = mapped_column(Text)

    assignments: Mapped[list[TerritoryZipAssignment]] = relationship(
        back_populates="territory",
        cascade="all, delete-orphan",
        order_by="TerritoryZipAssignment.zip",
    )

    __table_args__ = (
        CheckConstraint(
            f"status IN {_sql_in(tuple(s.value for s in TerritoryStatus))}", name="status_valid"
        ),
        CheckConstraint(
            f"territory_size_class IN {_sql_in(tuple(s.value for s in TerritorySizeClass))}",
            name="size_class_valid",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Territory {self.territory_id} {self.client_business_name} {self.status}>"


class TerritoryZipAssignment(Base):
    __tablename__ = "territory_zip_assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    territory_id: Mapped[str] = mapped_column(
        ForeignKey("territories.territory_id"), nullable=False, index=True
    )
    client_id: Mapped[str] = mapped_column(String(64), nullable=False)
    zip: Mapped[str] = mapped_column(String(5), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    date_assigned: Mapped[date] = mapped_column(Date, nullable=False)
    date_released: Mapped[date | None] = mapped_column(Date)

    territory: Mapped[Territory] = relationship(back_populates="assignments")

    __table_args__ = (
        CheckConstraint(
            f"status IN {_sql_in(tuple(s.value for s in AssignmentStatus))}", name="status_valid"
        ),
        Index(
            "uq_active_zip",
            "zip",
            unique=True,
            sqlite_where=text(f"status IN {BLOCKING_STATUS_SQL}"),
            postgresql_where=text(f"status IN {BLOCKING_STATUS_SQL}"),
        ),
    )

    @property
    def is_blocking(self) -> bool:
        return self.status in {s.value for s in BLOCKING_ASSIGNMENT_STATUSES}
