"""Registry rules on fixture scenarios 2 and 9 plus the full lifecycle (Standard sections 6-11)."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import load_business_rules
from app.enums import AssignmentStatus, TerritorySizeClass, TerritoryStatus, ZipAvailability
from app.fixtures import load_scenario
from app.ingest.seed import seed_scenario
from app.models import TerritoryZipAssignment
from app.schemas.registry import FLAG_RELEASE_DUE, FLAG_RESERVATION_EXPIRED
from app.services.registry import (
    ApprovalRequired,
    ExceptionNotAllowed,
    InvalidTransition,
    RegistryError,
    RegistryService,
    TerritoryNotFound,
    ZipConflict,
    next_territory_id,
)

RULES = load_business_rules()
AS_OF = date(2026, 9, 29)


def service(session: Session, scenario: str, as_of: date = AS_OF) -> RegistryService:
    with session.begin():
        seed_scenario(session, load_scenario(scenario))
    return RegistryService(session, RULES, as_of=as_of)


def propose(svc: RegistryService, zips: list[str], client: str = "C-NEW") -> str:
    record = svc.create_proposal(
        client_id=client,
        client_business_name=f"{client} Baths",
        starting_zip=zips[0],
        size_class=TerritorySizeClass.STANDARD,
        zips=zips,
    )
    return record.territory_id


def test_scenario_2_active_zip_cannot_be_assigned_twice(session: Session) -> None:
    svc = service(session, "start_zip_protected")
    result = svc.availability(["80123"], client_id="C-NEW")[0]
    assert result.availability == ZipAvailability.ACTIVE_PROTECTED and result.is_conflict
    assert result.blocking.territory_id == "T-000001"
    assert result.blocking.client_business_name == "Peak Bath Solutions"
    with pytest.raises(ZipConflict) as excinfo:
        propose(svc, ["80123", "80122"])
    assert excinfo.value.details[0]["zip"] == "80123"
    own = svc.availability(["80123"], client_id="C-ALPHA")[0]
    assert own.own and not own.is_conflict  # the protected client itself is never in conflict
    assert svc.availability(["80122"])[0].availability == ZipAvailability.AVAILABLE
    # Database backstop: a second blocking assignment for 80123 is refused outright.
    session.add(
        TerritoryZipAssignment(
            territory_id="T-000001", client_id="C-ZETA", zip="80123",
            status="RESERVED", date_assigned=AS_OF,
        )
    )  # fmt: skip
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_scenario_9_expired_reservation_blocks_until_released(session: Session) -> None:
    svc = service(session, "reserved_expired")
    blocked = svc.availability(["80127", "80129"], client_id="C-NEW")
    assert all(r.availability == ZipAvailability.RESERVED and r.is_conflict for r in blocked)
    assert all(r.flags == [FLAG_RESERVATION_EXPIRED] for r in blocked)
    assert blocked[0].blocking.client_business_name == "Front Range Showers"
    flags = svc.flags()
    assert [t.territory_id for t in flags.expired_reservations] == ["T-000002"]
    assert flags.releases_due == []
    with pytest.raises(ZipConflict):
        propose(svc, ["80123", "80127"])  # a proposal may not contain another client's ZIPs
    assert svc.sweep_due_releases().expired_reservations == ["T-000002"]  # never auto-released
    released = svc.cancel("T-000002", actor="Sales Manager", reason="prospect went cold")
    assert released.status == TerritoryStatus.CANCELLED
    assert {a.status for a in released.assignments} == {AssignmentStatus.RELEASED}
    assert all(a.date_released == AS_OF for a in released.assignments)
    assert svc.availability(["80127"], client_id="C-NEW")[0].availability == "AVAILABLE"
    proposal = propose(svc, ["80123", "80127"])
    reserved = svc.reserve(proposal, approved_by="Sales Manager")
    assert reserved.status == TerritoryStatus.RESERVED and reserved.zips == ["80123", "80127"]


def test_full_lifecycle_with_audit_trail(session: Session) -> None:
    svc = service(session, "denver_suburban_available")
    tid = propose(svc, ["80123", "80120", "80127"])
    assert tid == "T-000001" and next_territory_id(tid) == "T-000002"
    proposal = svc.get(tid)
    assert proposal.status == TerritoryStatus.PROPOSED and proposal.assignments == []
    with pytest.raises(ApprovalRequired):
        svc.reserve(tid, approved_by="  ")
    reserved = svc.reserve(tid, approved_by="Sales Manager")
    assert reserved.reservation_date == AS_OF
    assert reserved.reservation_expires_at == date(2026, 10, 29)
    assert reserved.approved_by == "Sales Manager" and reserved.approved_at is not None
    assert {a.status for a in reserved.assignments} == {AssignmentStatus.RESERVED}
    with pytest.raises(InvalidTransition):
        svc.reserve(tid, approved_by="Sales Manager")  # already reserved
    extended = svc.extend(tid, approved_by="Sales Manager", reason="contract in legal review")
    assert extended.reservation_expires_at == date(2026, 11, 13)
    assert extended.reservation_extensions == 1
    with pytest.raises(InvalidTransition):
        svc.extend(tid, approved_by="Sales Manager", reason="again")
    with pytest.raises(InvalidTransition):
        svc.release(tid, actor="Sales Manager")  # not pending release
    active = svc.activate(
        tid, approved_by="Owner", contract_start_date=date(2026, 10, 1),
        contract_end_date=date(2027, 9, 30),
    )  # fmt: skip
    assert active.status == TerritoryStatus.ACTIVE_PROTECTED
    assert {a.status for a in active.assignments} == {AssignmentStatus.ACTIVE_PROTECTED}
    assert svc.availability(["80120"], client_id="C-OTHER")[0].is_conflict
    with pytest.raises(InvalidTransition):
        svc.cancel(tid, actor="Owner", reason="cannot cancel an active contract")
    pending = svc.pending_release(tid, actor="Owner", reason="client offboarding")
    assert pending.status == TerritoryStatus.PENDING_RELEASE
    assert pending.release_date == date(2027, 9, 30)  # contract end is later than 30 days
    assert svc.availability(["80120"], client_id="C-OTHER")[0].availability == "PENDING_RELEASE"
    with pytest.raises(InvalidTransition):
        svc.release(tid, actor="Owner")  # release date not reached
    later = RegistryService(session, RULES, as_of=date(2027, 10, 1))
    assert later.availability(["80120"])[0].flags == [FLAG_RELEASE_DUE]
    assert later.flags().releases_due[0].territory_id == tid
    released = later.release(tid, actor="Owner")
    assert released.status == TerritoryStatus.RELEASED
    assert all(a.date_released == date(2027, 9, 30) for a in released.assignments)
    assert later.availability(["80120"])[0].availability == "AVAILABLE"
    events = [line.split("] ")[1].split(" by")[0] for line in released.notes.splitlines()]
    assert events == [
        "PROPOSED", "RESERVED", "RESERVATION_EXTENDED", "ACTIVE_PROTECTED", "PENDING_RELEASE",
        "RELEASED",
    ]  # fmt: skip
    again = propose(later, ["80120"], client="C-RETURNING")
    assert later.reserve(again, approved_by="Sales Manager").status == "RESERVED"


def test_proposal_validation_and_not_found(session: Session) -> None:
    svc = service(session, "denver_suburban_available")
    with pytest.raises(TerritoryNotFound):
        svc.get("T-999999")
    with pytest.raises(RegistryError) as no_market:  # unknown ZCTA
        propose(svc, ["80123", "99999"])
    assert no_market.value.code == "NO_MARKET_DATA" and no_market.value.status_code == 422
    with pytest.raises(RegistryError) as bad_start:
        svc.create_proposal(
            client_id="C-X", client_business_name="X", starting_zip="80120",
            size_class=TerritorySizeClass.SMALL, zips=["80123"],
        )  # fmt: skip
    assert bad_start.value.code == "STARTING_ZIP_NOT_IN_LIST"
    record = svc.create_proposal(
        client_id="C-X", client_business_name="X Baths", starting_zip="80123",
        size_class=TerritorySizeClass.SMALL, zips=["80123", "80123", "80120"],
        notes="manual proposal", snapshot={"source": "test"},
    )  # fmt: skip
    assert record.zips == ["80120", "80123"] and record.generation_snapshot["source"] == "test"
    assert "manual proposal" in record.notes and record.notes.startswith("[2026-09-29] PROPOSED")


def test_reserve_time_conflict_and_exceptions(session: Session) -> None:
    svc = service(session, "denver_suburban_available")
    first = propose(svc, ["80122", "80121"], client="C-FIRST")
    second = propose(svc, ["80122"], client="C-SECOND")  # both proposals may exist
    svc.reserve(second, approved_by="Sales Manager")
    with pytest.raises(ZipConflict) as excinfo:  # state changed since the proposal was made
        svc.reserve(first, approved_by="Sales Manager")
    assert excinfo.value.details[0]["blocking"]["territory_id"] == second
    assert svc.get(first).status == TerritoryStatus.PROPOSED
    with pytest.raises(ExceptionNotAllowed):
        svc.record_exception(
            first, exception_type="OVERRIDE_ACTIVE_PROTECTED", approved_by="Owner", reason="no"
        )
    with pytest.raises(ApprovalRequired):
        svc.record_exception(
            first, exception_type="NON_CONTIGUOUS_ZCTA", approved_by="", reason="island"
        )
    noted = svc.record_exception(
        first, exception_type="NON_CONTIGUOUS_ZCTA", approved_by="Owner", reason="island ZIP"
    )
    assert [e.type for e in noted.exceptions] == ["NON_CONTIGUOUS_ZCTA"]
    assert noted.exceptions[0].approved_by == "Owner" and noted.exceptions[0].at == "2026-09-29"
    assert "EXCEPTION_NON_CONTIGUOUS_ZCTA by Owner" in noted.notes


def test_due_release_completes_automatically_when_a_zip_is_needed(session: Session) -> None:
    svc = service(session, "denver_suburban_available")
    tid = propose(svc, ["80124", "80126"], client="C-OLD")
    svc.reserve(tid, approved_by="Sales Manager")
    svc.activate(tid, approved_by="Owner", contract_start_date=AS_OF)
    svc.pending_release(tid, actor="Owner", reason="offboarding", release_date=date(2026, 10, 15))
    before = RegistryService(session, RULES, as_of=date(2026, 10, 14))
    assert before.availability(["80124"], client_id="C-NEW")[0].is_conflict
    after = RegistryService(session, RULES, as_of=date(2026, 10, 16))
    assert not after.availability(["80124"], client_id="C-NEW")[0].is_conflict
    new_id = propose(after, ["80124"], client="C-NEW")  # completes the due release first
    assert after.get(tid).status == TerritoryStatus.RELEASED
    assert after.reserve(new_id, approved_by="Sales Manager").status == TerritoryStatus.RESERVED
    assert after.sweep_due_releases().released == []  # nothing left to release
