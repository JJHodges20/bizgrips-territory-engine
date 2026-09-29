"""Import ACS 5-Year demographic data for every ZCTA (Milestone 1).

    venv/Scripts/python.exe scripts/import_census.py [--source auto|api|summary-file]
    venv/Scripts/python.exe scripts/import_census.py --dry-run
    venv/Scripts/python.exe scripts/import_census.py \
        --api-response tests/fixtures/acs_api_response.json

Steps: validate variable labels against the API's variables metadata (`label_contains`); pull
every ZCTA either from the Data API (batches of <= 50 variables; needs a free CENSUS_API_KEY)
or from the ACS Summary File table-based files (no key; one download per table, cached in
data/raw/acs_sf); convert sentinels to NULL; sum bucket variables; derive owner_occupancy_percent
and households_per_sq_mile; upsert zcta_markets; record data_source_imports and
data_field_provenance. `--vintage` overrides the YAML with a warning; the label check must pass.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings, load_census_variables  # noqa: E402
from app.config.census_variables import CensusVariables  # noqa: E402
from app.db import create_db_engine, create_session_factory, init_db  # noqa: E402
from app.ingest.census import (  # noqa: E402
    API_TIMEOUT,
    AcsValues,
    CensusApiError,
    ParseStats,
    build_records,
    check_labels,
    fetch_api,
    fetch_variable_labels,
    merge_values,
    parse_api_table,
    read_summary_file,
)
from app.ingest.download import combined_checksum, download_file  # noqa: E402
from app.ingest.store import ImportMeta, write_demographics  # noqa: E402
from app.schemas.market import ZctaRecord  # noqa: E402

EXIT_LABELS_MISMATCH = 3
EXIT_FETCH_FAILED = 4


def print_plan(variables: CensusVariables, vintage: int, source: str, api_key: str | None) -> None:
    print("ACS import plan")
    print(f"  dataset:   {variables.dataset} vintage {vintage} ({variables.release_label})")
    print(f"  endpoint:  {variables.endpoint(vintage)}")
    print(f"  geography: {variables.geography}")
    print(f"  source:    {source}; api key {'set' if api_key else 'not set'}")
    print(f"  tables:    {', '.join(variables.tables)}; variables: {len(variables.all_variables)}")
    for name, field in variables.fields.items():
        print(f"    {name:32s} {field.table:7s} {'+'.join(field.variables)}")
    if vintage != variables.vintage:
        print(
            f"  WARNING: --vintage {vintage} differs from census_variables.yaml "
            f"({variables.vintage}); label checks must pass before any data is written."
        )


def validate_labels(variables: CensusVariables, vintage: int) -> list[str]:
    """Problems found when comparing live variable labels with `label_contains`."""
    with httpx.Client(timeout=API_TIMEOUT, follow_redirects=False) as client:
        labels = fetch_variable_labels(
            client, endpoint=variables.endpoint(vintage), variables=variables.label_checks()
        )
    return check_labels(labels, variables.label_checks())


def count_inconsistent(records: dict[str, dict[str, int | None]]) -> int:
    """Rows whose values violate ZctaRecord's cross-table sanity checks (reported, still stored)."""
    bad = 0
    for zcta, record in records.items():
        try:
            ZctaRecord(zcta=zcta, **record)
        except ValidationError:
            bad += 1
    return bad


