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

from app.db import create_db_engine, create_session_factory, init_db  # noqa: E402
from app.fixtures import LoadedScenario, list_scenarios, load_scenario  # noqa: E402
from app.ingest.seed import seed_scenario  # noqa: E402


def seed(loaded: LoadedScenario, database_url: str | None, replace: bool) -> dict[str, int]:
    engine = create_db_engine(database_url)
    init_db(engine)
    factory = create_session_factory(engine)
    with factory() as session, session.begin():
        counts = seed_scenario(session, loaded, replace=replace)
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
