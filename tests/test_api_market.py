"""POST /market/check and the internal /sales page on fixture-seeded databases."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.api.market import parse_free_text
from app.db import create_session_factory
from app.fixtures import load_scenario
from app.ingest.seed import seed_scenario
from app.main import create_app

AS_OF = "2026-09-29"


def seeded_client(engine, scenario: str) -> TestClient:
    with create_session_factory(engine)() as session, session.begin():
        seed_scenario(session, load_scenario(scenario))
    return TestClient(create_app(engine=engine))


def test_parse_free_text() -> None:
    assert parse_free_text("80123").starting_zip == "80123"
    assert parse_free_text(" 80123, 80127 80128;80123 ").requested_zips == [
        "80123", "80127", "80128",
    ]  # fmt: skip
    city = parse_free_text("Highlands Ranch, co")
    assert (city.city, city.state) == ("Highlands Ranch", "CO")
    assert parse_free_text("") is None and parse_free_text("nonsense") is None
    assert parse_free_text("Littleton Colorado") is None


def test_market_check_json_in_well_under_a_minute(engine) -> None:
    with seeded_client(engine, "reserved_expired") as client:
        started = time.perf_counter()
        response = client.post(
            "/market/check",
            params={"as_of": AS_OF},
            json={"requested_zips": ["80123", "80127"], "client_id": "C-NEW"},
        )
        elapsed = time.perf_counter() - started
        assert response.status_code == 200, response.text
        assert elapsed < 5.0
        body = response.json()
        assert body["market_availability"] == "PARTIALLY_AVAILABLE"
        assert [e["zcta"] for e in body["reserved_zips"]] == ["80127"]
        assert body["reserved_zips"][0]["client_business_name"] == "Front Range Showers"
        assert body["replacement_zips"] and body["talking_points"]
        assert body["approval_required"] is True and "internal use only" in body["disclaimer"]
        assert client.post("/market/check", json={}).status_code == 422
        assert client.post("/market/check", json={"city": "Littleton"}).status_code == 422
        city = client.post(
            "/market/check", params={"as_of": AS_OF}, json={"city": "littleton", "state": "CO"}
        ).json()
        assert city["resolution"]["method"] == "city_state"
        assert city["resolution"]["starting_zip"] == "80127"


def test_sales_page_renders_the_full_view(engine) -> None:
    with seeded_client(engine, "denver_suburban_available") as client:
        blank = client.get("/sales")
        assert blank.status_code == 200 and "<form" in blank.text and "name='q'" in blank.text
        page = client.get("/sales", params={"q": "80123", "as_of": AS_OF})
        assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
        assert "AVAILABLE" in page.text and "owner-occupied households" in page.text
        assert "Suggested territory" in page.text and "80123" in page.text
        assert "Talking points" in page.text and "not predict or guarantee" in page.text
        small = client.get("/sales", params={"q": "Littleton, CO", "size_class": "SMALL"})
        assert small.status_code == 200 and "80127" in small.text
        bad = client.get("/sales", params={"q": "what is this"})
        assert bad.status_code == 200 and "Enter a 5-digit ZIP" in bad.text
        escaped = client.get("/sales", params={"q": "<script>alert(1)</script>"})
        assert "<script>" not in escaped.text and "&lt;script&gt;" in escaped.text