def fetch_values(
    variables: CensusVariables,
    vintage: int,
    source: str,
    api_key: str | None,
    args: argparse.Namespace,
) -> AcsValues:
    stats = ParseStats()
    if args.api_response:
        rows = json.loads(Path(args.api_response).read_text(encoding="utf-8"))
        values = parse_api_table(
            rows, geography=variables.geography, sentinels=variables.sentinels, stats=stats
        )
        return AcsValues(values, "api-file", vintage, [args.api_response], None, stats)
    if source == "api":
        endpoint = variables.endpoint(vintage)
        with httpx.Client(timeout=API_TIMEOUT, follow_redirects=False) as client:
            values = fetch_api(
                client,
                endpoint=endpoint,
                variables=variables.all_variables,
                geography=variables.geography,
                api_key=api_key,
                sentinels=variables.sentinels,
                stats=stats,
            )
        return AcsValues(values, "api", vintage, [endpoint], None, stats)
    if vintage < variables.summary_file.min_vintage:
        raise CensusApiError(
            f"summary-file layout needs vintage >= {variables.summary_file.min_vintage}"
        )
    raw_dir = Path(args.raw_dir) if args.raw_dir else get_settings().raw_data_dir
    folder = Path(args.summary_dir) if args.summary_dir else raw_dir / "acs_sf"
    parts, urls, digests = [], [], []
    for table in variables.tables:
        url = variables.summary_file.url(vintage, table)
        filename = url.rsplit("/", 1)[-1]
        if args.summary_dir:
            path = folder / filename
        else:
            result = download_file(url, folder / filename, refresh=args.refresh)
            path = result.path
            digests.append(result.sha256)
            print(f"  {table}: {result.status} {filename} ({result.size_bytes:,} bytes)")
        urls.append(url)
        parts.append(
            read_summary_file(
                path,
                variables=[v for v in variables.all_variables if v.startswith(table + "_")],
                zcta_geo_id_prefix=variables.summary_file.zcta_geo_id_prefix,
                sentinels=variables.sentinels,
                stats=stats,
            )
        )
    checksum = combined_checksum(digests) if digests else None
    return AcsValues(merge_values(parts), "summary-file", vintage, urls, checksum, stats)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--vintage", type=int, default=None, help="override the ACS vintage")
    parser.add_argument("--source", choices=("auto", "api", "summary-file"), default="auto")
    parser.add_argument("--api-key", default=None, help="Census API key (else CENSUS_API_KEY)")
    parser.add_argument("--refresh", action="store_true", help="re-download cached summary files")
    parser.add_argument("--skip-label-check", action="store_true", help="offline use only")
    parser.add_argument("--raw-dir", default=None, help="override data/raw")
    parser.add_argument("--summary-dir", default=None, help="local folder of acsdt5y*.dat files")
    parser.add_argument("--api-response", default=None, help="saved API JSON instead of network")
    parser.add_argument("--database-url", default=None, help="override DATABASE_URL")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and exit 0")
    args = parser.parse_args(argv)

    variables = load_census_variables()
    settings = get_settings()
    vintage = args.vintage or variables.vintage
    api_key = args.api_key or settings.census_api_key
    source = args.source
    if source == "auto":
        source = "api" if api_key else "summary-file"
    print_plan(variables, vintage, source, api_key)
    if args.dry_run:
        return 0
    started = time.perf_counter()

    if args.skip_label_check:
        print("Label check SKIPPED (--skip-label-check)")
    else:
        try:
            problems = validate_labels(variables, vintage)
        except CensusApiError as exc:
            print(f"Label check FAILED to fetch metadata: {exc}")
            return EXIT_LABELS_MISMATCH
        if problems:
            print("Label check FAILED; nothing written:")
            for problem in problems:
                print(f"  {problem}")
            return EXIT_LABELS_MISMATCH
        print(f"Label check passed for {len(variables.label_checks())} variables")

    try:
        pulled = fetch_values(variables, vintage, source, api_key, args)
    except (CensusApiError, OSError, ValueError) as exc:
        print(f"Fetch FAILED ({source}): {exc}")
        return EXIT_FETCH_FAILED
    elapsed = time.perf_counter() - started
    print(f"Fetched {len(pulled.values):,} ZCTAs via {pulled.backend} ({elapsed:.1f}s)")
    print(f"  value cleaning: {pulled.stats.as_dict()}")

    records = build_records(pulled.values, variables.fields)
    inconsistent = count_inconsistent(records)
    field_sources = {name: (f.table, list(f.variables)) for name, f in variables.fields.items()}
    label = variables.release_label if vintage == variables.vintage else f"ACS 5-Year {vintage}"
    meta = ImportMeta(
        dataset=variables.dataset,
        vintage=str(vintage),
        release_label=label,
        source_url="; ".join(pulled.source_urls),
        checksum=pulled.checksum,
        notes=(
            f"backend={pulled.backend}; cleaning={pulled.stats.as_dict()}; "
            f"inconsistent_rows={inconsistent}"
        ),
        variables=field_sources,
    )
    engine = create_db_engine(args.database_url)
    init_db(engine)
    factory = create_session_factory(engine)
    with factory() as session, session.begin():
        result = write_demographics(
            session,
            records=records,
            field_columns=list(variables.fields),
            field_sources=field_sources,
            meta=meta,
            source_release=f"acs5-{vintage}",
        )
    engine.dispose()
    print("Written:")
    print(
        f"  zcta_markets: {result.markets.inserted:,} inserted, {result.markets.updated:,} "
        f"updated (import id {result.import_id})"
    )
    print(
        f"  ZCTAs without geography: {result.zctas_without_geography:,}; "
        f"cross-table inconsistent rows: {inconsistent:,}"
    )
    nulls = ", ".join(f"{k}={v:,}" for k, v in result.null_counts.items() if v)
    print(f"  NULL counts: {nulls or 'none'}")
    print(f"Done in {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
