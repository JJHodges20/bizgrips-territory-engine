"""Conflict checker (TERRITORY_ALGORITHM.md section 2, Milestone 6).

``check_conflicts`` classifies a ZIP list against the registry snapshot and, for every
conflicting ZIP, suggests the nearest available replacements that touch the non-conflicting
part of the request (or an explicit ``anchor`` such as a proposed territory). Pure and
deterministic: same market graph, registry snapshot, rules and input give the same result.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from app.config.business_rules import BusinessRules
from app.schemas.registry import RegistrySnapshot
from app.schemas.territory import ConflictResult, Suggestion
from app.services.conflicts import classify_zips, nearest_available
from app.services.market import MarketGraph


def check_conflicts(
    zips: list[str],
    market: MarketGraph,
    registry: RegistrySnapshot,
    rules: BusinessRules,
    *,
    client_id: str | None = None,
    as_of: date | None = None,
    anchor: Iterable[str] | None = None,
    exclude: Iterable[str] = (),
) -> ConflictResult:
    """Classify ``zips`` and attach replacement suggestions for each conflicting ZIP.

    ``as_of`` is informational: the snapshot already carries its date, and passing a different
    one is an error rather than a silent mismatch. ``anchor`` is the set replacements must be
    adjacent to (default: the non-conflicting requested ZIPs; the generator passes its
    proposal). With no anchor at all, the nearest available ZCTAs to the conflict are used.
    """
    if as_of is not None and as_of != registry.as_of:
        raise ValueError(f"as_of {as_of} differs from the registry snapshot ({registry.as_of})")
    result = classify_zips(zips, market, registry, client_id=client_id)
    limit = rules.generator.replacement_suggestions
    conflicting = [
        entry.zcta for entry in (*result.reserved, *result.protected, *result.pending_release)
    ]
    if not conflicting or limit <= 0:
        return result
    anchor_set = (
        frozenset(anchor) if anchor is not None else frozenset(result.available + result.own)
    )
    never = frozenset(exclude) | frozenset(dict.fromkeys(zips)) | anchor_set
    suggestions: list[Suggestion] = []
    for zcta in sorted(conflicting):
        suggestions.extend(
            nearest_available(
                zcta,
                market,
                registry,
                client_id=client_id,
                limit=limit,
                exclude=never,
                must_touch=anchor_set or None,
            )
        )
    result.suggestions = suggestions
    return result
