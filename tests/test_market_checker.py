"""Sales-call market checker on fixture scenarios: one input, the full view, factual wording."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import load_business_rules
from app.fixtures import load_scenario
from app.ingest.seed import seed_scenario
from app.repositories.registry import load_snapshot
from app.schemas.market_check import MarketCheck, MarketQuery
from app.schemas.registry import RegistrySnapshot
from app.services.market import MarketGraph
from app.services.market_checker import (
    FORBIDDEN_WORDS,
    about,
    check_market,
    normalise_zips,
    resolve_city,
)

RULES = load_business_rules()
AS_OF = date(2026, 9, 29)


def setup(session: Session, scenario_id: str):
    loaded = load_scenario(scenario_id)
    market = MarketGraph.from_grid(loaded.market, RULES)
    if loaded.scenario.territories:
        with session.begin():
            seed_scenario(session, loaded)
        registry = load_snapshot(session, AS_OF)
    else:
        registry = RegistrySnapshot(as_of=AS_OF)
    return loaded, market, registry


def assert_wording(check: MarketCheck) -> None:
    text = " ".join(check.talking_points).lower()
    for word in FORBIDDEN_WORDS:
        assert word not in text.split() and f" {word} " not in f" {text} ", (word, text)
    assert check.approval_required is True
    if check.market_availability != "NO_MARKET_DATA":
        assert "approver" in text  # every real view ends with the approval reminder
    assert "not predict or guarantee" in check.disclaimer


def test_starting_zip_available(session: Session) -> None:
    _, market, registry = setup(session, "denver_suburban_available")
    check = check_market(MarketQuery(starting_zip="80123"), market, registry, RULES, AS_OF)
    assert check.market_availability == "AVAILABLE"
    assert check.resolution.method == "starting_zip" and check.resolution.starting_zip == "80123"
    proposal = check.suggested_territory
    assert proposal is not None and proposal.status == "PROPOSED"
    assert check.available_zips == sorted(proposal.zip_codes)
    assert check.reserved_zips == [] and check.protected_zips == [] and check.replacement_zips == []
    stats = check.market_stats
    assert stats.zcta_count == len(proposal.zips)
    assert stats.owner_occupied_households == proposal.aggregates.owner_occupied_households
    assert 0 < stats.pre_2000_share < 1 and stats.market_tier in "ABCD"
    assert any("owner-occupied households" in p for p in check.talking_points)
    assert any("availability in this market" in p for p in check.talking_points)
    assert "Conflicts: none." in check.talking_points
    assert_wording(check)
    again = check_market(MarketQuery(starting_zip="80123"), market, registry, RULES, AS_OF)
    assert again.model_dump() == check.model_dump()


def test_blocked_start_is_unavailable_with_alternatives(session: Session) -> None:
    _, market, registry = setup(session, "start_zip_protected")
    check = check_market(
        MarketQuery(starting_zip="80123", client_id="C-NEW"), market, registry, RULES, AS_OF
    )
    assert check.market_availability == "UNAVAILABLE" and check.suggested_territory is None
    assert [e.zcta for e in check.protected_zips] == ["80123"]
    assert check.protected_zips[0].client_business_name == "Peak Bath Solutions"
    assert check.replacement_zips and "80123" not in {s.zcta for s in check.replacement_zips}
    assert check.market_stats.zcta_count == 1  # the starting ZIP alone
    assert any("Peak Bath Solutions" in p and "internal" in p for p in check.talking_points)
    assert_wording(check)
    own = check_market(
        MarketQuery(starting_zip="80123", client_id="C-ALPHA"), market, registry, RULES, AS_OF
    )
    assert own.market_availability in ("AVAILABLE", "PARTIALLY_AVAILABLE")


def test_pasted_list_is_partially_available(session: Session) -> None:
    _, market, registry = setup(session, "reserved_expired")
    query = MarketQuery(requested_zips=["80123", "80127", "12345", "80127"], client_id="C-NEW")
    check = check_market(query, market, registry, RULES, AS_OF)
    assert check.market_availability == "PARTIALLY_AVAILABLE"
    assert check.resolution.starting_zip == "80123"
    assert check.resolution.requested_zips == ["80123", "80127"]
    assert check.resolution.unknown_zips == ["12345"]
    assert [e.zcta for e in check.reserved_zips] == ["80127"]
    assert check.reserved_zips[0].client_business_name == "Front Range Showers"
    assert check.reserved_zips[0].expired is True
    assert check.conflicts is not None and check.conflicts.conflict_count == 1
    members = set(check.suggested_territory.zip_codes)
    assert check.replacement_zips
    assert all(market.neighbours(s.zcta) & members for s in check.replacement_zips)
    assert any("Front Range Showers" in p for p in check.talking_points)
    assert_wording(check)


def test_city_query_starts_from_highest_ou_zcta(session: Session) -> None:
    loaded, market, registry = setup(session, "denver_suburban_available")
    littleton = [r for r in loaded.market.zctas if r.primary_city == "Littleton"]
    start, candidates = resolve_city(littleton, RULES)
    assert start == "80127" and len(candidates) == 5 and candidates[0] == "80127"
    check = check_market(
        MarketQuery(city="Littleton", state="co"),
        market, registry, RULES, AS_OF, city_start=start, city_candidates=candidates,
    )  # fmt: skip
    assert check.resolution.method == "city_state" and check.resolution.starting_zip == "80127"
    assert check.resolution.city_candidates == candidates
    assert check.market_availability == "AVAILABLE"
    assert check.suggested_territory.zips[0].zcta == "80127"
    assert_wording(check)


def test_no_market_data_paths(session: Session) -> None:
    _, market, registry = setup(session, "denver_suburban_available")
    unknown = check_market(MarketQuery(starting_zip="99999"), market, registry, RULES, AS_OF)
    assert unknown.market_availability == "NO_MARKET_DATA" and unknown.suggested_territory is None
    assert unknown.resolution.unknown_zips == ["99999"]
    nowhere = check_market(
        MarketQuery(city="Nowhere", state="CO"), market, registry, RULES, AS_OF, city_start=None
    )
    assert nowhere.market_availability == "NO_MARKET_DATA"
    assert "No ZCTA has primary city Nowhere, CO" in nowhere.resolution.note
    pasted = check_market(MarketQuery(requested_zips=["00001"]), market, registry, RULES, AS_OF)
    assert pasted.market_availability == "NO_MARKET_DATA"
    assert_wording(unknown)


def test_query_validation_and_helpers() -> None:
    with pytest.raises(ValidationError):
        MarketQuery()
    with pytest.raises(ValidationError):
        MarketQuery(starting_zip="80123", city="Littleton", state="CO")
    with pytest.raises(ValidationError):
        MarketQuery(city="Littleton")
    assert MarketQuery(requested_zips=["80123"]).method == "requested_zips"
    assert normalise_zips([" 80123 ", "80123", "abc", "80124"]) == (["80123", "80124"], ["abc"])
    assert about(41_237) == "about 41,200" and about(846) == "about 850"
