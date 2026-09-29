"""Territory registry: availability, transition rules and the RegistryService (Milestone 4).

The rules (BIZGRIPS_TERRITORY_STANDARD.md sections 6-11, TERRITORY_ALGORITHM.md section 4) are
pure functions over plain records plus ``BusinessRules`` and an explicit ``as_of`` date, so
they are testable without a database. ``RegistryService`` at the bottom is the only stateful
part: it loads records through the repository, applies the pure rules and persists the plan.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from app.config.business_rules import BusinessRules
from app.enums import AssignmentStatus, TerritorySizeClass, TerritoryStatus, ZipAvailability
from app.schemas.registry import (
    FLAG_RELEASE_DUE,
    FLAG_RESERVATION_EXPIRED,
    BlockingInfo,
    ExceptionRecord,
    RegistryFlagsResponse,
    RegistrySnapshot,
    SweepResponse,
    TerritoryRecord,
    TerritoryResponse,
    TransitionPlan,
    ZipAvailabilityResult,
)

TERRITORY_ID_PREFIX = "T-"
TERRITORY_ID_WIDTH = 6


class RegistryError(Exception):
    """Base for rule violations; the API maps ``status_code`` and ``code`` to a JSON error."""

    status_code = 409

    def __init__(self, code: str, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.code, self.message, self.details = code, message, details


class TerritoryNotFound(RegistryError):
    status_code = 404


class InvalidTransition(RegistryError):
    status_code = 409


class ApprovalRequired(RegistryError):
    status_code = 422


class ZipConflict(RegistryError):
    status_code = 409


class ExceptionNotAllowed(RegistryError):
    status_code = 422


class UnknownZips(RegistryError):
    status_code = 422


# ---- availability (Standard section 6, algorithm section 2) -----------------------------------


def availability_for(
    zip_code: str, snapshot: RegistrySnapshot, *, client_id: str | None = None
) -> ZipAvailabilityResult:
    """ZIP-level state derived from the blocking assignments; never from a cached column."""
    info = snapshot.blocking.get(zip_code)
    if info is None:
        return ZipAvailabilityResult(zip=zip_code, availability=ZipAvailability.AVAILABLE)
    flags: list[str] = []
    if info.status == AssignmentStatus.PENDING_RELEASE and info.release_date is not None:
        if info.release_date <= snapshot.as_of:  # release date reached: treated as released
            return ZipAvailabilityResult(
                zip=zip_code,
                availability=ZipAvailability.AVAILABLE,
                blocking=info,
                flags=[FLAG_RELEASE_DUE],
            )
    if info.status == AssignmentStatus.RESERVED and info.expired:
        flags.append(FLAG_RESERVATION_EXPIRED)
    own = client_id is not None and info.client_id == client_id
    return ZipAvailabilityResult(
        zip=zip_code,
        availability=ZipAvailability(info.status.value),
        own=own,
        is_conflict=not own,
        blocking=info,
        flags=flags,
    )


def conflicts_for(
    zips: list[str], snapshot: RegistrySnapshot, *, client_id: str | None = None
) -> list[ZipAvailabilityResult]:
    results = [availability_for(z, snapshot, client_id=client_id) for z in sorted(set(zips))]
    return [r for r in results if r.is_conflict]


def blocking_info(
    territory: TerritoryRecord, zip_code: str, status: AssignmentStatus, as_of: date
) -> BlockingInfo:
    expired = (
        status == AssignmentStatus.RESERVED
        and territory.reservation_expires_at is not None
        and territory.reservation_expires_at < as_of
    )
    return BlockingInfo(
        zip=zip_code,
        territory_id=territory.territory_id,
        client_id=territory.client_id,
        client_business_name=territory.client_business_name,
        status=status,
        reservation_expires_at=territory.reservation_expires_at,
        release_date=territory.release_date,
        contract_end_date=territory.contract_end_date,
        expired=expired,
    )


# ---- flags, audit trail, identifiers ---------------------------------------------------------


def territory_flags(territory: TerritoryRecord, as_of: date) -> list[str]:
    flags: list[str] = []
    if (
        territory.status == TerritoryStatus.RESERVED
        and territory.reservation_expires_at is not None
        and territory.reservation_expires_at < as_of
    ):
        flags.append(FLAG_RESERVATION_EXPIRED)
    if (
        territory.status == TerritoryStatus.PENDING_RELEASE
        and territory.release_date is not None
        and territory.release_date <= as_of
    ):
        flags.append(FLAG_RELEASE_DUE)
    return flags


def audit_line(as_of: date, actor: str, event: str, detail: str) -> str:
    return f"[{as_of.isoformat()}] {event} by {actor}: {detail}"


def append_note(existing: str | None, line: str) -> str:
    return line if not existing else f"{existing}\n{line}"


def next_territory_id(last_id: str | None) -> str:
    number = int(last_id[len(TERRITORY_ID_PREFIX) :]) + 1 if last_id else 1
    return f"{TERRITORY_ID_PREFIX}{number:0{TERRITORY_ID_WIDTH}d}"


def at_midnight(as_of: date) -> datetime:
    return datetime.combine(as_of, time.min, tzinfo=UTC)


def _require_actor(value: str | None, code: str, what: str) -> str:
    if not value or not value.strip():
        raise ApprovalRequired(code, f"{what} requires a named person")
    return value.strip()


# ---- transitions (algorithm section 4) --------------------------------------------------------


def _expect_status(territory: TerritoryRecord, *allowed: TerritoryStatus, event: str) -> None:
    if territory.status not in allowed:
        raise InvalidTransition(
            "INVALID_TRANSITION",
            f"{event} is not allowed from {territory.status.value} "
            f"(requires {', '.join(s.value for s in allowed)})",
            {"territory_id": territory.territory_id, "status": territory.status.value},
        )


def plan_reserve(
    territory: TerritoryRecord,
    *,
    approved_by: str | None,
    as_of: date,
    rules: BusinessRules,
    at: datetime | None = None,
) -> TransitionPlan:
    """PROPOSED -> RESERVED: approver required; 30-day window; assignments written RESERVED."""
    _expect_status(territory, TerritoryStatus.PROPOSED, event="reserve")
    approver = _require_actor(approved_by, "APPROVAL_REQUIRED", "RESERVED")
    zips = territory.zips
    if not zips:
        raise InvalidTransition("NO_ZIPS", "a territory without ZIPs cannot be reserved")
    expires = as_of + timedelta(days=rules.registry.reservation_days)
    return TransitionPlan(
        event="RESERVED",
        new_status=TerritoryStatus.RESERVED,
        fields={
            "approved_by": approver,
            "approved_at": at or at_midnight(as_of),
            "reservation_date": as_of,
            "reservation_expires_at": expires,
        },
        assignment_status=AssignmentStatus.RESERVED,
        create_assignments_for=zips,
        note=audit_line(as_of, approver, "RESERVED", f"{len(zips)} ZIPs until {expires}"),
    )


def plan_extend(
    territory: TerritoryRecord,
    *,
    approved_by: str | None,
    reason: str,
    as_of: date,
    rules: BusinessRules,
) -> TransitionPlan:
    """RESERVED -> RESERVED with a longer window; at most max_reservation_extensions times."""
    _expect_status(territory, TerritoryStatus.RESERVED, event="extend")
    approver = _require_actor(approved_by, "APPROVAL_REQUIRED", "a reservation extension")
    if not reason.strip():
        raise ApprovalRequired("REASON_REQUIRED", "a reservation extension requires a reason")
    limit = rules.registry.max_reservation_extensions
    if territory.reservation_extensions >= limit:
        raise InvalidTransition(
            "EXTENSION_LIMIT", f"reservation already extended {limit} time(s), the maximum"
        )
    base = territory.reservation_expires_at or as_of
    expires = base + timedelta(days=rules.registry.reservation_extension_days)
    return TransitionPlan(
        event="RESERVATION_EXTENDED",
        new_status=TerritoryStatus.RESERVED,
        fields={
            "reservation_expires_at": expires,
            "reservation_extensions": territory.reservation_extensions + 1,
        },
        note=audit_line(as_of, approver, "RESERVATION_EXTENDED", f"until {expires}: {reason}"),
    )


def plan_activate(
    territory: TerritoryRecord,
    *,
    approved_by: str | None,
    contract_start_date: date,
    contract_end_date: date | None,
    as_of: date,
    at: datetime | None = None,
) -> TransitionPlan:
    """RESERVED -> ACTIVE_PROTECTED on a signed agreement."""
    _expect_status(territory, TerritoryStatus.RESERVED, event="activate")
    approver = _require_actor(approved_by, "APPROVAL_REQUIRED", "ACTIVE_PROTECTED")
    if contract_end_date is not None and contract_end_date < contract_start_date:
        raise InvalidTransition("CONTRACT_DATES", "contract_end_date precedes contract_start_date")
    return TransitionPlan(
        event="ACTIVATED",
        new_status=TerritoryStatus.ACTIVE_PROTECTED,
        fields={
            "approved_by": approver,
            "approved_at": at or at_midnight(as_of),
            "contract_start_date": contract_start_date,
            "contract_end_date": contract_end_date,
        },
        assignment_status=AssignmentStatus.ACTIVE_PROTECTED,
        note=audit_line(
            as_of, approver, "ACTIVE_PROTECTED", f"contract from {contract_start_date}"
        ),
    )


def plan_cancel(
    territory: TerritoryRecord, *, actor: str | None, reason: str, as_of: date
) -> TransitionPlan:
    """PROPOSED or RESERVED -> CANCELLED; reserved ZIPs are released the same day."""
    _expect_status(territory, TerritoryStatus.PROPOSED, TerritoryStatus.RESERVED, event="cancel")
    who = _require_actor(actor, "ACTOR_REQUIRED", "cancellation")
    return TransitionPlan(
        event="CANCELLED",
        new_status=TerritoryStatus.CANCELLED,
        fields={"release_date": as_of},
        assignment_status=AssignmentStatus.RELEASED,
        assignment_date_released=as_of,
        note=audit_line(as_of, who, "CANCELLED", reason or "no reason given"),
    )


def plan_pending_release(
    territory: TerritoryRecord,
    *,
    actor: str | None,
    reason: str,
    release_date: date | None,
    as_of: date,
    rules: BusinessRules,
) -> TransitionPlan:
    """ACTIVE_PROTECTED -> PENDING_RELEASE with notice (default 30 days, or contract end)."""
    _expect_status(territory, TerritoryStatus.ACTIVE_PROTECTED, event="pending release")
    who = _require_actor(actor, "ACTOR_REQUIRED", "a release decision")
    default = as_of + timedelta(days=rules.registry.release_notice_days)
    if territory.contract_end_date is not None and territory.contract_end_date > default:
        default = territory.contract_end_date
    effective = release_date or default
    if effective < as_of:
        raise InvalidTransition("RELEASE_DATE_PAST", "release_date cannot be before as_of")
    return TransitionPlan(
        event="PENDING_RELEASE",
        new_status=TerritoryStatus.PENDING_RELEASE,
        fields={"release_date": effective},
        assignment_status=AssignmentStatus.PENDING_RELEASE,
        note=audit_line(as_of, who, "PENDING_RELEASE", f"ZIPs release on {effective}: {reason}"),
    )


def plan_release(territory: TerritoryRecord, *, actor: str | None, as_of: date) -> TransitionPlan:
    """PENDING_RELEASE -> RELEASED on or after the release date; history is kept."""
    _expect_status(territory, TerritoryStatus.PENDING_RELEASE, event="release")
    who = _require_actor(actor, "ACTOR_REQUIRED", "a release")
    release_on = territory.release_date or as_of
    if release_on > as_of:
        raise InvalidTransition(
            "RELEASE_DATE_NOT_REACHED", f"release_date {release_on} is after {as_of}"
        )
    return TransitionPlan(
        event="RELEASED",
        new_status=TerritoryStatus.RELEASED,
        assignment_status=AssignmentStatus.RELEASED,
        assignment_date_released=release_on,
        note=audit_line(as_of, who, "RELEASED", f"ZIPs available from {release_on}"),
    )


def validate_exception(
    exception_type: str, approved_by: str | None, reason: str, as_of: date, rules: BusinessRules
) -> ExceptionRecord:
    """Standard section 9: only listed exception types, always with approver and reason."""
    if exception_type not in rules.registry.allowed_exceptions:
        raise ExceptionNotAllowed(
            "EXCEPTION_NOT_ALLOWED",
            f"{exception_type!r} is not an allowed exception",
            {"allowed": list(rules.registry.allowed_exceptions)},
        )
    approver = _require_actor(approved_by, "APPROVAL_REQUIRED", "an exception")
    if not reason.strip():
        raise ApprovalRequired("REASON_REQUIRED", "an exception requires a reason")
    return ExceptionRecord(
        type=exception_type, approved_by=approver, reason=reason.strip(), at=as_of.isoformat()
    )


class InvalidProposal(RegistryError):
    status_code = 422


# ---- stateful orchestration --------------------------------------------------------------------


class RegistryService:
    """Loads records through the repository, applies the pure rules, persists the plan.

    ``as_of`` is explicit (never read from the clock here) so tests and back-dated actions are
    deterministic. The caller owns the transaction: methods flush, the API commits.
    """

    def __init__(
        self, session: Any, rules: BusinessRules, *, as_of: date, at: datetime | None = None
    ) -> None:
        from app.repositories import registry as repo

        self._repo = repo
        self._session = session
        self.rules = rules
        self.as_of = as_of
        self.at = at or at_midnight(as_of)

    # ---- reads ---------------------------------------------------------------------------------

    def _row(self, territory_id: str) -> Any:
        row = self._repo.get_territory_row(self._session, territory_id)
        if row is None:
            raise TerritoryNotFound("TERRITORY_NOT_FOUND", f"no territory {territory_id}")
        return row

    def get(self, territory_id: str) -> TerritoryRecord:
        return self._repo.to_record(self._row(territory_id))

    def list(
        self, *, status: TerritoryStatus | str | None = None, client_id: str | None = None
    ) -> list[TerritoryRecord]:
        status_value = status.value if isinstance(status, TerritoryStatus) else status
        rows = self._repo.list_territory_rows(
            self._session, status=status_value, client_id=client_id
        )
        return [self._repo.to_record(row) for row in rows]

    def response(self, record: TerritoryRecord) -> TerritoryResponse:
        return TerritoryResponse.from_record(record, territory_flags(record, self.as_of))

    def availability(
        self, zips: list[str], *, client_id: str | None = None
    ) -> list[ZipAvailabilityResult]:
        snapshot = self._repo.load_snapshot(self._session, self.as_of, zips)
        return [availability_for(z, snapshot, client_id=client_id) for z in zips]

    def flags(self) -> RegistryFlagsResponse:
        expired = [
            self.response(r)
            for r in self.list(status=TerritoryStatus.RESERVED)
            if FLAG_RESERVATION_EXPIRED in territory_flags(r, self.as_of)
        ]
        due = [
            self.response(r)
            for r in self.list(status=TerritoryStatus.PENDING_RELEASE)
            if FLAG_RELEASE_DUE in territory_flags(r, self.as_of)
        ]
        return RegistryFlagsResponse(
            as_of=self.as_of, expired_reservations=expired, releases_due=due
        )

    # ---- writes --------------------------------------------------------------------------------

    def _conflicts(self, zips: list[str], client_id: str) -> None:
        registry = self._repo.load_snapshot(self._session, self.as_of, zips)
        conflicts = conflicts_for(zips, registry, client_id=client_id)
        if conflicts:
            raise ZipConflict(
                "ZIP_CONFLICT",
                f"{len(conflicts)} ZIP(s) are blocked for another client",
                [c.model_dump(mode="json") for c in conflicts],
            )

    def create_proposal(
        self,
        *,
        client_id: str,
        client_business_name: str,
        starting_zip: str,
        size_class: TerritorySizeClass,
        zips: list[str],
        notes: str | None = None,
        snapshot: dict[str, Any] | None = None,
    ) -> TerritoryRecord:
        codes = sorted({str(z).strip() for z in zips})
        if not codes or any(len(z) != 5 or not z.isdigit() for z in codes):
            raise InvalidProposal("INVALID_ZIPS", "zips must be 5-digit ZCTA codes")
        if starting_zip not in codes:
            raise InvalidProposal("STARTING_ZIP_NOT_IN_LIST", "starting_zip must be in zips")
        unknown = sorted(set(codes) - self._repo.known_zctas(self._session, codes))
        if unknown:
            raise UnknownZips("NO_MARKET_DATA", f"unknown ZCTAs: {unknown}", {"zips": unknown})
        self._complete_due_releases(codes)
        self._conflicts(codes, client_id)
        territory_id = next_territory_id(self._repo.last_territory_id(self._session))
        detail = f"{len(codes)} ZIPs from {starting_zip}" + (f"; {notes}" if notes else "")
        row = self._repo.create_territory_row(
            self._session,
            {
                "territory_id": territory_id,
                "client_id": client_id,
                "client_business_name": client_business_name,
                "starting_zip": starting_zip,
                "territory_size_class": size_class.value,
                "status": TerritoryStatus.PROPOSED.value,
                "generation_snapshot_json": {**(snapshot or {}), "zips": codes},
                "notes": audit_line(self.as_of, "engine", "PROPOSED", detail),
            },
        )
        return self._repo.to_record(row)

    def _apply(self, territory_id: str, plan: TransitionPlan) -> TerritoryRecord:
        row = self._row(territory_id)
        return self._repo.to_record(self._repo.apply_plan(self._session, row, plan, self.as_of))

    def _complete_due_releases(self, zips: list[str] | None = None) -> list[str]:
        """PENDING_RELEASE territories past their release date become RELEASED (Standard 11)."""
        released: list[str] = []
        for record in self.list(status=TerritoryStatus.PENDING_RELEASE):
            if FLAG_RELEASE_DUE not in territory_flags(record, self.as_of):
                continue
            if zips is not None and not set(record.zips) & set(zips):
                continue
            plan = plan_release(record, actor="system", as_of=self.as_of)
            self._apply(record.territory_id, plan)
            released.append(record.territory_id)
        return released

    def reserve(self, territory_id: str, *, approved_by: str | None) -> TerritoryRecord:
        record = self.get(territory_id)
        plan = plan_reserve(
            record, approved_by=approved_by, as_of=self.as_of, rules=self.rules, at=self.at
        )
        self._complete_due_releases(record.zips)
        self._conflicts(record.zips, record.client_id)
        return self._apply(territory_id, plan)

    def extend(self, territory_id: str, *, approved_by: str | None, reason: str) -> TerritoryRecord:
        plan = plan_extend(
            self.get(territory_id),
            approved_by=approved_by,
            reason=reason,
            as_of=self.as_of,
            rules=self.rules,
        )
        return self._apply(territory_id, plan)

    def activate(
        self,
        territory_id: str,
        *,
        approved_by: str | None,
        contract_start_date: date,
        contract_end_date: date | None = None,
    ) -> TerritoryRecord:
        plan = plan_activate(
            self.get(territory_id),
            approved_by=approved_by,
            contract_start_date=contract_start_date,
            contract_end_date=contract_end_date,
            as_of=self.as_of,
            at=self.at,
        )
        return self._apply(territory_id, plan)

    def cancel(self, territory_id: str, *, actor: str | None, reason: str) -> TerritoryRecord:
        plan = plan_cancel(self.get(territory_id), actor=actor, reason=reason, as_of=self.as_of)
        return self._apply(territory_id, plan)

    def pending_release(
        self,
        territory_id: str,
        *,
        actor: str | None,
        reason: str,
        release_date: date | None = None,
    ) -> TerritoryRecord:
        plan = plan_pending_release(
            self.get(territory_id),
            actor=actor,
            reason=reason,
            release_date=release_date,
            as_of=self.as_of,
            rules=self.rules,
        )
        return self._apply(territory_id, plan)

    def release(self, territory_id: str, *, actor: str | None) -> TerritoryRecord:
        plan = plan_release(self.get(territory_id), actor=actor, as_of=self.as_of)
        return self._apply(territory_id, plan)

    def record_exception(
        self, territory_id: str, *, exception_type: str, approved_by: str | None, reason: str
    ) -> TerritoryRecord:
        exception = validate_exception(exception_type, approved_by, reason, self.as_of, self.rules)
        row = self._row(territory_id)
        event = f"EXCEPTION_{exception.type}"
        note = audit_line(self.as_of, exception.approved_by, event, reason)
        self._repo.add_exception(self._session, row, exception, note)
        return self._repo.to_record(row)

    def sweep_due_releases(self) -> SweepResponse:
        released = self._complete_due_releases()
        expired = [t.territory_id for t in self.flags().expired_reservations]
        return SweepResponse(as_of=self.as_of, released=released, expired_reservations=expired)
