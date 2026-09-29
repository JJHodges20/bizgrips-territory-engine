"""Fixture markets load, are internally consistent, and encode the scenarios in TEST_MARKETS.md."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.fixtures import list_grids, list_scenarios, load_grid, load_scenario
from app.schemas.market import ZctaRecord

EXPECTED_SCENARIOS = {
    "denver_suburban_available",
    "start_zip_protected",
    "surrounded_by_protected",
    "rural_large_area",
    "missing_census_fields",
    "disconnected_request",
    "state_border_kansas_city",
    "symmetric_multi_path",
    "reserved_expired",
}


def test_expected_grids_and_scenarios_exist() -> None:
    assert set(list_grids()) == {
        "denver_suburban",
        "wyoming_rural",
        "kansas_city_border",
        "symmetric_chain",
    }
    assert set(list_scenarios()) == EXPECTED_SCENARIOS


@pytest.mark.parametrize(
    "grid_id", ["denver_suburban", "wyoming_rural", "kansas_city_border", "symmetric_chain"]
)
def test_grids_are_connected_with_symmetric_adjacency(grid_id: str) -> None:
    grid = load_grid(grid_id)
    codes = set(grid.records)
    assert grid.is_connected(codes)
    for a, b in grid.adjacency:
        assert b in grid.neighbors(a) and a in grid.neighbors(b)
    for record in grid.zctas:
        assert record.latitude is not None and record.longitude is not None
        assert record.land_area_sq_miles is not None and record.land_area_sq_miles > 0
        assert record.owner_occupancy_share is not None
        assert record.owner_45_plus_share is not None
        assert record.pre_2000_share is not None


def test_denver_grid_matches_documented_lattice() -> None:
    grid = load_grid("denver_suburban")
    assert len(grid.zctas) == 12 and len(grid.adjacency) == 17
    assert grid.neighbors("80123") == {"80120", "80122", "80124", "80127"}
    start = grid.records["80123"]
    # Worked example in SCORING_SPEC.md section 9.
    assert start.owner_occupied_households == 13400
    assert start.owner_households_age_45_plus == 9300
    assert start.homes_built_before_2000 == 9800
    assert start.median_household_income == 108000
    assert start.owner_occupancy_share == pytest.approx(0.8121, abs=1e-4)
    assert start.households_per_sq_mile == pytest.approx(1473.2, abs=0.1)


@pytest.mark.parametrize("scenario_id", sorted(EXPECTED_SCENARIOS))
def test_every_scenario_loads_and_resolves(scenario_id: str) -> None:
    loaded = load_scenario(scenario_id)
    assert loaded.scenario.scenario_id == scenario_id
    assert loaded.scenario.requests, "each scenario must contain at least one request"
    for request in loaded.scenario.requests:
        assert request.expected, f"{scenario_id}/{request.name} has no expectations"
    for territory in loaded.scenario.territories:
        assert loaded.market.is_connected(territory.zips), territory.territory_id


def test_surrounded_scenario_blocks_every_neighbour_of_start() -> None:
    loaded = load_scenario("surrounded_by_protected")
    blocked = {z for t in loaded.scenario.territories for z in t.zips}
    assert loaded.market.neighbors("80123") <= blocked


def test_missing_fields_overrides_null_out_values() -> None:
    market = load_scenario("missing_census_fields").market
    assert market.records["80124"].median_household_income is None
    assert market.records["80126"].pre_2000_share is None
    assert market.records["80112"].owner_occupancy_share is None
    assert market.records["80130"].owner_occupancy_share is None
    # Untouched ZCTAs keep their values.
    assert market.records["80123"].median_household_income == 108000


def test_symmetric_chain_candidates_are_true_mirrors() -> None:
    market = load_scenario("symmetric_multi_path").market
    left, right = market.records["40011"], market.records["40013"]
    ignore = {"zcta", "postal_zip", "longitude"}
    assert left.model_dump(exclude=ignore) == right.model_dump(exclude=ignore)
    centre = market.records["40012"].longitude
    assert abs(left.longitude - centre) == pytest.approx(abs(right.longitude - centre))


def test_rural_grid_exceeds_land_area_cap(rules) -> None:
    market = load_scenario("rural_large_area").market
    cap = rules.serviceability.max_zcta_land_area_sq_miles
    oversized = {z for z, r in market.records.items() if r.land_area_sq_miles > cap}
    assert oversized == {"82633", "82637", "82604"}


def test_reserved_expired_scenario_is_dated_before_as_of() -> None:
    loaded = load_scenario("reserved_expired")
    territory = loaded.scenario.territories[0]
    assert territory.status == "RESERVED"
    assert territory.reservation_expires_at < loaded.scenario.as_of


def test_record_validation_rejects_impossible_counts() -> None:
    with pytest.raises(ValidationError, match="exceeds"):
        ZctaRecord(zcta="00001", total_households=100, owner_occupied_households=200)
    with pytest.raises(ValidationError):
        ZctaRecord(zcta="1234")  # not five digits


def test_unknown_override_target_is_rejected() -> None:
    grid = load_grid("symmetric_chain")
    with pytest.raises(ValueError, match="unknown ZCTAs"):
        grid.with_overrides({"99999": {"median_household_income": None}})


def test_metric_lookup_matches_component_ramps(rules) -> None:
    record = load_grid("denver_suburban").records["80123"]
    for name in (
        "owner_concentration",
        "owner_age_45_plus",
        "housing_age",
        "purchasing_power",
        "serviceability",
    ):
        metric = rules.scoring.components.get(name).metric
        assert record.metric(metric) is not None
    with pytest.raises(KeyError):
        record.metric("nonsense")
