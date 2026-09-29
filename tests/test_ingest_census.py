"""ACS parsing: sentinels, bucket sums, both backends, label checks and the demographics upsert."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import load_census_variables
from app.ingest.census import (
    CensusApiKeyRequired,
    ParseStats,
    build_records,
    check_labels,
    clean_value,
    fetch_api,
    merge_values,
    parse_api_table,
    read_summary_file,
    summary_column,
)
from app.ingest.store import ImportMeta, write_demographics
from app.models import DataFieldProvenance, DataSourceImport, ZctaMarket

FIXTURES = Path(__file__).parent / "fixtures"
VARIABLES = load_census_variables()
ENDPOINT = "https://api.census.gov/data/2023/acs/acs5"


def api_rows() -> list[list[str | None]]:
    return json.loads((FIXTURES / "acs_api_response.json").read_text(encoding="utf-8"))


def api_records() -> dict[str, dict[str, int | None]]:
    values = parse_api_table(
        api_rows(), geography=VARIABLES.geography, sentinels=VARIABLES.sentinels
    )
    return build_records(values, VARIABLES.fields)


def test_clean_value_sentinels_blanks_and_negatives() -> None:
    stats = ParseStats()
    sentinels = VARIABLES.sentinels
    assert clean_value("1234", sentinels, stats) == 1234
    assert clean_value("-666666666", sentinels, stats) is None
    assert clean_value(None, sentinels, stats) is None
    assert clean_value("", sentinels, stats) is None
    assert clean_value("-5", sentinels, stats) is None
    assert clean_value("abc", sentinels, stats) is None
    assert clean_value("98500.0", sentinels, stats) == 98500
    assert stats.as_dict() == {
        "values": 7,
        "sentinels": 1,
        "unexpected_negatives": 1,
        "unparseable": 1,
        "nulls": 2,
    }


def test_bucket_sums_and_missing_components() -> None:
    records = api_records()
    full = records["11111"]
    assert full["owner_households_age_45_plus"] == 3200 + 1500 + 1400 + 2400 + 900 + 200
    assert full["owner_households_age_55_plus"] == 6400
    assert full["owner_households_age_65_plus"] == 3500
    assert full["homes_built_before_2000"] == 13100
    assert full["homes_built_before_1980"] == 5600
    assert records["11112"]["median_household_income"] is None  # sentinel -> NULL
    partial = records["11113"]  # B25007_007E missing: sums that need it are NULL
    assert partial["owner_households_age_45_plus"] is None
    assert partial["owner_households_age_55_plus"] is None
    assert partial["owner_households_age_65_plus"] == 850
    assert set(records) == {"11111", "11112", "11113", "11114", "11115"}


def test_summary_file_backend_matches_api_backend() -> None:
    assert summary_column("B25007_006E") == "B25007_E006"
    with pytest.raises(ValueError):
        summary_column("B25007_006")
    parts = []
    for table in VARIABLES.tables:
        parts.append(
            read_summary_file(
                FIXTURES / "acs_summary" / f"acsdt5y2023-{table.lower()}.dat",
                variables=[v for v in VARIABLES.all_variables if v.startswith(table + "_")],
                zcta_geo_id_prefix=VARIABLES.summary_file.zcta_geo_id_prefix,
                sentinels=VARIABLES.sentinels,
            )
        )
    merged = merge_values(parts)
    assert set(merged) == {"11111", "11112", "11113", "11114", "11115"}  # state/county rows skipped
    assert build_records(merged, VARIABLES.fields) == api_records()


def test_summary_file_refuses_missing_columns(tmp_path: Path) -> None:
    bad = tmp_path / "acsdt5y2023-b25003.dat"
    bad.write_text("GEO_ID|B25003_E001|B25003_M001\n860Z200US11111|10|1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="B25003_E002"):
        read_summary_file(
            bad,
            variables=["B25003_001E", "B25003_002E"],
            zcta_geo_id_prefix="860Z200US",
            sentinels=VARIABLES.sentinels,
        )


def test_label_checks_detect_bucket_drift() -> None:
    labels = json.loads((FIXTURES / "acs_variable_labels.json").read_text(encoding="utf-8"))
    expected = VARIABLES.label_checks()
    assert check_labels(labels, expected) == []
    drifted = {**labels, "B25034_005E": "Estimate!!Total:!!Built 2014 or later"}
    problems = check_labels(drifted, expected)
    assert len(problems) == 1 and problems[0].startswith("B25034_005E")
    assert check_labels({}, {"B25003_002E": "Owner occupied"}) == [
        "B25003_002E: no label available"
    ]


def test_fetch_api_batches_and_merges() -> None:
    rows = api_rows()
    header = rows[0]
    calls: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        calls.append(params)
        wanted = params["get"].split(",")
        idx = [header.index(v) for v in wanted] + [len(header) - 1]
        return httpx.Response(200, json=[[row[i] for i in idx] for row in rows])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        values = fetch_api(
            client,
            endpoint=ENDPOINT,
            variables=VARIABLES.all_variables,
            geography=VARIABLES.geography,
            api_key="k",
            sentinels=VARIABLES.sentinels,
            batch_size=8,
        )
    assert len(calls) == 3 and all(len(c["get"].split(",")) <= 8 for c in calls)
    assert all(c["key"] == "k" and c["for"] == "zip code tabulation area:*" for c in calls)
    assert build_records(values, VARIABLES.fields) == api_records()


def test_fetch_api_reports_missing_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        location = "https://api.census.gov/data/missing_key.html"
        return httpx.Response(302, headers={"Location": location})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(CensusApiKeyRequired):
            fetch_api(
                client,
                endpoint=ENDPOINT,
                variables=["B25003_001E"],
                geography=VARIABLES.geography,
                api_key=None,
                sentinels=VARIABLES.sentinels,
                retries=0,
            )


def _write(session: Session) -> None:
    field_sources = {n: (f.table, list(f.variables)) for n, f in VARIABLES.fields.items()}
    with session.begin():
        write_demographics(
            session,
            records=api_records(),
            field_columns=list(VARIABLES.fields),
            field_sources=field_sources,
            meta=ImportMeta("acs/acs5", "2023", variables=field_sources),
            source_release="acs5-2023",
        )


def test_write_demographics_upserts_with_provenance(session: Session) -> None:
    _write(session)
    _write(session)  # second run: same rows, one more import record
    assert session.scalar(select(func.count()).select_from(ZctaMarket)) == 5
    assert session.scalar(select(func.count()).select_from(DataSourceImport)) == 2
    row = session.get(ZctaMarket, "11111")
    assert row is not None
    assert row.owner_households_age_45_plus == 9600
    assert row.owner_occupancy_percent == pytest.approx(81.21)
    assert row.households_per_sq_mile is None  # no geography yet
    assert row.source_release == "acs5-2023" and row.demographics_import_id == 2
    assert session.get(ZctaMarket, "11112").median_household_income is None
    provenance = session.get(DataFieldProvenance, "owner_households_age_45_plus")
    assert provenance is not None and provenance.table_id == "B25007"
    assert provenance.variables_json[0] == "B25007_006E" and provenance.import_id == 2
