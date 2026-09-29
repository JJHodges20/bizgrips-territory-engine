"""ZIP availability, expiry flags and the due-release sweep (Milestone 4)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Path, Query

from app.api.deps import SessionDep
from app.api.territories import make_service
from app.schemas.registry import RegistryFlagsResponse, SweepResponse, ZipAvailabilityResult

router = APIRouter(tags=["registry"])
AS_OF = Query(None, description="registry date; defaults to today (UTC)")


@router.get("/zips/{zip_code}/availability", response_model=ZipAvailabilityResult)
def zip_availability(
    session: SessionDep,
    zip_code: str = Path(pattern=r"^\d{5}$"),
    client_id: str | None = Query(None, description="the prospect; own ZIPs are not conflicts"),
    as_of: date | None = AS_OF,
) -> ZipAvailabilityResult:
    """AVAILABLE, or the blocking assignment with its client and expiry/release flags."""
    return make_service(session, as_of).availability([zip_code], client_id=client_id)[0]


@router.get("/registry/flags", response_model=RegistryFlagsResponse)
def registry_flags(session: SessionDep, as_of: date | None = AS_OF) -> RegistryFlagsResponse:
    """Expired reservations (still blocking, human action needed) and releases due."""
    return make_service(session, as_of).flags()


@router.post("/registry/sweep", response_model=SweepResponse)
def registry_sweep(session: SessionDep, as_of: date | None = AS_OF) -> SweepResponse:
    """Complete PENDING_RELEASE territories whose release date has passed. Reservations are
    never touched: expired ones are only listed."""
    result = make_service(session, as_of).sweep_due_releases()
    session.commit()
    return result
