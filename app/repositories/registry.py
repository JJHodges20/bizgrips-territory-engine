"""Registry persistence: territories, assignments, the blocking-ZIP snapshot, plan application."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.enums import BLOCKING_ASSIGNMENT_STATUSES, AssignmentStatus
from app.models import Territory, TerritoryZipAssignment, ZctaMarket
from app.schemas.registry import (
    AssignmentRecord,
    BlockingInfo,
    ExceptionRecord,
    RegistrySnapshot,
    TerritoryRecord,
    TransitionPlan,
)

BLOCKING = tuple(s.value for s in BLOCKING_ASSIGNMENT_STATUSES)


def to_record(row: Territory) -> TerritoryRecord:
    return TerritoryRecord(
        territory_id=row.territory_id,
        client_id=row.client_id,
        client_business_name=row.client_business_name,
        starting_zip=row.starting_zip,
        territory_size_class=row.territory_size_class,
        status=row.status,
        approved_by=row.approved_by,
        approved_at=row.approved_at,
        reservation_date=row.reservation_date,
        reservation_expires_at=row.reservation_expires_at,
        reservation_extensions=row.reservation_extensions or 0,
        contract_start_date=row.contract_start_date,
        contract_end_date=row.contract_end_date,
        release_date=row.release_date,
        exceptions=[ExceptionRecord.model_validate(e) for e in (row.exceptions_json or [])],
        generation_snapshot=row.generation_snapshot_json,
        notes=row.notes,
        assignments=[AssignmentRecord.model_validate(a) for a in row.assignments],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def get_territory_row(session: Session, territory_id: str) -> Territory | None:
    return session.get(Territory, territory_id, options=[selectinload(Territory.assignments)])


def list_territory_rows(
    session: Session, *, status: str | None = None, client_id: str | None = None
) -> list[Territory]:
    stmt = select(Territory).options(selectinload(Territory.assignments))
    if status:
        stmt = stmt.where(Territory.status == status)
    if client_id:
        stmt = stmt.where(Territory.client_id == client_id)
    return list(session.scalars(stmt.order_by(Territory.territory_id)))


def last_territory_id(session: Session) -> str | None:
    return session.scalar(select(func.max(Territory.territory_id)))


def known_zctas(session: Session, zips: list[str]) -> set[str]:
    if not zips:
        return set()
    return set(session.scalars(select(ZctaMarket.zcta).where(ZctaMarket.zcta.in_(zips))))


def load_snapshot(session: Session, as_of: date, zips: list[str] | None = None) -> RegistrySnapshot:
    """Blocking assignments (joined with their territories) keyed by ZIP."""
    stmt = (
        select(TerritoryZipAssignment, Territory)
        .join(Territory, Territory.territory_id == TerritoryZipAssignment.territory_id)
        .where(TerritoryZipAssignment.status.in_(BLOCKING))
    )
    if zips is not None:
        stmt = stmt.where(TerritoryZipAssignment.zip.in_(zips))
    blocking: dict[str, BlockingInfo] = {}
    for assignment, territory in session.execute(stmt):
        status = AssignmentStatus(assignment.status)
        expired = (
            status == AssignmentStatus.RESERVED
            and territory.reservation_expires_at is not None
            and territory.reservation_expires_at < as_of
        )
        blocking[assignment.zip] = BlockingInfo(
            zip=assignment.zip,
            territory_id=territory.territory_id,
            client_id=territory.client_id,
            client_business_name=territory.client_business_name,
            status=status,
            reservation_expires_at=territory.reservation_expires_at,
            release_date=territory.release_date,
            contract_end_date=territory.contract_end_date,
            expired=expired,
        )
    return RegistrySnapshot(as_of=as_of, blocking=blocking)


def create_territory_row(session: Session, fields: dict[str, Any]) -> Territory:
    row = Territory(**fields)
    session.add(row)
    session.flush()
    return row


def apply_plan(session: Session, row: Territory, plan: TransitionPlan, as_of: date) -> Territory:
    """Persist a validated transition: fields, status, assignments and the audit note."""
    for name, value in plan.fields.items():
        setattr(row, name, value)
    row.status = plan.new_status.value
    row.notes = f"{row.notes}\n{plan.note}" if row.notes else plan.note
    for zip_code in plan.create_assignments_for:
        row.assignments.append(
            TerritoryZipAssignment(
                territory_id=row.territory_id,
                client_id=row.client_id,
                zip=zip_code,
                status=(plan.assignment_status or AssignmentStatus.RESERVED).value,
                date_assigned=as_of,
            )
        )
    if plan.assignment_status is not None and not plan.create_assignments_for:
        for assignment in row.assignments:
            if assignment.status in BLOCKING:
                assignment.status = plan.assignment_status.value
                if plan.assignment_date_released is not None:
                    assignment.date_released = plan.assignment_date_released
    session.flush()
    return row


def add_exception(session: Session, row: Territory, exception: ExceptionRecord, note: str) -> None:
    row.exceptions_json = [*(row.exceptions_json or []), exception.model_dump()]
    row.notes = f"{row.notes}\n{note}" if row.notes else note
    session.flush()


def rows_with_status(session: Session, status: str) -> list[Territory]:
    return list_territory_rows(session, status=status)
