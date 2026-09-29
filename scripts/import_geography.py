"""Import ZCTA geography (Milestone 1): boundaries, centroids, land area, adjacency, state, city.

Milestone 0 ships the interface and the plan only. Running it prints the sources from
app/config/census_variables.yaml and exits with status 2 so `make import-data` fails visibly
until Milestone 1 lands.

Planned behaviour (docs/MILESTONES.md, Milestone 1):
  1. Download each source to data/raw/ with a sha256 checksum (skip if unchanged).
  2. Load the ZCTA boundary shapefile with geopandas (optional `geo` extra).
  3. Compute representative-point lat/lon, land/water area in sq mi, and rook adjacency with
     shared boundary length in a projected CRS (EPSG:5070).
  4. Assign the dominant state from the ZCTA-to-county relationship file and the primary city
     plus postal_zip from GeoNames.
  5. Upsert zcta_markets geography columns and zcta_adjacency; record provenance.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings, load_census_variables  # noqa: E402


def print_plan() -> None:
    variables = load_census_variables()
    settings = get_settings()
    print("Geography import plan")
    print(f"  raw data dir: {settings.raw_data_dir}")
    for key, source in variables.geography_sources.items():
        print(f"  {key}: {source.name}")
        print(f"    {source.url}")
        if source.fields:
            print(f"    fields: {source.fields}")
        if source.notes:
            print(f"    note: {source.notes}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--with-geometry", action="store_true", help="also store GeoJSON polygons")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and exit 0")
    args = parser.parse_args(argv)

    print_plan()
    if args.with_geometry:
        print("  geometry: GeoJSON polygons will be stored in zcta_markets.geometry_geojson")
    if args.dry_run:
        return 0
    print("\nNOT IMPLEMENTED: geography import is Milestone 1. See docs/MILESTONES.md.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
