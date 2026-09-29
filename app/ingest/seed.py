"""Seed a fixture scenario (data/fixtures/scenarios/*.json) into a database session.

Development and test convenience: gives the API something to serve before or beside the real
Census import. Fixture values are synthetic; they are not Census data.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.fixtures import LoadedScenario
from app.models import (
    DataSourceImport,
    Territory,
    TerritoryZipAssignment,
    ZctaAdjacency,
    ZctaMarket,
)

_ASSIGNMENT_STATUS = {
    "RESERVED": "RESERVED",
    "ACTIVE_PROTECTED": "ACTIVE_PROTECTED",
    "PENDING_RELEASE": "PENDING_RELEASE",
    "RELEASED": "RELEASED",
    "CANCELLED": "RELEASED",
}


def assignment_status(territory_status: str) -> str:
    """Map a fixture territory status to the status written on each ZIP assignment."""
    if territory_status not in _ASSIGNMENT_STATUS:
        raise ValueError(f"fixture territories cannot be seeded with status {territory_status}")
    return _ASSIGNMENT_STATUS[territory_status]


def seed_scenario(
    session: Session, loaded: LoadedScenario, replace: bool = False
) -> dict[str, int]:
    """Write the scenario's markets, adjacency and registry state. Caller commits."""
    scenario, market = loaded.scenario, loaded.market
    counts = {"zctas": 0, "adjacency": 0, "territories": 0, "assignments": 0}

    if replace:
        session.execute(delete(TerritoryZipAssignment))
        session.execute(delete(Territory))
        session.execute(delete(ZctaAdjacency))
        session.execute(delete(ZctaMarket))

    provenance = DataSourceImport(
        dataset="fixture",
        vintage=scenario.scenario_id,
        release_label=f"Synthetic fixture scenario {scenario.scenario_id}",
        source_url=None,
        record_count=len(market.zctas),
        notes="Synthetic values for development and tests. Not real Census data.",
    )
    session.add(provenance)
    session.flush()

    for record in market.zctas:
        row = ZctaMarket(**record.to_orm_kwargs())
        row.demographics_import_id = provenance.id
        row.geography_import_id = provenance.id
        row.source_release = f"fixture:{scenario.scenario_id}"
        session.merge(row)
        counts["zctas"] += 1
    session.flush()

    for a, b in market.adjacency:
        za, zb = ZctaAdjacency.ordered(a, b)
        session.merge(ZctaAdjacency(zcta_a=za, zcta_b=zb, geography_import_id=provenance.id))
        counts["adjacency"] += 1
    session.flush()

    for fixture in scenario.territories:
        existing = session.get(Territory, fixture.territory_id)
        if existing is not None:
            session.execute(
                delete(TerritoryZipAssignment).where(
                    TerritoryZipAssignment.territory_id == fixture.territory_id
                )
            )
            session.delete(existing)
            session.flush()
        territory = Territory(
            territory_id=fixture.territory_id,
            client_id=fixture.client_id,
            client_business_name=fixture.client_business_name,
            starting_zip=fixture.starting_zip,
            territory_size_class=fixture.territory_size_class.value,
            status=fixture.status.value,
            approved_by=fixture.approved_by,
            reservation_date=fixture.reservation_date,
            reservation_expires_at=fixture.reservation_expires_at,
            contract_start_date=fixture.contract_start_date,
            contract_end_date=fixture.contract_end_date,
            release_date=fixture.release_date,
            notes=fixture.notes,
        )
        session.add(territory)
        assigned_on = fixture.reservation_date or fixture.contract_start_date or scenario.as_of
        released = fixture.status.value in ("RELEASED", "CANCELLED")
        for zip_code in fixture.zips:
            session.add(
                TerritoryZipAssignment(
                    territory_id=fixture.territory_id,
                    client_id=fixture.client_id,
                    zip=zip_code,
                    status=assignment_status(fixture.status.value),
                    date_assigned=assigned_on,
                    date_released=fixture.release_date if released else None,
                )
            )
            counts["assignments"] += 1
        counts["territories"] += 1

    counts["total_zctas_in_db"] = len(session.scalars(select(ZctaMarket.zcta)).all())
    return counts
