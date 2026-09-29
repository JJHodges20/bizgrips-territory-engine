"""SCORING_SPEC.md acceptance: worked example, missing data, determinism, weight sensitivity."""

from __future__ import annotations

import pytest

from app.config import BusinessRules, load_business_rules
from app.config.business_rules import ComponentRamp
from app.fixtures import load_scenario
from app.schemas.scoring import OU_INSUFFICIENT_DATA, UNSCORED_INSUFFICIENT_HOUSEHOLDS
from app.services.scoring import (
    compare_territories,
    opportunity_units,
    ramp_score,
    score_territory,
    score_zcta,
)

RULES = load_business_rules()
DENVER = load_scenario("denver_suburban_available").market


def rules_with(**scoring_updates) -> BusinessRules:
    """Copy of the rules with scoring.* keys replaced (weights must still sum to 1)."""
    data = RULES.model_dump(mode="json")
    for key, value in scoring_updates.items():
        data["scoring"][key] = value
    return BusinessRules.model_validate(data)


def test_worked_example_reproduces_spec_section_9() -> None:
    result = score_zcta(DENVER.records["80123"], RULES)
    assert (result.score, result.tier) == (75.8, "A")
    assert result.opportunity_units == 7299.0
    assert result.data_completeness == 1.0 and result.missing_components == []
    assert result.unscored_reason is None and result.ou_reason is None
    scores = {name: c.score for name, c in result.components.items()}
    assert scores["owner_concentration"] == pytest.approx(91.58, abs=0.01)
    assert scores["owner_age_45_plus"] == pytest.approx(64.68, abs=0.01)
    assert scores["housing_age"] == pytest.approx(49.05, abs=0.01)
    assert scores["purchasing_power"] == 85.0 and scores["serviceability"] == 100.0
    assert result.ou_factors.age == pytest.approx(0.69403, abs=1e-5)
    assert result.ou_factors.housing_age == pytest.approx(0.784884, abs=1e-5)
    assert result.ou_factors.purchasing_power == 1.0
    assert result.config_version == RULES.version


def test_missing_income_renormalises_weights() -> None:
    record = DENVER.records["80123"].model_copy(update={"median_household_income": None})
    result = score_zcta(record, RULES)
    assert (result.score, result.tier) == (74.2, "B")
    assert result.data_completeness == 0.85
    assert result.missing_components == ["purchasing_power"]
    assert result.components["purchasing_power"].missing is True
    assert result.missing_factors == ["purchasing_power"]  # neutral factor 1.0, flagged
    assert result.opportunity_units == 7299.0


def test_zero_policy_scores_missing_components_as_zero() -> None:
    record = DENVER.records["80123"].model_copy(update={"median_household_income": None})
    result = score_zcta(record, rules_with(missing_data_policy="zero"))
    assert result.score == pytest.approx(63.0, abs=0.05) and result.data_completeness == 0.85


def test_scenario_5_missing_data_expectations() -> None:
    loaded = load_scenario("missing_census_fields")
    expected = loaded.scenario.requests[0].expected["scoring"]
    for zcta, checks in expected.items():
        result = score_zcta(loaded.market.records[zcta], RULES)
        for key, value in checks.items():
            assert getattr(result, key) == value, (zcta, key, getattr(result, key))
    unscored = score_zcta(loaded.market.records["80130"], RULES)
    assert unscored.unscored_reason == UNSCORED_INSUFFICIENT_HOUSEHOLDS
    gap = score_zcta(loaded.market.records["80112"], RULES)
    assert gap.score is None and gap.ou_reason == OU_INSUFFICIENT_DATA


def test_determinism_across_repeats_and_input_order() -> None:
    records = list(DENVER.records.values())
    first = [score_zcta(r, RULES).model_dump() for r in records]
    second = [score_zcta(r, RULES).model_dump() for r in records]
    assert first == second
    forward = score_territory(records, RULES).model_dump()
    backward = score_territory(list(reversed(records)), RULES).model_dump()
    assert forward == backward


