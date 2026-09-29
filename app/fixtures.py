"""Loader for the deterministic fixture markets in data/fixtures (see docs/TEST_MARKETS.md).

A *grid* is a small synthetic market: ZCTA records plus rook adjacency. A *scenario* references
a grid, optionally overrides fields (including nulling them out), adds registry state and lists
the requests with their expected behaviour.
"""

from __future__ import annotations

import json
from collections import deque
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config.settings import get_settings
from app.enums import TerritorySizeClass, TerritoryStatus
from app.schemas.market import ZctaRecord


class MarketGrid(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grid_id: str
    description: str
    zctas: list[ZctaRecord]
    adjacency: list[tuple[str, str]]

    @model_validator(mode="after")
    def _valid_graph(self) -> MarketGrid:
        codes = [z.zcta for z in self.zctas]
        if len(codes) != len(set(codes)):
            raise ValueError(f"{self.grid_id}: duplicate ZCTA codes")
        known = set(codes)
        seen: set[tuple[str, str]] = set()
        for a, b in self.adjacency:
            if a == b:
                raise ValueError(f"{self.grid_id}: self-adjacency {a}")
            if a not in known or b not in known:
                raise ValueError(f"{self.grid_id}: adjacency references unknown ZCTA in ({a}, {b})")
            pair = (a, b) if a < b else (b, a)
            if pair in seen:
                raise ValueError(f"{self.grid_id}: duplicate adjacency {pair}")
            seen.add(pair)
        return self

    @property
    def records(self) -> dict[str, ZctaRecord]:
        return {z.zcta: z for z in self.zctas}

    def neighbors(self, zcta: str) -> set[str]:
        out: set[str] = set()
        for a, b in self.adjacency:
            if a == zcta:
                out.add(b)
            elif b == zcta:
                out.add(a)
        return out

    def is_connected(self, zips: list[str] | set[str]) -> bool:
        """True when the given ZCTAs form a single connected component (rook adjacency)."""
        remaining = set(zips)
        if not remaining:
            return True
        start = min(remaining)
        seen = {start}
        queue = deque([start])
        while queue:
            current = queue.popleft()
            for nxt in self.neighbors(current):
                if nxt in remaining and nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        return seen == remaining

    def with_overrides(self, overrides: dict[str, dict[str, Any]]) -> MarketGrid:
        """Return a copy with per-ZCTA field overrides applied (None nulls a field)."""
        unknown = set(overrides) - set(self.records)
        if unknown:
            raise ValueError(f"overrides reference unknown ZCTAs: {sorted(unknown)}")
        updated: list[ZctaRecord] = []
        for record in self.zctas:
            patch = overrides.get(record.zcta)
            if patch:
                updated.append(ZctaRecord.model_validate({**record.model_dump(), **patch}))
            else:
                updated.append(record)
        return self.model_copy(update={"zctas": updated})


class FixtureTerritory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    territory_id: str
    client_id: str
    client_business_name: str
    starting_zip: str = Field(pattern=r"^\d{5}$")
    territory_size_class: TerritorySizeClass = TerritorySizeClass.STANDARD
    status: TerritoryStatus
    approved_by: str | None = None
    reservation_date: date | None = None
    reservation_expires_at: date | None = None
    contract_start_date: date | None = None
    contract_end_date: date | None = None
    release_date: date | None = None
    zips: list[str] = Field(min_length=1)
    notes: str | None = None

    @model_validator(mode="after")
    def _approval_rule(self) -> FixtureTerritory:
        if self.status in (TerritoryStatus.RESERVED, TerritoryStatus.ACTIVE_PROTECTED):
            if not self.approved_by:
                raise ValueError(f"{self.territory_id}: {self.status} requires approved_by")
        return self


class FixtureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    starting_zip: str = Field(pattern=r"^\d{5}$")
    size_class: TerritorySizeClass = TerritorySizeClass.STANDARD
    requested_zips: list[str] = Field(default_factory=list)
    client_id: str | None = None
    client_name: str = "Prospect"
    max_service_distance_miles: float | None = None
    allow_cross_state: bool | None = None
    expected: dict[str, Any] = Field(default_factory=dict)


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    description: str
    grid: str
    as_of: date
    zcta_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)
    territories: list[FixtureTerritory] = Field(default_factory=list)
    requests: list[FixtureRequest] = Field(min_length=1)
    expected_behavior: list[str] = Field(default_factory=list)


class LoadedScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: Scenario
    market: MarketGrid

    @model_validator(mode="after")
    def _references_resolve(self) -> LoadedScenario:
        known = set(self.market.records)
        for territory in self.scenario.territories:
            missing = [z for z in territory.zips if z not in known]
            if missing:
                raise ValueError(f"{territory.territory_id} references unknown ZCTAs {missing}")
        for request in self.scenario.requests:
            if request.starting_zip not in known:
                raise ValueError(f"request {request.name!r}: unknown starting_zip")
            missing = [z for z in request.requested_zips if z not in known]
            if missing:
                raise ValueError(f"request {request.name!r} references unknown ZCTAs {missing}")
        return self


def fixtures_dir() -> Path:
    return get_settings().fixtures_dir


def _read_json(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def list_grids() -> list[str]:
    return sorted(p.stem for p in (fixtures_dir() / "grids").glob("*.json"))


def list_scenarios() -> list[str]:
    return sorted(p.stem for p in (fixtures_dir() / "scenarios").glob("*.json"))


def load_grid(grid_id: str) -> MarketGrid:
    path = fixtures_dir() / "grids" / f"{grid_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"unknown fixture grid {grid_id!r} ({path})")
    return MarketGrid.model_validate(_read_json(path))


def load_scenario(scenario_id: str) -> LoadedScenario:
    path = fixtures_dir() / "scenarios" / f"{scenario_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"unknown fixture scenario {scenario_id!r} ({path})")
    scenario = Scenario.model_validate(_read_json(path))
    market = load_grid(scenario.grid).with_overrides(scenario.zcta_overrides)
    return LoadedScenario(scenario=scenario, market=market)
