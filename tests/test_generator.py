"""Territory generator against the fixture scenarios (TEST_MARKETS.md) and determinism."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.config import load_business_rules
from app.fixtures import LoadedScenario, load_scenario
from app.ingest.seed import seed_scenario
from app.repositories.registry import load_snapshot
from app.schemas.registry import RegistrySnapshot
from app.schemas.territory import TerritoryProposal, TerritoryRequest
from app.services.conflicts import classify_zips
from app.services.market import MarketGraph
from app.services.territory_generator import generate_territory

RULES = load_business_rules()
ROOT = Path(__file__).resolve().parents[1]
GENERATOR_SCENARIOS = [
    "denver_suburban_available",
    "surrounded_by_protected",
    "rural_large_area",
    "disconnected_request",
    "state_border_kansas_city",
    "symmetric_multi_path",
    "missing_census_fields",
]


def setup(
    session: Session, scenario_id: str
) -> tuple[LoadedScenario, MarketGraph, RegistrySnapshot]:
    loaded = load_scenario(scenario_id)
    market = MarketGraph.from_grid(loaded.market, RULES)
    if loaded.scenario.territories:
        with session.begin():
            seed_scenario(session, loaded)
        registry = load_snapshot(session, loaded.scenario.as_of)
    else:
        registry = RegistrySnapshot(as_of=loaded.scenario.as_of)
    return loaded, market, registry


def to_request(fixture_request: Any) -> TerritoryRequest:
    return TerritoryRequest(
        client_name=fixture_request.client_name,
        client_id=fixture_request.client_id,
        starting_zip=fixture_request.starting_zip,
        size_class=fixture_request.size_class,
        requested_zips=fixture_request.requested_zips,
        max_service_distance_miles=fixture_request.max_service_distance_miles,
        allow_cross_state=fixture_request.allow_cross_state,
    )


def check(proposal: TerritoryProposal, expected: dict[str, Any], market: MarketGraph) -> None:
    codes = proposal.zip_codes
    excluded = {e.zcta: e.reason for e in proposal.excluded}
    for key, value in expected.items():
        if key == "status":
            assert proposal.status == value
        elif key == "includes":
            assert set(value) <= set(codes), (value, codes)
        elif key == "includes_any":
            assert set(value) & set(codes), (value, codes)
        elif key == "excludes":
            assert not set(value) & set(codes), (value, codes)
        elif key == "first_zip":
            assert codes[0] == value
        elif key == "zips":
            assert sorted(codes) == sorted(value), codes
        elif key == "zips_ordered":
            assert codes == value, codes
        elif key == "contiguous":
            assert market.is_connected(codes) is value
        elif key == "target_status":
            assert proposal.target is not None and proposal.target.status == value
        elif key == "flags_include":
            assert set(value) <= set(proposal.flags), (value, proposal.flags)
        elif key == "conflict_count":
            assert proposal.conflicts.conflict_count == value
        elif key == "max_miles_from_start":
            assert all(z.miles_from_start <= value for z in proposal.zips)
        elif key == "approval_required":
            assert proposal.approval_required is value
        elif key == "excluded_reasons":
            for zcta, reason in value.items():
                assert excluded.get(zcta) == reason, (zcta, excluded.get(zcta), reason)
        elif key == "requested_reasons":
            reasons = {z.zcta: z.reason for z in proposal.zips}
            for zcta, reason in value.items():
                assert reasons.get(zcta) == reason, (zcta, reasons.get(zcta))
        elif key == "states":
            assert sorted({z.state for z in proposal.zips}) == sorted(value)
        elif key == "serviceability_component":
            for zcta, score in value.items():
                assert market.scores[zcta].components["serviceability"].score == score
        elif key in ("deterministic", "deterministic_runs"):
            pass  # covered by test_determinism_across_runs_and_processes
        elif key in ("scoring", "failure_code", "blocking_territory_id", "blocking_status"):
            pass  # scoring: tests/test_scoring.py; failure keys: test_start_zip_unavailable
        else:
            raise AssertionError(f"unhandled expectation {key!r}")


@pytest.mark.parametrize("scenario_id", GENERATOR_SCENARIOS)
def test_scenario_expectations(session: Session, scenario_id: str) -> None:
    loaded, market, registry = setup(session, scenario_id)
    for fixture_request in loaded.scenario.requests:
        proposal = generate_territory(
            to_request(fixture_request), market, registry, RULES, loaded.scenario.as_of
        )
        assert proposal.rules_version == RULES.version and proposal.approval_required
        if proposal.status == "PROPOSED":
            assert proposal.zips[0].zcta == fixture_request.starting_zip
            assert market.is_connected(proposal.zip_codes)
            included_lines = [
                line
                for line in proposal.explanation
                if any(
                    line.startswith(f"{z.zcta} included") or line.startswith(f"{z.zcta} selected")
                    for z in proposal.zips
                )
            ]
            assert len(included_lines) == len(proposal.zips)  # one line per included ZCTA
            orders = [z.order for z in proposal.zips]
            assert orders == list(range(1, len(orders) + 1))
        check(proposal, fixture_request.expected, market)


def test_start_zip_unavailable_fails_with_suggestions(session: Session) -> None:
    loaded, market, registry = setup(session, "start_zip_protected")
    fixture_request = loaded.scenario.requests[0]
    proposal = generate_territory(
        to_request(fixture_request), market, registry, RULES, loaded.scenario.as_of
    )
    expected = fixture_request.expected
    assert proposal.status == "FAILED" and proposal.zips == []
    assert proposal.failure.code == expected["failure_code"]
    assert proposal.failure.blocking_territory_id == expected["blocking_territory_id"]
    assert proposal.failure.blocking_status == expected["blocking_status"]
    suggested = [s.zcta for s in proposal.failure.suggestions]
    assert set(expected["suggestions_include_any"]) & set(suggested)
    assert len(suggested) <= RULES.generator.replacement_suggestions
    assert not {"80123", "80120", "80128"} & set(suggested)  # protected ZIPs never suggested
    conflicts = classify_zips(["80123"], market, registry, client_id="C-NEW")
    assert [c.zcta for c in conflicts.protected] == expected["conflict_check"]["protected"]
    assert conflicts.conflict_count == expected["conflict_check"]["conflict_count"]
    own = generate_territory(
        to_request(fixture_request).model_copy(update={"client_id": "C-ALPHA"}),
        market, registry, RULES, loaded.scenario.as_of,
    )  # fmt: skip
    assert own.status == "PROPOSED"  # the protected client may plan around its own ZIPs


def test_no_market_data_failure() -> None:
    market = MarketGraph.from_grid(load_scenario("symmetric_multi_path").market, RULES)
    proposal = generate_territory(
        TerritoryRequest(client_name="Nobody", starting_zip="99999"),
        market, RegistrySnapshot(as_of=date(2026, 9, 29)), RULES, date(2026, 9, 29),
    )  # fmt: skip
    assert proposal.status == "FAILED" and proposal.failure.code == "NO_MARKET_DATA"


def _symmetric_fingerprint() -> str:
    loaded = load_scenario("symmetric_multi_path")
    market = MarketGraph.from_grid(loaded.market, RULES)
    request = to_request(loaded.scenario.requests[0])
    registry = RegistrySnapshot(as_of=loaded.scenario.as_of)
    return generate_territory(request, market, registry, RULES, loaded.scenario.as_of).fingerprint()


def test_determinism_across_runs_and_processes() -> None:
    loaded = load_scenario("symmetric_multi_path")
    market = MarketGraph.from_grid(loaded.market, RULES)
    request = to_request(loaded.scenario.requests[0])
    registry = RegistrySnapshot(as_of=loaded.scenario.as_of)
    runs = loaded.scenario.requests[0].expected["deterministic_runs"]
    proposals = [
        generate_territory(request, market, registry, RULES, loaded.scenario.as_of)
        for _ in range(runs)
    ]
    assert {p.fingerprint() for p in proposals} == {proposals[0].fingerprint()}
    assert proposals[0].zip_codes == ["40012", "40011", "40013"]
    code = "from tests.test_generator import _symmetric_fingerprint;print(_symmetric_fingerprint())"
    other = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(ROOT), "DATABASE_URL": "sqlite://"},
    )
    assert other.returncode == 0, other.stderr
    assert other.stdout.strip() == proposals[0].fingerprint()
    denver = load_scenario("denver_suburban_available")
    grid = MarketGraph.from_grid(denver.market, RULES)
    first = generate_territory(
        to_request(denver.scenario.requests[0]), grid, registry, RULES, denver.scenario.as_of
    )
    second = generate_territory(
        to_request(denver.scenario.requests[0]), grid, registry, RULES, denver.scenario.as_of
    )
    assert first.model_dump() == second.model_dump()