def test_weight_change_moves_score_predictably() -> None:
    base = score_zcta(DENVER.records["80123"], RULES)
    shifted = RULES.scoring.weights.as_dict()
    shifted["owner_concentration"] += 0.05
    shifted["serviceability"] -= 0.05
    moved = score_zcta(DENVER.records["80123"], rules_with(weights=shifted))
    expected_delta = 0.05 * (
        base.components["owner_concentration"].score - base.components["serviceability"].score
    )
    assert moved.score - base.score == pytest.approx(expected_delta, abs=0.06)
    assert moved.score < base.score  # serviceability (100) lost weight to a lower component


def test_tier_thresholds_and_ramps() -> None:
    assert RULES.scoring.tier_for(75.0) == "A" and RULES.scoring.tier_for(74.9) == "B"
    assert RULES.scoring.tier_for(0.0) == "D" and RULES.scoring.tier_for(None) == "U"
    linear = ComponentRamp(metric="pre_2000_share", floor=0.30, ceiling=0.85)
    assert ramp_score(0.1, linear) == 0.0 and ramp_score(0.95, linear) == 100.0
    assert ramp_score(0.575, linear) == pytest.approx(50.0)
    log = ComponentRamp(metric="households_per_sq_mile", scale="log10", floor=10, ceiling=1000)
    assert ramp_score(0.0, log) == 0.0 and ramp_score(100.0, log) == pytest.approx(50.0)
    assert ramp_score(None, log) is None


def test_opportunity_unit_edge_cases() -> None:
    record = DENVER.records["80123"]
    no_owner = opportunity_units(
        record.model_copy(update={"owner_occupied_households": None}), RULES
    )
    assert no_owner.opportunity_units is None and no_owner.reason == OU_INSUFFICIENT_DATA
    no_age = opportunity_units(
        record.model_copy(update={"owner_households_age_45_plus": None}), RULES
    )
    assert no_age.opportunity_units is None and no_age.missing_factors == ["age"]
    empty = record.model_copy(
        update={"owner_occupied_households": 0, "owner_households_age_45_plus": 0}
    )
    assert opportunity_units(empty, RULES).opportunity_units == 0.0
    floor_rules = RULES.model_dump(mode="json")
    floor_rules["opportunity_units"]["missing_factor_policy"] = "floor"
    no_income = opportunity_units(
        record.model_copy(update={"median_household_income": None}),
        BusinessRules.model_validate(floor_rules),
    )
    assert no_income.factors.purchasing_power == 0.5
    assert no_income.missing_factors == ["purchasing_power"]


def test_territory_aggregation_and_comparison() -> None:
    zctas = ["80123", "80120", "80127", "80128"]
    records = [DENVER.records[z] for z in zctas]
    territory = score_territory(records, RULES)
    assert territory.zctas == sorted(zctas)
    assert territory.totals.total_households == sum(r.total_households for r in records)
    assert territory.opportunity_units == sum(
        score_zcta(r, RULES).opportunity_units for r in records
    )
    assert territory.metrics.owner_occupancy_share == pytest.approx(
        territory.totals.owner_occupied_households / territory.totals.total_households
    )
    assert territory.score is not None and territory.tier in "ABCD"
    assert territory.missing_ou_zctas == [] and set(territory.zcta_tiers) == set(zctas)
    smaller = score_territory([DENVER.records[z] for z in ("80121", "80122")], RULES)
    comparison = compare_territories(territory, smaller)
    assert comparison.comparisons["opportunity_units"].better == "a"
    assert comparison.comparisons["zcta_count"].better == "b"  # fewer ZCTAs is preferable
    assert comparison.ou_ratio_b_to_a == pytest.approx(
        smaller.opportunity_units / territory.opportunity_units
    )
    assert "OU" in comparison.summary
    gaps = load_scenario("missing_census_fields").market
    with_gap = score_territory([gaps.records["80123"], gaps.records["80112"]], RULES)
    assert with_gap.missing_ou_zctas == ["80112"]
    assert with_gap.totals.missing_by_field["owner_occupied_households"] == ["80112"]
