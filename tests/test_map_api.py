"""Milestone 8 backend: map endpoints, custom-group evaluation, static workspace, JS syntax."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import create_session_factory
from app.fixtures import load_scenario
from app.ingest.seed import seed_scenario
from app.main import create_app
from app.models import ZctaMarket

ROOT = Path(__file__).resolve().parents[1]
AS_OF = "2026-09-29"


def square(lat: float, lon: float, size: float = 0.02) -> str:
    ring = [[lon, lat], [lon + size, lat], [lon + size, lat + size], [lon, lat + size], [lon, lat]]
    return json.dumps({"type": "Polygon", "coordinates": [ring]})


def seed_with_geometry(engine, scenario: str) -> None:
    """Seed a scenario and attach synthetic square polygons around each ZCTA centroid."""
    with create_session_factory(engine)() as session, session.begin():
        seed_scenario(session, load_scenario(scenario))
        for row in session.query(ZctaMarket).all():
            if row.latitude is None:
                continue
            row.geometry_geojson = square(row.latitude - 0.01, row.longitude - 0.01)
            row.bbox_min_lon, row.bbox_min_lat = row.longitude - 0.01, row.latitude - 0.01
            row.bbox_max_lon, row.bbox_max_lat = row.longitude + 0.01, row.latitude + 0.01
            row.market_tier, row.opportunity_score = "A", 80.0


def test_viewport_features_carry_availability_and_scores(engine) -> None:
    seed_with_geometry(engine, "reserved_expired")
    with TestClient(create_app(engine=engine)) as client:
        response = client.get(
            "/map/zctas",
            params={"bbox": "-105.2,39.5,-104.9,39.7", "as_of": AS_OF, "client_id": "C-NEW"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["type"] == "FeatureCollection" and body["meta"]["count"] == 12
        by_zcta = {f["properties"]["zcta"]: f["properties"] for f in body["features"]}
        assert by_zcta["80127"]["availability"] == "RESERVED"
        assert by_zcta["80127"]["client_business_name"] == "Front Range Showers"
        assert by_zcta["80127"]["flags"] == ["RESERVATION_EXPIRED"]
        assert (
            by_zcta["80123"]["availability"] == "AVAILABLE"
            and by_zcta["80123"]["market_tier"] == "A"
        )
        assert body["features"][0]["geometry"]["type"] == "Polygon"
        narrow = client.get("/map/zctas", params={"bbox": "-105.09,39.60,-105.07,39.63"}).json()
        assert narrow["meta"]["count"] < 12 and "80123" in {f["id"] for f in narrow["features"]}
        assert client.get("/map/zctas", params={"bbox": "-110,35,-100,45"}).status_code == 400
        assert client.get("/map/zctas", params={"bbox": "1,2,3"}).status_code == 400
        assert client.get("/map/zctas", params={"bbox": "-105,40,-106,41"}).status_code == 400


def test_territory_shape_and_locate(engine) -> None:
    seed_with_geometry(engine, "reserved_expired")
    with TestClient(create_app(engine=engine)) as client:
        shape = client.get("/map/territories/T-000002", params={"as_of": AS_OF}).json()
        assert shape["territory"]["client_business_name"] == "Front Range Showers"
        assert shape["territory"]["flags"] == ["RESERVATION_EXPIRED"]
        assert sorted(f["id"] for f in shape["features"]) == ["80127", "80129"]
        assert shape["bounds"][0][0] < shape["bounds"][1][0]
        assert client.get("/map/territories/T-000009").status_code == 404
        zcta = client.get("/map/locate", params={"q": "80123"}).json()
        assert zcta["kind"] == "zcta" and zcta["label"].startswith("80123 Littleton")
        city = client.get("/map/locate", params={"q": "Littleton, co"}).json()
        assert city["kind"] == "city" and len(city["zctas"]) == 5 and city["bounds"]
        assert client.get("/map/locate", params={"q": "Nowhere, CO"}).status_code == 404
        assert client.get("/map/locate", params={"q": "just words"}).status_code == 422


def test_evaluate_custom_grouping(engine) -> None:
    seed_with_geometry(engine, "reserved_expired")
    with TestClient(create_app(engine=engine)) as client:
        body = client.post(
            "/territories/evaluate",
            params={"as_of": AS_OF},
            json={
                "zips": ["80123", "80120", "80127", "99999"],
                "client_id": "C-NEW",
                "size_class": "SMALL",
            },
        ).json()
        assert body["zips"] == ["80123", "80120", "80127"] and body["unknown_zips"] == ["99999"]
        assert body["contiguous"] is True and body["can_save"] is False
        assert {"CONTAINS_BLOCKED", "CONTAINS_UNKNOWN"} <= set(body["flags"])
        assert body["target"]["size_class"] == "SMALL" and body["aggregates"]["zcta_count"] == 3
        statuses = {z["zcta"]: z["availability"] for z in body["per_zip"]}
        assert statuses["80127"] == "RESERVED" and statuses["80123"] == "AVAILABLE"
        assert body["conflicts"]["conflict_count"] == 1 and body["conflicts"]["suggestions"]
        clean = client.post("/territories/evaluate", json={"zips": ["80123", "80120"]}).json()
        assert clean["can_save"] is True and clean["conflicts"]["conflict_count"] == 0
        assert clean["target"]["status"] in (
            "BELOW_TARGET",
            "WITHIN_TARGET",
            "BELOW_MINIMUM_VIABLE",
        )
        apart = client.post("/territories/evaluate", json={"zips": ["80123", "80130"]}).json()
        assert apart["contiguous"] is False and "NOT_CONTIGUOUS" in apart["flags"]
        assert client.post("/territories/evaluate", json={"zips": []}).status_code == 422


def test_workspace_is_served(engine) -> None:
    with TestClient(create_app(engine=engine)) as client:
        assert client.get("/", follow_redirects=False).status_code == 307
        page = client.get("/app")
        assert page.status_code == 200 and "Territory Workspace" in page.text
        assert client.get("/app/map").status_code == 200
        assert client.get("/static/js/main.js").status_code == 200
        assert client.get("/static/vendor/leaflet/leaflet.js").status_code == 200
        assert client.get("/static/css/styles.css").headers["content-type"].startswith("text/css")


@pytest.mark.parametrize("name", ["api", "ui", "main", "registry", "map", "sales"])
def test_javascript_modules_parse(name: str) -> None:
    esprima = pytest.importorskip("esprima")
    source = (ROOT / "app" / "static" / "js" / f"{name}.js").read_text(encoding="utf-8")
    esprima.parseModule(source)  # raises on a syntax error
    assert "export" in source


def test_config_script_parses() -> None:
    esprima = pytest.importorskip("esprima")
    esprima.parseScript((ROOT / "app" / "static" / "config.js").read_text(encoding="utf-8"))
