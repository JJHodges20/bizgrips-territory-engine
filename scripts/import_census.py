"""Import ACS 5-Year demographic data for every ZCTA (Milestone 1).

Milestone 0 ships the interface and the import plan only. Running it prints the plan derived
from app/config/census_variables.yaml and exits with status 2 so `make import-data` fails
visibly until Milestone 1 lands.

Planned behaviour (docs/MILESTONES.md, Milestone 1):
  1. Validate variable labels against {endpoint}/variables.json (`label_contains`).
  2. Pull all ZCTAs in batches of <= 50 variables (CENSUS_API_KEY optional).
  3. Convert sentinel values to NULL; sum bucket variables into the stored fields.
  4. Upsert zcta_markets demographic columns; record data_source_imports + data_field_provenance.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings, load_census_variables  # noqa: E402


def print_plan(vintage: int | None) -> None:
    variables = load_census_variables()
    settings = get_settings()
    effective_vintage = vintage or variables.vintage
    print("ACS import plan")
    print(
        f"  dataset:   {variables.dataset} vintage {effective_vintage} ({variables.release_label})"
    )
    print(f"  endpoint:  {variables.api_base}/{effective_vintage}/{variables.dataset}")
    print(f"  geography: {variables.geography}")
    print(f"  api key:   {'set' if settings.census_api_key else 'not set (rate-limited)'}")
    print(f"  tables:    {', '.join(variables.tables)}")
    print(f"  variables: {len(variables.all_variables)}")
    for name, field in variables.fields.items():
        print(f"    {name:32s} {field.table:7s} {'+'.join(field.variables)}")
    if vintage and vintage != variables.vintage:
        print(
            f"  WARNING: --vintage {vintage} differs from census_variables.yaml "
            f"({variables.vintage}); label checks must pass before any data is written."
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--vintage", type=int, default=None, help="override the ACS vintage")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and exit 0")
    args = parser.parse_args(argv)

    print_plan(args.vintage)
    if args.dry_run:
        return 0
    print("\nNOT IMPLEMENTED: ACS import is Milestone 1. See docs/MILESTONES.md.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
