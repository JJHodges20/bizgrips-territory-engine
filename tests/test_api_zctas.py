"""Milestone 2 read API against a fixture-seeded in-memory SQLite database."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.db import create_session_factory
from app.fixtures import LoadedScenario, load_scenario
from app.ingest.seed import seed_scenario
from app.main import create_app
from app.models import DataFieldProvenance, ZctaMarket
from app.schemas.api import MARKET_DATA_FIELDS


def seed(engine: Engine, scenario_id: str) -> LoadedScenario:
    loaded = load_scenario(scenario_id)
    with create_session_factory(engine)() as session, session.begin():
        seed_scenario(session, loaded)
    return loaded


@contextmanager
def client_for(engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(engine=engine)) as client:
        yield client


@pytest.fixture
def denver(engine: Engine) -> LoadedScenario:
    return seed(engine, "denver_suburban_available")


def test_get_zcta_returns_all_columns_shares_and_no_missing_fields(engine, denver) -> None:
    record = denver.market.records["80123"]
    with client_for(engine) as client:
        response = client.get("/zctas/80123")
    assert response.status_code == 200
    body = response.json()
    assert body["zcta"] == "80123" and body["primary_city"] == record.primary_city
    assert body["state"] == "CO" and body["total_households"] == record.total_households
    assert body["owner_households_age_45_plus"] == record.owner_households_age_45_plus
    assert body["shares"]["owner_occupancy_share"] == round(record.owner_occupancy_share, 4)
    assert body["shares"]["pre_2000_share"] == round(record.pre_2000_share, 4)
    assert body["missing_fields"] == []
    assert body["geometry_geojson"] is None and body["market_tier"] is None
    assert body["source_release"] == "fixture:denver_suburban_available"
    assert body["demographics_import_id"] == 1 and body["unserviceable_land_area"] is False
    for column in MARKET_DATA_FIELDS:
        assert column in body


def test_unknown_and_malformed_codes(engine, denver) -> None:
    with client_for(engine) as client:
        missing = client.get("/zctas/00000")
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "NO_MARKET_DATA"
        assert client.get("/zctas/abcde").status_code == 422
        assert client.get("/zctas/1234").status_code == 422
        assert client.get("/zctas/00000/neighbors").status_code == 404


def test_list_filters_and_pagination(engine, denver) -> None:
    codes = sorted(denver.market.records)
    littleton = sorted(
        z
        for z, r in denver.market.records.items()
        if (r.primary_city or "").startswith("Littleton")
    )
    with client_for(engine) as client:
        body = client.get("/zctas", params={"state": "co"}).json()
        assert body["total"] == len(codes) and [i["zcta"] for i in body["items"]] == codes
        assert body["filters"] == {"state": "CO", "city": None, "tier": None}
        page = client.get("/zctas", params={"state": "CO", "limit": 5, "offset": 10}).json()
        assert page["total"] == len(codes) and [i["zcta"] for i in page["items"]] == codes[10:15]
        assert client.get("/zctas", params={"state": "WY"}).json()["total"] == 0
        city = client.get("/zctas", params={"city": "litt"}).json()
        assert [i["zcta"] for i in city["items"]] == littleton and littleton
        assert client.get("/zctas", params={"tier": "A"}).json()["total"] == 0  # unscored yet
        assert client.get("/zctas", params={"tier": "Z"}).status_code == 422
        assert client.get("/zctas", params={"limit": 0}).status_code == 422
        with create_session_factory(engine)() as session, session.begin():
            session.get(ZctaMarket, "80123").market_tier = "A"
        tier = client.get("/zctas", params={"tier": "A", "state": "co"}).json()
        assert tier["total"] == 1 and tier["items"][0]["zcta"] == "80123"


def test_neighbors_match_fixture_adjacency_and_are_symmetric(engine, denver) -> None:
    expected = sorted(denver.market.neighbors("80123"))
    with client_for(engine) as client:
        body = client.get("/zctas/80123/neighbors").json()
        assert body["zcta"] == "80123" and body["count"] == len(expected)
        assert [n["zcta"] for n in body["neighbors"]] == expected
        assert all(
            n["primary_city"] and n["shared_boundary_length_m"] is None for n in body["neighbors"]
        )
        for code in expected:
            back = client.get(f"/zctas/{code}/neighbors").json()
            assert "80123" in [n["zcta"] for n in back["neighbors"]]


def test_geometry_only_on_request(engine, denver) -> None:
    with create_session_factory(engine)() as session, session.begin():
        session.get(ZctaMarket, "80123").geometry_geojson = '{"type":"Polygon","coordinates":[]}'
    with client_for(engine) as client:
        assert client.get("/zctas/80123").json()["geometry_geojson"] is None
        with_geometry = client.get("/zctas/80123", params={"include_geometry": "true"}).json()
        assert with_geometry["geometry_geojson"].startswith('{"type":"Polygon"')


def test_imports_and_field_provenance(engine, denver) -> None:
    with create_session_factory(engine)() as session, session.begin():
        session.add(
            DataFieldProvenance(
                field_name="owner_occupied_households",
                dataset="acs/acs5",
                vintage="2023",
                table_id="B25003",
                variables_json=["B25003_002E"],
                import_id=1,
            )
        )
    with client_for(engine) as client:
        body = client.get("/imports").json()
        assert body["total"] == 1 and body["items"][0]["dataset"] == "fixture"
        assert body["items"][0]["vintage"] == "denver_suburban_available"
        assert body["items"][0]["record_count"] == len(denver.market.records)
        assert client.get("/imports", params={"dataset": "acs/acs5"}).json()["total"] == 0
        fields = client.get("/imports/fields").json()["items"]
        assert fields == [
            {
                **fields[0],
                "field_name": "owner_occupied_households",
                "table_id": "B25003",
                "variables_json": ["B25003_002E"],
                "import_id": 1,
            }
        ]


def test_missing_source_fields_are_listed_explicitly(engine) -> None:
    loaded = seed(engine, "missing_census_fields")
    with_gaps = {
        z: [f for f in MARKET_DATA_FIELDS if getattr(r, f, None) is None]
        for z, r in loaded.market.records.items()
    }
    assert any(with_gaps.values())  # the scenario really nulls something
    with client_for(engine) as client:
        for zcta, expected in with_gaps.items():
            body = client.get(f"/zctas/{zcta}").json()
            assert body["missing_fields"] == expected, zcta
            if "total_households" in expected:
                assert body["shares"]["owner_occupancy_share"] is None
