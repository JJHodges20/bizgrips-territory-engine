"""Plain-data views of the territory registry plus API request/response models (M4)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.enums import AssignmentStatus, TerritorySizeClass, TerritoryStatus, ZipAvailability

FLAG_RESERVATION_EXPIRED = "RESERVATION_EXPIRED"
FLAG_RELEASE_DUE = "RELEASE_DUE"


class AssignmentRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    territory_id: str
    client_id: str
    zip: str
    status: AssignmentStatus
    date_assigned: date
    date_released: date | None = None


class ExceptionRecord(BaseModel):
    """One manual exception on a territory (Standard section 9); stored in exceptions_json."""

    type: str
    approved_by: str
    reason: str
    at: str  # ISO timestamp


class TerritoryRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    territory_id: str
    client_id: str
    client_business_name: str
    starting_zip: str
    territory_size_class: TerritorySizeClass
    status: TerritoryStatus
    approved_by: str | None = None
    approved_at: datetime | None = None
    reservation_date: date | None = None
    reservation_expires_at: date | None = None
    reservation_extensions: int = 0
    contract_start_date: date | None = None
    contract_end_date: date | None = None
    release_date: date | None = None
    exceptions: list[ExceptionRecord] = Field(default_factory=list)
    generation_snapshot: dict[str, Any] | None = None
    notes: str | None = None
    assignments: list[AssignmentRecord] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def zips(self) -> list[str]:
        """The territory definition: assignment ZIPs once reserved, the proposal list before."""
        if self.assignments:
            return sorted({a.zip for a in self.assignments})
        snapshot = self.generation_snapshot or {}
        return sorted(str(z) for z in snapshot.get("zips", []))


class BlockingInfo(BaseModel):
    """The assignment that blocks a ZIP, with what a sales manager needs to act on it."""

    zip: str
    territory_id: str
    client_id: str
    client_business_name: str
    status: AssignmentStatus
    reservation_expires_at: date | None = None
    release_date: date | None = None
    contract_end_date: date | None = None
    expired: bool = False


class RegistrySnapshot(BaseModel):
    """Blocking assignments keyed by ZIP at a point in time (read-only view for services)."""

    as_of: date
    blocking: dict[str, BlockingInfo] = Field(default_factory=dict)


class ZipAvailabilityResult(BaseModel):
    zip: str
    availability: ZipAvailability
    own: bool = False  # blocked by the requesting client's own territory: not a conflict
    is_conflict: bool = False
    blocking: BlockingInfo | None = None
    flags: list[str] = Field(default_factory=list)


class TransitionPlan(BaseModel):
    """What a validated transition changes; the repository applies it verbatim."""

    event: str
    new_status: TerritoryStatus
    fields: dict[str, Any] = Field(default_factory=dict)
    assignment_status: AssignmentStatus | None = None
    assignment_date_released: date | None = None
    create_assignments_for: list[str] = Field(default_factory=list)
    note: str


# ---- API request models -----------------------------------------------------------------------


class TerritoryCreateRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=64)
    client_business_name: str = Field(min_length=1, max_length=200)
    starting_zip: str = Field(pattern=r"^\d{5}$")
    territory_size_class: TerritorySizeClass = TerritorySizeClass.STANDARD
    zips: list[str] = Field(min_length=1)
    notes: str | None = None
    generation_snapshot: dict[str, Any] | None = None


class ApprovalRequest(BaseModel):
    approved_by: str = Field(min_length=1, max_length=120)


class ExtendRequest(ApprovalRequest):
    reason: str = Field(min_length=1)


class ActivateRequest(ApprovalRequest):
    contract_start_date: date
    contract_end_date: date | None = None


class ActorRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1)


class PendingReleaseRequest(ActorRequest):
    release_date: date | None = None


class ReleaseRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=120)


class ExceptionRequest(ApprovalRequest):
    exception_type: str = Field(min_length=1)
    reason: str = Field(min_length=1)


# ---- API response models ----------------------------------------------------------------------


class TerritoryResponse(TerritoryRecord):
    zip_count: int
    flags: list[str] = Field(default_factory=list)

    @classmethod
    def from_record(cls, record: TerritoryRecord, flags: list[str]) -> TerritoryResponse:
        data = record.model_dump(exclude={"zips"})
        return cls(**data, zip_count=len(record.zips), flags=flags)


class TerritoryListResponse(BaseModel):
    items: list[TerritoryResponse]
    total: int


class RegistryFlagsResponse(BaseModel):
    as_of: date
    expired_reservations: list[TerritoryResponse]
    releases_due: list[TerritoryResponse]


class SweepResponse(BaseModel):
    as_of: date
    released: list[str]
    expired_reservations: list[str]
