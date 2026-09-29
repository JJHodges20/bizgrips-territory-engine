"""ORM schema creates cleanly and enforces the registry's core invariant."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import BusinessRules
from app.models import (
    DataSourceImport,
    ScoringConfig,
    Territory,
    TerritoryZipAssignment,
    ZctaAdjacency,
    ZctaMarket,
)

EXPECTED_TABLES = {
    "zcta_markets",
    "zcta_adjacency",
    "territories",
    "territory_zip_assignments",
    "scoring_configs",
    "data_source_imports",
    "data_field_provenance",
}


def _territory(territory_id: str, client_id: str, status: str = "ACTIVE_PROTECTED") -> Territory:
    return Territory(
        territory_id=territory_id,
        client_id=client_id,
        client_business_name=f"{client_id} Baths",
        starting_zip="80123",
        territory_size_class="STANDARD",
        status=status,
        approved_by="Sales Manager",
        contract_start_date=date(2026, 3, 1),
    )


def _assignment(territory: Territory, zip_code: str, status: str) -> TerritoryZipAssignment:
    return TerritoryZipAssignment(
        territory_id=territory.territory_id,
        client_id=territory.client_id,
        zip=zip_code,
        status=status,
        date_assigned=date(2026, 3, 1),
    )


def test_all_tables_exist(engine) -> None:
    assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())


def test_market_and_adjacency_round_trip(session: Session) -> None:
    provenance = DataSourceImport(dataset="fixture", vintage="test", record_count=2)
    session.add(provenance)
    session.flush()
    session.add_all(
        [
            ZctaMarket(
                zcta="80123",
                primary_city="Littleton",
                state="CO",
                total_households=16500,
                owner_occupied_households=13400,
                geography_import_id=provenance.id,
            ),
            ZctaMarket(
                zcta="80127",
                primary_city="Littleton",
                state="CO",
                total_households=14700,
                owner_occupied_households=12100,
                geography_import_id=provenance.id,
            ),
        ]
    )
    session.flush()
    session.add(ZctaAdjacency(zcta_a="80123", zcta_b="80127", shared_boundary_length_m=4800.0))
    session.commit()

    row = session.get(ZctaMarket, "80123")
    assert row is not None and row.unserviceable_land_area is False
    pair = session.get(ZctaAdjacency, ("80123", "80127"))
    assert pair is not None and pair.shared_boundary_length_m == 4800.0
    assert ZctaAdjacency.ordered("80127", "80123") == ("80123", "80127")


def test_adjacency_requires_ordered_pair_and_known_zctas(session: Session) -> None:
    session.add(ZctaMarket(zcta="80123"))
    session.add(ZctaMarket(zcta="80127"))
    session.flush()
    session.add(ZctaAdjacency(zcta_a="80127", zcta_b="80123"))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    session.add(ZctaMarket(zcta="80123"))
    session.flush()
    session.add(ZctaAdjacency(zcta_a="80123", zcta_b="99999"))
    with pytest.raises(IntegrityError):  # foreign keys are enforced on SQLite via PRAGMA
        session.flush()
    session.rollback()


def test_same_zip_cannot_be_active_for_two_territories(session: Session) -> None:
    alpha = _territory("T-000001", "C-ALPHA")
    bravo = _territory("T-000002", "C-BRAVO", status="RESERVED")
    session.add_all([alpha, bravo])
    session.flush()
    session.add(_assignment(alpha, "80123", "ACTIVE_PROTECTED"))
    session.flush()
    session.add(_assignment(bravo, "80123", "RESERVED"))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_released_assignment_frees_the_zip(session: Session) -> None:
    alpha = _territory("T-000001", "C-ALPHA", status="RELEASED")
    bravo = _territory("T-000002", "C-BRAVO")
    session.add_all([alpha, bravo])
    session.flush()
    released = _assignment(alpha, "80123", "RELEASED")
    released.date_released = date(2026, 9, 1)
    session.add(released)
    session.add(_assignment(bravo, "80123", "ACTIVE_PROTECTED"))
    session.commit()
    assignments = session.query(TerritoryZipAssignment).filter_by(zip="80123").all()
    assert {a.status for a in assignments} == {"RELEASED", "ACTIVE_PROTECTED"}
    assert [a.is_blocking for a in sorted(assignments, key=lambda a: a.status)] == [True, False]


def test_invalid_status_is_rejected(session: Session) -> None:
    session.add(_territory("T-000009", "C-X", status="MAYBE"))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_scoring_config_snapshot_round_trip(session: Session, rules: BusinessRules) -> None:
    session.add(ScoringConfig.from_rules(rules))
    session.commit()
    row = session.get(ScoringConfig, rules.version)
    assert row is not None
    assert row.owner_household_weight == pytest.approx(0.35)
    assert row.standard_target_min == 20000
    assert row.full_config_json["scoring"]["weights"]["serviceability"] == pytest.approx(0.05)
