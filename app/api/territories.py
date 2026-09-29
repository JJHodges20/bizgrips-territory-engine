"""Territory registry endpoints: proposals, status transitions, exceptions (Milestone 4).

The engine only creates PROPOSED territories; every move to RESERVED or ACTIVE_PROTECTED needs
a named approver. Rule violations surface as JSON errors with a stable ``code``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, Path, Query
from sqlalchemy.orm import Session

from app.api.deps import SessionDep
from app.config import get_business_rules
from app.enums import TerritoryStatus
from app.schemas.registry import (
    ActivateRequest,
    ActorRequest,
    ApprovalRequest,
    ExceptionRequest,
    ExtendRequest,
    PendingReleaseRequest,
    ReleaseRequest,
    TerritoryCreateRequest,
    TerritoryListResponse,
    TerritoryResponse,
)
from app.services.registry import RegistryService

router = APIRouter(prefix="/territories", tags=["registry"])

TERRITORY_ID = Path(pattern=r"^T-\d{6}$", description="territory id, e.g. T-000001")
AS_OF = Query(None, description="registry date for the action; defaults to today (UTC)")


def make_service(session: Session, as_of: date | None) -> RegistryService:
    now = datetime.now(UTC)
    return RegistryService(session, get_business_rules(), as_of=as_of or now.date(), at=now)


def _transition(
    session: Session, as_of: date | None, territory_id: str, action: str, **kwargs: Any
) -> TerritoryResponse:
    service = make_service(session, as_of)
    record = getattr(service, action)(territory_id, **kwargs)
    session.commit()
    return service.response(record)


@router.post("", response_model=TerritoryResponse, status_code=201)
def create_territory(
    session: SessionDep, body: TerritoryCreateRequest, as_of: date | None = AS_OF
) -> TerritoryResponse:
    """Create a PROPOSED territory from an explicit ZIP list (409 if any ZIP is blocked)."""
    service = make_service(session, as_of)
    record = service.create_proposal(
        client_id=body.client_id,
        client_business_name=body.client_business_name,
        starting_zip=body.starting_zip,
        size_class=body.territory_size_class,
        zips=body.zips,
        notes=body.notes,
        snapshot=body.generation_snapshot,
    )
    session.commit()
    return service.response(record)


@router.get("", response_model=TerritoryListResponse)
def list_territories(
    session: SessionDep,
    status: TerritoryStatus | None = None,
    client_id: str | None = Query(None, max_length=64),
    as_of: date | None = AS_OF,
) -> TerritoryListResponse:
    service = make_service(session, as_of)
    items = [service.response(r) for r in service.list(status=status, client_id=client_id)]
    return TerritoryListResponse(items=items, total=len(items))


@router.get("/{territory_id}", response_model=TerritoryResponse)
def get_territory(
    session: SessionDep, territory_id: str = TERRITORY_ID, as_of: date | None = AS_OF
) -> TerritoryResponse:
    service = make_service(session, as_of)
    return service.response(service.get(territory_id))


@router.post("/{territory_id}/reserve", response_model=TerritoryResponse)
def reserve(
    session: SessionDep,
    body: ApprovalRequest,
    territory_id: str = TERRITORY_ID,
    as_of: date | None = AS_OF,
) -> TerritoryResponse:
    """PROPOSED -> RESERVED (30 days). 409 if any ZIP is blocked for another client."""
    return _transition(session, as_of, territory_id, "reserve", approved_by=body.approved_by)


@router.post("/{territory_id}/extend", response_model=TerritoryResponse)
def extend(
    session: SessionDep,
    body: ExtendRequest,
    territory_id: str = TERRITORY_ID,
    as_of: date | None = AS_OF,
) -> TerritoryResponse:
    return _transition(
        session, as_of, territory_id, "extend", approved_by=body.approved_by, reason=body.reason
    )


@router.post("/{territory_id}/activate", response_model=TerritoryResponse)
def activate(
    session: SessionDep,
    body: ActivateRequest,
    territory_id: str = TERRITORY_ID,
    as_of: date | None = AS_OF,
) -> TerritoryResponse:
    """RESERVED -> ACTIVE_PROTECTED on a signed agreement."""
    return _transition(
        session,
        as_of,
        territory_id,
        "activate",
        approved_by=body.approved_by,
        contract_start_date=body.contract_start_date,
        contract_end_date=body.contract_end_date,
    )


@router.post("/{territory_id}/cancel", response_model=TerritoryResponse)
def cancel(
    session: SessionDep,
    body: ActorRequest,
    territory_id: str = TERRITORY_ID,
    as_of: date | None = AS_OF,
) -> TerritoryResponse:
    """PROPOSED or RESERVED -> CANCELLED; reserved ZIPs become available today."""
    return _transition(session, as_of, territory_id, "cancel", actor=body.actor, reason=body.reason)


@router.post("/{territory_id}/pending-release", response_model=TerritoryResponse)
def pending_release(
    session: SessionDep,
    body: PendingReleaseRequest,
    territory_id: str = TERRITORY_ID,
    as_of: date | None = AS_OF,
) -> TerritoryResponse:
    """ACTIVE_PROTECTED -> PENDING_RELEASE with a release date (default 30 days' notice)."""
    return _transition(
        session,
        as_of,
        territory_id,
        "pending_release",
        actor=body.actor,
        reason=body.reason,
        release_date=body.release_date,
    )


@router.post("/{territory_id}/release", response_model=TerritoryResponse)
def release(
    session: SessionDep,
    body: ReleaseRequest,
    territory_id: str = TERRITORY_ID,
    as_of: date | None = AS_OF,
) -> TerritoryResponse:
    """PENDING_RELEASE -> RELEASED on or after the release date."""
    return _transition(session, as_of, territory_id, "release", actor=body.actor)


@router.post("/{territory_id}/exceptions", response_model=TerritoryResponse)
def record_exception(
    session: SessionDep,
    body: ExceptionRequest,
    territory_id: str = TERRITORY_ID,
    as_of: date | None = AS_OF,
) -> TerritoryResponse:
    """Record a manual exception from the allowed list (approver and reason required)."""
    return _transition(
        session,
        as_of,
        territory_id,
        "record_exception",
        exception_type=body.exception_type,
        approved_by=body.approved_by,
        reason=body.reason,
    )
