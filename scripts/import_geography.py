"""Import ZCTA geography: boundaries, centroids, land area, adjacency, state, city (Milestone 1).

    venv/Scripts/python.exe scripts/import_geography.py [--with-geometry] [--refresh]
    venv/Scripts/python.exe scripts/import_geography.py --dry-run
    venv/Scripts/python.exe scripts/import_geography.py \
        --boundaries tests/fixtures/zcta_boundaries_four.geojson \
        --relationship tests/fixtures/zcta_county_rel_sample.txt \
        --geonames tests/fixtures/geonames_sample.txt

Steps: download each source in app/config/census_variables.yaml to data/raw (sha256 recorded,
cached unless --refresh); extract the boundary shapefile; compute centroids, land/water area and
rook adjacency with shared boundary length (EPSG:5070); dominant state from the ZCTA-to-county
relationship file; primary city and postal_zip from GeoNames; upsert zcta_markets and
zcta_adjacency; record data_source_imports and data_field_provenance. Requires the `geo` extra.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_business_rules, get_settings, load_census_variables  # noqa: E402
from app.config.census_variables import GeographySource  # noqa: E402
from app.db import create_db_engine, create_session_factory, init_db  # noqa: E402
from app.ingest.download import DownloadResult, download_file, sha256_of_file  # noqa: E402
from app.ingest.geography import (  # noqa: E402
    adjacency_degrees,
    compute_adjacency,
    compute_geography,
    load_boundaries,
    read_geonames_places,
    read_zcta_state_overlap,
)
from app.ingest.store import ImportMeta, write_geography  # noqa: E402

SPOT_CHECK_ZCTAS = ("80123", "82633", "07103", "44301", "85224")


def obtain(
    source: GeographySource, raw_dir: Path, override: str | None, refresh: bool
) -> DownloadResult:
    """Local file for a source: an explicit path (checksummed, never downloaded) or the download."""
    if override:
        path = Path(override)
        return DownloadResult(path, sha256_of_file(path), path.stat().st_size, downloaded=False)
    result = download_file(source.url, raw_dir / source.local_filename, refresh=refresh)
    print(f"  {source.dataset}: {result.status} {result.path.name} ({result.size_bytes:,} bytes)")
    return result


def boundary_layer(path: Path) -> Path:
    """Extract a zipped shapefile next to the archive (once) and return the .shp path."""
    if path.suffix.lower() != ".zip":
        return path
    target = path.with_suffix("")
    shp = next(target.glob("*.shp"), None) if target.is_dir() else None
    if shp is None:
        with zipfile.ZipFile(path) as archive:
            archive.extractall(target)
        shp = next(target.glob("*.shp"))
    return shp


def vintage_for(source: GeographySource, result: DownloadResult) -> str:
    if source.vintage:
        return source.vintage
    return datetime.fromtimestamp(result.path.stat().st_mtime, UTC).date().isoformat()


def meta_for(source: GeographySource, result: DownloadResult) -> ImportMeta:
    return ImportMeta(
        dataset=source.dataset,
        vintage=vintage_for(source, result),
        release_label=source.name,
        source_url=source.url,
        checksum=result.sha256,
        notes=source.notes,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--with-geometry", action="store_true", help="also store GeoJSON polygons")
    parser.add_argument(
        "--simplify-tolerance",
        type=float,
        default=0.0005,
        help="Douglas-Peucker tolerance in degrees for stored polygons (default 0.0005)",
    )
    parser.add_argument("--refresh", action="store_true", help="re-download cached source files")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and exit 0")
    parser.add_argument("--raw-dir", default=None, help="override data/raw")
    parser.add_argument("--database-url", default=None, help="override DATABASE_URL")
    parser.add_argument("--boundaries", help="local boundary file instead of the download")
    parser.add_argument("--relationship", help="local ZCTA-to-county file instead of the download")
    parser.add_argument("--geonames", help="local GeoNames US.zip/US.txt instead of the download")
    args = parser.parse_args(argv)

    variables = load_census_variables()
    settings = get_settings()
    rules = get_business_rules()
    raw_dir = Path(args.raw_dir) if args.raw_dir else settings.raw_data_dir
    sources = variables.geography_sources
    print("Geography import")
    print(f"  raw data dir: {raw_dir}")
    for key, source in sources.items():
        print(f"  {key}: {source.name} -> {source.local_filename}")
    if args.dry_run:
        return 0

    started = time.perf_counter()
    print("Sources:")
    boundaries = obtain(sources["zcta_boundaries"], raw_dir, args.boundaries, args.refresh)
    relationship = obtain(sources["zcta_to_county"], raw_dir, args.relationship, args.refresh)
    geonames = obtain(sources["postal_places"], raw_dir, args.geonames, args.refresh)

    gdf = load_boundaries(boundary_layer(boundaries.path))
    print(f"Loaded {len(gdf):,} ZCTA polygons ({time.perf_counter() - started:.1f}s)")
    geography = compute_geography(
        gdf, with_geometry=args.with_geometry, simplify_tolerance=args.simplify_tolerance
    )
    adjacency = compute_adjacency(gdf)
    degrees = adjacency_degrees(adjacency)
    print(
        f"Computed {len(adjacency):,} adjacent pairs; neighbours per ZCTA median "
        f"{statistics.median(degrees.values()) if degrees else 0:.0f}, max "
        f"{max(degrees.values(), default=0)}, isolated {len(gdf) - len(degrees):,} "
        f"({time.perf_counter() - started:.1f}s)"
    )
    states = read_zcta_state_overlap(relationship.path)
    places = read_geonames_places(geonames.path)

    engine = create_db_engine(args.database_url)
    init_db(engine)
    factory = create_session_factory(engine)
    with factory() as session, session.begin():
        result = write_geography(
            session,
            geography=geography,
            adjacency=adjacency,
            states=states,
            places=places,
            boundary_meta=meta_for(sources["zcta_boundaries"], boundaries),
            relationship_meta=meta_for(sources["zcta_to_county"], relationship),
            places_meta=meta_for(sources["postal_places"], geonames),
            max_land_area_sq_miles=rules.serviceability.max_zcta_land_area_sq_miles,
        )
    engine.dispose()

    print("Written:")
    print(
        f"  zcta_markets: {result.markets.inserted:,} inserted, {result.markets.updated:,} updated"
    )
    a = result.adjacency
    print(
        f"  zcta_adjacency: {a.total:,} pairs ({a.inserted:,} new, {a.updated:,} kept, "
        f"{a.deleted:,} removed)"
    )
    print(
        f"  without state: {result.zctas_without_state:,}; "
        f"without postal ZIP: {result.zctas_without_postal:,}"
    )
    cap = rules.serviceability.max_zcta_land_area_sq_miles
    print(f"  over {cap:g} sq mi (unserviceable): {result.unserviceable_land_area:,}")
    print(f"  import ids: {result.import_ids}")
    codes = {g.zcta for g in geography}
    for zcta in SPOT_CHECK_ZCTAS:
        if zcta in codes:
            neighbours = sorted(
                p.zcta_b if p.zcta_a == zcta else p.zcta_a
                for p in adjacency
                if zcta in (p.zcta_a, p.zcta_b)
            )
            print(f"  {zcta}: {len(neighbours)} neighbours {neighbours}")
    print(f"Done in {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
