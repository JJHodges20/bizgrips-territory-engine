"""Registry endpoints on fixture-seeded databases: proposals, transitions, availability."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.db import create_session_factory
from app.fixtures import load_scenario
from app.ingest.seed import seed_scenario
from app.main import create_app

AS_OF = "2026-09-29"


@contextmanager
def client_for(engine: Engine, scenario: str) -> Iterator[TestClient]:
    with create_session_factory(engine)() as session, session.begin():
        seed_scenario(session, load_scenario(scenario))
    with TestClient(create_app(engine=engine)) as client:
        yield client


def proposal(client: TestClient, zips: list[str], client_id: str = "C-NEW") -> dict:
    return client.post(
        "/territories",
        params={"as_of": AS_OF},
        json={
            "client_id": client_id,
            "client_business_name": f"{client_id} Baths",
            "starting_zip": zips[0],
            "zips": zips,
        },
    ).json()


def test_proposal_reserve_activate_release_over_the_api(engine) -> None:
    with client_for(engine, "denver_suburban_available") as client:
        created = client.post(
            "/territories",
            params={"as_of": AS_OF},
            json={
                "client_id": "C-NEW",
                "client_business_name": "New Prospect LLC",
                "starting_zip": "80123",
                "territory_size_class": "STANDARD",
                "zips": ["80123", "80120", "80127"],
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        tid = body["territory_id"]
        assert body["status"] == "PROPOSED" and body["zips"] == ["80120", "80123", "80127"]
        assert body["zip_count"] == 3 and body["flags"] == []

        missing = client.post(f"/territories/{tid}/reserve", json={"approved_by": ""})
        assert missing.status_code == 422
        reserved = client.post(
            f"/territories/{tid}/reserve",
            params={"as_of": AS_OF},
            json={"approved_by": "Sales Manager"},
        ).json()
        assert reserved["status"] == "RESERVED"
        assert reserved["reservation_expires_at"] == "2026-10-29"
        assert [a["status"] for a in reserved["assignments"]] == ["RESERVED"] * 3

        blocked = client.get(
            "/zips/80120/availability", params={"client_id": "C-OTHER", "as_of": AS_OF}
        ).json()
        assert blocked["availability"] == "RESERVED" and blocked["is_conflict"] is True
        assert blocked["blocking"]["territory_id"] == tid
        own = client.get("/zips/80120/availability", params={"client_id": "C-NEW"}).json()
        assert own["own"] is True and own["is_conflict"] is False

        again = client.post(f"/territories/{tid}/reserve", json={"approved_by": "Sales Manager"})
        assert again.status_code == 409 and again.json()["detail"]["code"] == "INVALID_TRANSITION"

        active = client.post(
            f"/territories/{tid}/activate",
            params={"as_of": AS_OF},
            json={"approved_by": "Owner", "contract_start_date": "2026-10-01"},
        ).json()
        assert active["status"] == "ACTIVE_PROTECTED"
        pending = client.post(
            f"/territories/{tid}/pending-release",
            params={"as_of": "2027-01-10"},
            json={"actor": "Owner", "reason": "offboarding"},
        ).json()
        assert pending["status"] == "PENDING_RELEASE" and pending["release_date"] == "2027-02-09"
        early = client.post(
            f"/territories/{tid}/release", params={"as_of": "2027-02-01"}, json={"actor": "Owner"}
        )
        assert early.status_code == 409
        flags = client.get("/registry/flags", params={"as_of": "2027-02-09"}).json()
        assert [t["territory_id"] for t in flags["releases_due"]] == [tid]
        swept = client.post("/registry/sweep", params={"as_of": "2027-02-09"}).json()
        assert swept["released"] == [tid]
        final = client.get(f"/territories/{tid}").json()
        assert final["status"] == "RELEASED"
        assert client.get("/zips/80120/availability").json()["availability"] == "AVAILABLE"
        listing = client.get("/territories", params={"status": "RELEASED"}).json()
        assert listing["total"] == 1 and listing["items"][0]["territory_id"] == tid


def test_conflicts_and_errors_over_the_api(engine) -> None:
    with client_for(engine, "start_zip_protected") as client:
        conflict = client.post(
            "/territories",
            json={
                "client_id": "C-NEW",
                "client_business_name": "New Prospect LLC",
                "starting_zip": "80123",
                "zips": ["80123", "80122"],
            },
        )
        assert conflict.status_code == 409
        detail = conflict.json()["detail"]
        assert detail["code"] == "ZIP_CONFLICT"
        assert detail["details"][0]["blocking"]["client_business_name"] == "Peak Bath Solutions"
        assert client.get("/territories/T-000009").status_code == 404
        assert client.get("/territories/bogus").status_code == 422
        assert client.get("/zips/8012/availability").status_code == 422
        unknown = client.post(
            "/territories",
            json={"client_id": "C", "client_business_name": "C", "starting_zip": "99999",
                  "zips": ["99999"]},
        )  # fmt: skip
        assert unknown.status_code == 422 and unknown.json()["detail"]["code"] == "NO_MARKET_DATA"
        bad_exception = client.post(
            "/territories/T-000001/exceptions",
            json={"exception_type": "NOT_A_THING", "approved_by": "Owner", "reason": "x"},
        )
        assert bad_exception.status_code == 422
        assert bad_exception.json()["detail"]["code"] == "EXCEPTION_NOT_ALLOWED"


def test_expired_reservation_flagged_and_released_by_a_human(engine) -> None:
    with client_for(engine, "reserved_expired") as client:
        blocked = client.get(
            "/zips/80127/availability", params={"client_id": "C-NEW", "as_of": AS_OF}
        ).json()
        assert blocked["availability"] == "RESERVED" and blocked["flags"] == ["RESERVATION_EXPIRED"]
        assert blocked["blocking"]["client_business_name"] == "Front Range Showers"
        flags = client.get("/registry/flags", params={"as_of": AS_OF}).json()
        assert [t["territory_id"] for t in flags["expired_reservations"]] == ["T-000002"]
        assert client.post("/registry/sweep", params={"as_of": AS_OF}).json()["released"] == []
        cancelled = client.post(
            "/territories/T-000002/cancel",
            params={"as_of": AS_OF},
            json={"actor": "Sales Manager", "reason": "prospect went cold"},
        ).json()
        assert cancelled["status"] == "CANCELLED"
        assert all(a["date_released"] == AS_OF for a in cancelled["assignments"])
        assert client.get("/zips/80127/availability").json()["availability"] == "AVAILABLE"
        created = proposal(client, ["80127", "80129"], client_id="C-LATE")
        assert created["status"] == "PROPOSED"
