"""The business rules file must load, validate and reject inconsistent edits."""

from __future__ import annotations

import copy
import math

import pytest
import yaml
from pydantic import ValidationError

from app.config import BusinessRules, get_settings, load_business_rules
from app.config.business_rules import COMPONENT_NAMES


def _raw_rules() -> dict:
    with open(get_settings().business_rules_path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_rules_load_and_carry_version(rules: BusinessRules) -> None:
    assert rules.version == "1.0.0"
    assert rules.effective_date.isoformat() == "2026-09-29"


def test_weights_sum_to_one_and_match_roadmap(rules: BusinessRules) -> None:
    weights = rules.scoring.weights.as_dict()
    assert set(weights) == set(COMPONENT_NAMES)
    assert math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9)
    assert weights["owner_concentration"] == pytest.approx(0.35)
    assert weights["owner_age_45_plus"] == pytest.approx(0.25)
    assert weights["housing_age"] == pytest.approx(0.20)
    assert weights["purchasing_power"] == pytest.approx(0.15)
    assert weights["serviceability"] == pytest.approx(0.05)


def test_every_component_has_a_valid_ramp(rules: BusinessRules) -> None:
    for name in COMPONENT_NAMES:
        ramp = rules.scoring.components.get(name)
        assert ramp.floor < ramp.ceiling, name
        if ramp.scale == "log10":
            assert ramp.floor > 0


def test_tiers_are_descending_and_cover_all_scores(rules: BusinessRules) -> None:
    thresholds = list(rules.scoring.tiers.values())
    assert thresholds == sorted(thresholds, reverse=True)
    assert thresholds[-1] <= 0
    assert rules.scoring.tier_for(100) == "A"
    assert rules.scoring.tier_for(75) == "A"
    assert rules.scoring.tier_for(74.9) == "B"
    assert rules.scoring.tier_for(60) == "B"
    assert rules.scoring.tier_for(45) == "C"
    assert rules.scoring.tier_for(0) == "D"
    assert rules.scoring.tier_for(None) == "U"
    assert rules.scoring.tier_order == ("A", "B", "C", "D")


def test_size_bands_ascending_and_consistent(rules: BusinessRules) -> None:
    bands = rules.territory_sizes.bands
    assert bands.small.target_max <= bands.standard.target_min
    assert bands.standard.target_max <= bands.large.target_min
    assert rules.territory_sizes.minimum_viable_units <= bands.small.target_min
    assert rules.territory_sizes.absolute_max_units >= bands.large.target_max
    assert bands.get("STANDARD") is bands.standard
    with pytest.raises(KeyError):
        bands.get("huge")


def test_generator_min_tier_is_a_real_tier(rules: BusinessRules) -> None:
    assert rules.generator.min_tier_for_auto_selection in rules.scoring.tiers
    assert rules.generator.tie_breakers[-1] == "zcta_asc"


def test_registry_rules_match_enum_contract(rules: BusinessRules) -> None:
    assert "ACTIVE_PROTECTED" in rules.registry.blocking_statuses
    assert "RELEASED" not in rules.registry.blocking_statuses
    assert "ACTIVE_PROTECTED" in rules.registry.approval_required_for
    assert rules.registry.reservation_days == 30


def test_weights_not_summing_to_one_are_rejected() -> None:
    raw = _raw_rules()
    raw["scoring"]["weights"]["owner_concentration"] = 0.5
    with pytest.raises(ValidationError, match="sum to 1.0"):
        BusinessRules.model_validate(raw)


def test_overlapping_bands_are_rejected() -> None:
    raw = _raw_rules()
    raw["territory_sizes"]["bands"]["small"]["target_max"] = 25000
    with pytest.raises(ValidationError, match="overlap"):
        BusinessRules.model_validate(raw)


def test_unknown_tier_for_generator_is_rejected() -> None:
    raw = _raw_rules()
    raw["generator"]["min_tier_for_auto_selection"] = "Z"
    with pytest.raises(ValidationError, match="not one of the scored tiers"):
        BusinessRules.model_validate(raw)


def test_unknown_keys_are_rejected() -> None:
    raw = _raw_rules()
    raw["scoring"]["mystery_knob"] = 1
    with pytest.raises(ValidationError):
        BusinessRules.model_validate(raw)


def test_rules_are_immutable(rules: BusinessRules) -> None:
    with pytest.raises(ValidationError):
        rules.scoring.weights.owner_concentration = 0.9  # type: ignore[misc]


def test_loading_from_explicit_path_matches_default(rules: BusinessRules, tmp_path) -> None:
    raw = copy.deepcopy(_raw_rules())
    path = tmp_path / "rules.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    assert load_business_rules(path) == rules
