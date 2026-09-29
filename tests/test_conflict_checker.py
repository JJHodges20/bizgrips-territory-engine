"""Conflict checker on scenarios 2, 6 and 9 plus the endpoint (TERRITORY_ALGORITHM section 2)."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import load_business_rules
from app.db import create_session_factory
from app.enums import AssignmentStatus
from app.fixtures import load_scenario
from app.ingest.seed import seed_scenario
from app.main import create_app
from app.repositories.registry import load_snapshot
from app.schemas.registry import FLAG_RESERVATION_EXPIRED, BlockingInfo, RegistrySnapshot
from app.services.conflict_checker import check_conflicts
from app.services.market import MarketGraph

RULES = load_business_rules()
AS_OF = date(2026, 9, 29)


def scenario(session: Session, scenario_id: str) -> tuple[MarketGraph, RegistrySnapshot]:
    loaded = load_scenario(scenario_id)
    with session.begin():
        seed_scenario(session, loaded)
    return MarketGraph.from_grid(loaded.market, RULES), load_snapshot(session, AS_OF)


def test_scenario_2_protected_zip_with_nearest_replacements(session: Session) -> None:
    market, registry = scenario(session, "start_zip_protected")
    result = check_conflicts(["80123"], market, registry, RULES, client_id="C-NEW", as_of=AS_OF)
    assert [e.zcta for e in result.protected] == ["80123"] and result.conflict_count == 1
    assert result.protected[0].territory_id == "T-000001"
    assert result.protected[0].contract_end_date == date(2027, 2, 28)
    suggested = [s.zcta for s in result.suggestions]
    assert 0 < len(suggested) <= RULES.generator.replacement_suggestions
    assert not {"80123", "80120", "80128"} & set(suggested)  # never another client's ZIPs
    assert all(s.for_zcta == "80123" for s in result.suggestions)
    miles = [s.miles for s in result.suggestions]
    assert miles == sorted(miles)  # nearest first
    own = check_conflicts(["80123", "80120"], market, registry, RULES, client_id="C-ALPHA")
    assert own.own == ["80120", "80123"] or own.own == ["80123", "80120"]
    assert own.conflict_count == 0 and own.suggestions == []
    with pytest.raises(ValueError):
        check_conflicts(["80123"], market, registry, RULES, as_of=date(2026, 1, 1))


def test_scenario_9_expired_reservation_suggests_adjacent_replacements(session: Session) -> None:
    market, registry = scenario(session, "reserved_expired")
    result = check_conflicts(["80123", "80127"], market, registry, RULES, client_id="C-NEW")
    assert result.available == ["80123"]
    assert [e.zcta for e in result.reserved] == ["80127"] and result.conflict_count == 1
    assert result.reserved[0].client_business_name == "Front Range Showers"
    assert result.reserved[0].expired and result.reserved[0].expires_at == date(2026, 8, 14)
    assert result.flags == {"80127": FLAG_RESERVATION_EXPIRED}
    assert result.contiguous and result.components == [["80123", "80127"]]
    suggested = [s.zcta for s in result.suggestions]
    assert suggested and all(market.neighbours(z) & {"80123"} for z in suggested)
    assert not {"80127", "80129", "80123"} & set(suggested)
    assert all(s.tier != "U" for s in result.suggestions)
    reserving_client = check_conflicts(["80127"], market, registry, RULES, client_id="C-BRAVO")
    assert reserving_client.own == ["80127"] and reserving_client.conflict_count == 0


def test_scenario_6_contiguity_and_unknown_codes(session: Session) -> None:
    market, registry = scenario(session, "disconnected_request")
    result = check_conflicts(["80124", "80130", "99999", "80124"], market, registry, RULES)
    assert result.requested_count == 3 and result.unknown == ["99999"]
    assert result.available == ["80124", "80130"] and result.conflict_count == 0
    assert result.contiguous is False and result.components == [["80124"], ["80130"]]
    assert check_conflicts([], market, registry, RULES).requested_count == 0


def test_pending_release_past_its_date_counts_as_available() -> None:
    market = MarketGraph.from_grid(load_scenario("denver_suburban_available").market, RULES)
    info = BlockingInfo(
        zip="80124", territory_id="T-000007", client_id="C-OLD", client_business_name="Old Co",
        status=AssignmentStatus.PENDING_RELEASE, release_date=date(2026, 9, 1),
    )  # fmt: skip
    registry = RegistrySnapshot(as_of=AS_OF, blocking={"80124": info})
    result = check_conflicts(["80124"], market, registry, RULES, client_id="C-NEW")
    assert result.available == ["80124"] and result.conflict_count == 0
    still = RegistrySnapshot(as_of=date(2026, 8, 15), blocking={"80124": info})
    pending = check_conflicts(["80124"], market, still, RULES, client_id="C-NEW")
    assert [e.zcta for e in pending.pending_release] == ["80124"]
    assert pending.pending_release[0].release_date == date(2026, 9, 1)
    twice = check_conflicts(["80124"], market, still, RULES, client_id="C-NEW")
    assert twice.model_dump() == pending.model_dump()  # deterministic


def test_conflict_check_endpoint(engine) -> None:
    with create_session_factory(engine)() as session, session.begin():
        seed_scenario(session, load_scenario("reserved_expired"))
    with TestClient(create_app(engine=engine)) as client:
        body = client.post(
            "/conflicts/check",
            params={"as_of": "2026-09-29"},
            json={"zips": ["80123", "80127", "80127"], "client_id": "C-NEW"},
        ).json()
        assert body["checked"] == ["80123", "80127"] and body["as_of"] == "2026-09-29"
        assert body["available"] == ["80123"]
        assert [e["zcta"] for e in body["reserved"]] == ["80127"]
        assert body["flags"] == {"80127": "RESERVATION_EXPIRED"}
        assert body["suggestions"] and body["suggestions"][0]["for_zcta"] == "80127"
        assert "human-approved" in body["disclaimer"]
        assert client.post("/conflicts/check", json={"zips": ["8012"]}).status_code == 422
        assert client.post("/conflicts/check", json={"zips": []}).status_code == 422
