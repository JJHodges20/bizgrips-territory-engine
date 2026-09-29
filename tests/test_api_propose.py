"""POST /territories/propose on fixture-seeded databases."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.db import create_session_factory
from app.fixtures import load_scenario
from app.ingest.seed import seed_scenario
from app.main import create_app

AS_OF = "2026-09-29"


def seeded_client(engine, scenario: str) -> TestClient:
    with create_session_factory(engine)() as session, session.begin():
        seed_scenario(session, load_scenario(scenario))
    return TestClient(create_app(engine=engine))


def test_propose_returns_a_contiguous_recommendation(engine) -> None:
    with seeded_client(engine, "denver_suburban_available") as client:
        response = client.post(
            "/territories/propose",
            params={"as_of": AS_OF},
            json={"client_name": "Prospect Bath Co", "starting_zip": "80123"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "PROPOSED" and body["zips"][0]["zcta"] == "80123"
        assert body["target"]["status"] == "WITHIN_TARGET" and body["size_class"] == "STANDARD"
        assert body["aggregates"]["opportunity_units"] >= 20000
        assert body["approval_required"] is True and body["territory_id"] is None
        assert "not forecasts" in body["disclaimer"]
        assert client.get("/territories").json()["total"] == 0  # nothing persisted

        needs_client = client.post(
            "/territories/propose", params={"persist": "true"},
            json={"client_name": "Prospect Bath Co", "starting_zip": "80123"},
        )  # fmt: skip
        assert needs_client.status_code == 422
        persisted = client.post(
            "/territories/propose",
            params={"as_of": AS_OF, "persist": "true"},
            json={"client_name": "Prospect Bath Co", "client_id": "C-NEW", "starting_zip": "80123",
                  "size_class": "SMALL", "requested_zips": ["80124", "80130"]},
        ).json()  # fmt: skip
        assert persisted["territory_id"] == "T-000001"
        territory = client.get("/territories/T-000001").json()
        assert territory["status"] == "PROPOSED"
        assert territory["zips"] == sorted(z["zcta"] for z in persisted["zips"])
        assert territory["generation_snapshot"]["flags"] == persisted["flags"]
        reasons = {e["zcta"]: e["reason"] for e in persisted["excluded"]}
        assert reasons["80130"] == "NOT_CONTIGUOUS"


def test_propose_reports_blocked_start_and_unknown_zip(engine) -> None:
    with seeded_client(engine, "start_zip_protected") as client:
        blocked = client.post(
            "/territories/propose",
            params={"as_of": AS_OF},
            json={"client_name": "New Prospect LLC", "starting_zip": "80123"},
        ).json()
        assert blocked["status"] == "FAILED"
        assert blocked["failure"]["code"] == "START_ZIP_UNAVAILABLE"
        assert blocked["failure"]["blocking_territory_id"] == "T-000001"
        assert blocked["failure"]["suggestions"]
        unknown = client.post(
            "/territories/propose", json={"client_name": "Nobody", "starting_zip": "99999"}
        ).json()
        assert unknown["status"] == "FAILED" and unknown["failure"]["code"] == "NO_MARKET_DATA"
        assert client.post("/territories/propose", json={"starting_zip": "1"}).status_code == 422
