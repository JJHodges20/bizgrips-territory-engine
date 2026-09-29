"""Load a fixture scenario (data/fixtures/scenarios/*.json) into the configured database.

Development convenience only: gives the API and later the sales UI something to show before
real Census data is imported (Milestone 1).

    venv/Scripts/python.exe scripts/seed_fixtures.py --scenario denver_suburban_available
    venv/Scripts/python.exe scripts/seed_fixtures.py --list
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select  # noqa: E402

from app.db import create_db_engine, create_session_factory, init_db  # noqa: E402
from app.fixtures import LoadedScenario, list_scenarios, load_scenario  # noqa: E402
from app.models import (  # noqa: E402
    DataSourceImport,
    Territory,
    TerritoryZipAssignment,
    ZctaAdjacency,
    ZctaMarket,
)


def _assignment_status(territory_status: str) -> str:
    """Map a fixture territory status to the status written on each ZIP assignment."""
    mapping = {
        "RESERVED": "RESERVED",
        "ACTIVE_PROTECTED": "ACTIVE_PROTECTED",
        "PENDING_RELEASE": "PENDING_RELEASE",
        "RELEASED": "RELEASED",
        "CANCELLED": "RELEASED",
    }
    if territory_status not in mapping:
        raise ValueError(f"fixture territories cannot be seeded with status {territory_status}")
    return mapping[territory_status]


def seed(loaded: LoadedScenario, database_url: str | None, replace: bool) -> dict[str, int]:
    engine = create_db_engine(database_url)
    init_db(engine)
    factory = create_session_factory(engine)
    scenario, market = loaded.scenario, loaded.market
    counts = {"zctas": 0, "adjacency": 0, "territories": 0, "assignments": 0}

    with factory() as session, session.begin():
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
            for zip_code in fixture.zips:
                session.add(
                    TerritoryZipAssignment(
                        territory_id=fixture.territory_id,
                        client_id=fixture.client_id,
                        zip=zip_code,
                        status=_assignment_status(fixture.status.value),
                        date_assigned=assigned_on,
                        date_released=fixture.release_date
                        if fixture.status.value in ("RELEASED", "CANCELLED")
                        else None,
                    )
                )
                counts["assignments"] += 1
            counts["territories"] += 1

        counts["total_zctas_in_db"] = len(session.scalars(select(ZctaMarket.zcta)).all())
    engine.dispose()
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--scenario", help="scenario id from data/fixtures/scenarios")
    parser.add_argument("--database-url", default=None, help="override DATABASE_URL")
    parser.add_argument(
        "--replace", action="store_true", help="wipe market, adjacency and registry tables first"
    )
    parser.add_argument("--list", action="store_true", help="list available scenarios and exit")
    args = parser.parse_args(argv)

    if args.list or not args.scenario:
        for scenario_id in list_scenarios():
            print(scenario_id)
        return 0 if args.list else 1

    loaded = load_scenario(args.scenario)
    counts = seed(loaded, args.database_url, args.replace)
    print(f"Seeded scenario {args.scenario!r} (as_of {loaded.scenario.as_of.isoformat()}):")
    for key, value in counts.items():
        print(f"  {key}: {value}")
    print("Reminder: fixture values are synthetic; they are not Census data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
