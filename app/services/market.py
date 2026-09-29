"""MarketGraph: scored ZCTA records, rook adjacency and centroid distances as plain data.

Built from fixture grids in tests and from the database by ``app.repositories.market_graph``;
the generator and checkers only ever see this object plus a ``RegistrySnapshot``.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field

from app.config.business_rules import BusinessRules
from app.fixtures import MarketGrid
from app.schemas.market import ZctaRecord
from app.schemas.scoring import ZctaScore
from app.services.scoring import score_zcta

EARTH_RADIUS_MILES = 3958.7613


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def connected_components(
    zips: Iterable[str], adjacency: dict[str, frozenset[str]]
) -> list[list[str]]:
    """Rook-connected components of a ZIP set, each sorted, ordered by their first code."""
    remaining = set(zips)
    components: list[list[str]] = []
    while remaining:
        start = min(remaining)
        seen = {start}
        queue = deque([start])
        while queue:
            current = queue.popleft()
            for nxt in adjacency.get(current, frozenset()):
                if nxt in remaining and nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        components.append(sorted(seen))
        remaining -= seen
    return sorted(components, key=lambda c: c[0])


@dataclass(frozen=True)
class MarketGraph:
    records: dict[str, ZctaRecord]
    adjacency: dict[str, frozenset[str]]
    scores: dict[str, ZctaScore]
    unserviceable: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def build(
        cls,
        records: Iterable[ZctaRecord],
        pairs: Iterable[tuple[str, str]],
        rules: BusinessRules,
    ) -> MarketGraph:
        by_code = {r.zcta: r for r in records}
        adjacency: dict[str, set[str]] = {code: set() for code in by_code}
        for a, b in pairs:
            if a in by_code and b in by_code and a != b:
                adjacency[a].add(b)
                adjacency[b].add(a)
        cap = rules.serviceability.max_zcta_land_area_sq_miles
        return cls(
            records=by_code,
            adjacency={code: frozenset(nbrs) for code, nbrs in adjacency.items()},
            scores={code: score_zcta(record, rules) for code, record in by_code.items()},
            unserviceable=frozenset(
                code
                for code, record in by_code.items()
                if record.land_area_sq_miles is not None and record.land_area_sq_miles > cap
            ),
        )

    @classmethod
    def from_grid(cls, grid: MarketGrid, rules: BusinessRules) -> MarketGraph:
        return cls.build(grid.zctas, grid.adjacency, rules)

    def has(self, zcta: str) -> bool:
        return zcta in self.records

    def neighbours(self, zcta: str) -> frozenset[str]:
        return self.adjacency.get(zcta, frozenset())

    def state(self, zcta: str) -> str | None:
        return self.records[zcta].state if zcta in self.records else None

    def distance_miles(self, a: str, b: str) -> float | None:
        ra, rb = self.records.get(a), self.records.get(b)
        if ra is None or rb is None:
            return None
        if None in (ra.latitude, ra.longitude, rb.latitude, rb.longitude):
            return None
        return haversine_miles(ra.latitude, ra.longitude, rb.latitude, rb.longitude)

    def components(self, zips: Iterable[str]) -> list[list[str]]:
        return connected_components(zips, self.adjacency)

    def is_connected(self, zips: Iterable[str]) -> bool:
        codes = list(zips)
        return len(codes) == 0 or len(self.components(codes)) == 1
