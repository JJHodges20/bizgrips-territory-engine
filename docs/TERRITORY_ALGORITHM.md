# Territory Algorithm v1.0

Specifies the territory generator (Phase 4 / Milestone 5), the conflict checker (Phase 7 /
Milestone 6) and the sales-call market checker (Phase 6 / Milestone 7). All three are pure
services over data loaded by repositories, configured by `app/config/business_rules.yaml`, and
they never mutate the registry. Only a human-approved registry action changes ZIP state.

```
generate_territory(request: TerritoryRequest, market: MarketGraph, registry: RegistrySnapshot, rules, as_of) -> TerritoryProposal
check_conflicts(zips: list[str], market, registry, rules, as_of, client_id=None) -> ConflictResult
check_market(query: MarketQuery, market, registry, rules, as_of) -> MarketCheck
```

`MarketGraph` = scored ZCTA records + adjacency + centroids. `RegistrySnapshot` = current
assignments with statuses and dates. Both are plain data so tests can build them from fixtures.

---

## 1. Territory generator

### Inputs (`TerritoryRequest`)

| Field | Required | Notes |
|-------|----------|-------|
| client_name | yes | prospect or client business name |
| client_id | no | when present, the client's own ZIPs are not conflicts |
| starting_zip | yes | 5-digit ZCTA (postal ZIP is mapped to its ZCTA first) |
| size_class | no | SMALL / STANDARD / LARGE; default `territory_sizes.default_size_class` |
| requested_zips | no | ZCTAs the prospect asked for, in priority order |
| max_service_distance_miles | no | ≤ `serviceability.max_service_radius_miles`; default `default_service_radius_miles` |
| allow_cross_state | no | default `serviceability.allow_cross_state` |

### Priority order (from the roadmap, enforced in this order)

1. Availability — never include a blocked ZCTA.
2. Contiguity — only add ZCTAs adjacent to the current territory.
3. Serviceability — only add ZCTAs inside the radius and not flagged unserviceable.
4. Opportunity quality — prefer higher scores, discounted by distance.
5. Target size — stop when the OU band is reached.

### Algorithm

```
1. Resolve start. If starting_zip has no market record → FAIL(NO_MARKET_DATA).
   If it is blocked for another client → FAIL(START_ZIP_UNAVAILABLE) with the blocking
   territory/status and up to `generator.replacement_suggestions` nearest available ZCTAs.
   If its land area exceeds the cap → include it anyway but flag UNSERVICEABLE_LAND_AREA
   (a human decides).
2. territory = [start]; explain("Starting ZIP included").
3. Seed requested ZIPs: for each requested ZIP in order, if it is available, within radius,
   serviceable, and adjacent to the current territory, add it with reason REQUESTED.
   Otherwise defer it; re-check deferred requested ZIPs after every addition.
   Requested ZIPs that are blocked are reported as conflicts; those never connected are
   reported NOT_CONTIGUOUS; those outside the radius OUTSIDE_SERVICE_RADIUS.
4. Loop while OU(territory) < band.target_min and len(territory) < max_zctas_per_territory:
     frontier = ZCTAs adjacent to the territory that are
        available for this client
        AND within max_service_distance of the start centroid
        AND not unserviceable
        AND tier >= generator.min_tier_for_auto_selection (never U)
        AND (allow_cross_state or same state as start)
        AND OU is not None
     if frontier is empty → stop with FRONTIER_EXHAUSTED.
     rank frontier by priority = score - distance_penalty_points_per_mile * miles_from_start,
        descending; ties by generator.tie_breakers (distance asc, OU desc, zcta asc).
     candidate = first frontier ZCTA whose addition keeps OU <= target_max * (1 + target_tolerance);
        if none fits, stop with NO_CANDIDATE_FITS_BAND.
     add candidate with reason SELECTED and an explanation sentence.
5. Evaluate: aggregates (SCORING_SPEC §7), conflict status, flags:
     BELOW_MINIMUM_VIABLE, BELOW_TARGET, WITHIN_TARGET, ABOVE_TARGET, EXCEEDS_MAX_SIZE,
     CROSSES_STATE_LINE, CONTAINS_UNSERVICEABLE, FRONTIER_EXHAUSTED.
6. Return TerritoryProposal with status PROPOSED and approval_required = true.
```

Every excluded ZCTA that was ever on the frontier or requested is listed in
`excluded` with one reason: BLOCKED_<STATUS>, OUTSIDE_SERVICE_RADIUS, UNSERVICEABLE_LAND_AREA,
UNSCORED, BELOW_MIN_TIER, NOT_CONTIGUOUS, CROSS_STATE_DISALLOWED, WOULD_EXCEED_BAND.

### Determinism

Given the same market graph, registry snapshot, rules and request, the output is identical.
Sorting keys are total (the final tie-breaker is the ZCTA code), no randomness, `as_of` is an
input. Fixture `symmetric_multi_path` proves this.

### Output (`TerritoryProposal`)

```
status: PROPOSED | FAILED
failure: {code, message, blocking_territory_id?, blocking_status?, suggestions[]} | None
client_name, client_id, starting_zip, size_class, rules_version, as_of
zips: [{zcta, order, reason, explanation, score, tier, opportunity_units, miles_from_start, state}]
excluded: [{zcta, reason, detail}]
aggregates: {zcta_count, total_population, total_households, owner_occupied_households,
             owner_households_age_45_plus, owner_households_age_55_plus, owner_households_age_65_plus,
             total_housing_units, homes_built_before_2000, homes_built_before_1990, homes_built_before_1980,
             median_household_income (household-weighted), land_area_sq_miles,
             opportunity_units, opportunity_score, market_tier}
target: {band_min, band_max, tolerance, status: BELOW_MINIMUM_VIABLE|BELOW_TARGET|WITHIN_TARGET|ABOVE_TARGET}
conflicts: ConflictResult for requested_zips (empty when none requested)
flags: [...]
explanation: [sentences in selection order]
approval_required: true
```

Example explanation lines:
- "80123 included: starting ZIP."
- "80127 selected: adjacent, available, Tier A (score 81), 3.2 mi from start."
- "80128 selected: keeps contiguity and moves the territory toward the Standard target (26,400 of 20,000–32,000 OU)."
- "80129 excluded: ACTIVE_PROTECTED for territory T-000001."

### Implementation notes (Milestone 5, 2026-09-29)

- `app/services/territory_generator.py::generate_territory`; market data as
  `app/services/market.py::MarketGraph` (records, rook adjacency, live scores, centroid
  distances by haversine); conflicts of requested ZIPs via `app/services/conflicts.py`.
- Additional exclusion reason `NO_MARKET_DATA` for a requested code with no record; additional
  flags `CONTAINS_UNSERVICEABLE` (any member over the land cap; `UNSERVICEABLE_LAND_AREA` marks
  the start itself), `NO_CANDIDATE_FITS_BAND`, `MAX_ZCTAS_REACHED`, `RADIUS_CLAMPED` (a
  requested radius above the maximum is clamped).
- Requested ZIPs must also be scored (tier not U); an unscored requested ZIP is excluded
  `UNSCORED`, the same rule that keeps unscored ZCTAs off the frontier.
- Only ZCTAs that were on the frontier or requested appear in `excluded`; a neighbour the loop
  never reached before the target was met is simply absent.
- The explanation carries one line per included ZCTA (in selection order) followed by one
  line per exclusion; `POST /territories/propose?persist=true` stores the proposal as the
  PROPOSED territory's `generation_snapshot_json`.
- `TerritoryProposal.fingerprint()` (sha256 of the canonical JSON) is what the determinism
  test compares across 100 runs and across processes.

## 2. Conflict checker

### Inputs

One ZIP, a list of ZIPs, or a proposed territory (its ZIP list), plus optional `client_id`.

### Rules

- For each ZIP: find assignments with a blocking status. If one exists for a different client,
  the ZIP is in conflict with that status (RESERVED / ACTIVE_PROTECTED / PENDING_RELEASE).
- PENDING_RELEASE with `release_date <= as_of` is treated as released (available).
- RESERVED with `reservation_expires_at < as_of` is still a conflict but carries the flag
  `RESERVATION_EXPIRED`.
- Same-client assignments are reported under `own` and are not conflicts.
- ZIPs with no market record are reported under `unknown` (NO_MARKET_DATA).
- Contiguity of the requested list is evaluated and reported (`contiguous: bool`,
  `components: [[...], [...]]`), but it is informational for the checker.
- Replacement suggestions: for each conflicting ZIP, the nearest available ZCTAs (by centroid
  distance) that are adjacent to any non-conflicting requested ZIP, up to
  `generator.replacement_suggestions`, ranked by distance then score.

### Output (`ConflictResult`)

```
requested_count, available: [zcta], reserved: [{zcta, territory_id, client_business_name, expires_at, expired}],
protected: [{zcta, territory_id, client_business_name, contract_end_date}],
pending_release: [{zcta, territory_id, release_date}], own: [zcta], unknown: [zcta],
conflict_count, contiguous, components, suggestions: [{for_zcta, zcta, miles, score, tier}]
```

Deterministic: same registry snapshot + same inputs ⇒ same output.

## 3. Sales-call market checker

### Inputs (`MarketQuery`)

Exactly one of: `starting_zip`; `requested_zips` (pasted list, postal ZIPs accepted); or
`city` + `state` (resolved to the ZCTAs whose primary city matches, then the highest-OU ZCTA
becomes the starting ZIP). Optional `size_class`, `client_id`.

### Process

1. Resolve the query to a starting ZIP (and requested ZIPs, if pasted).
2. Run `check_conflicts` on the requested ZIPs (if any).
3. Run `generate_territory` from the starting ZIP with the requested ZIPs.
4. Assemble the sales view.

### Output (`MarketCheck`)

```
market_availability: AVAILABLE | PARTIALLY_AVAILABLE | UNAVAILABLE
   AVAILABLE: start available and proposal reached the band with no requested-ZIP conflicts
   PARTIALLY_AVAILABLE: start available but conflicts or a below-target proposal
   UNAVAILABLE: start blocked
suggested_territory: TerritoryProposal (or None)
available_zips, reserved_zips, protected_zips (with client names for internal use only), replacement_zips
market_stats: owner households, owner 45+, housing-age profile (pre-2000/1990/1980 shares),
              median household income, opportunity score, market tier, OU
talking_points: factual sentences generated from the data, e.g.
   "The proposed 7-ZIP territory contains about 41,200 owner-occupied households, 29,600 of them
    with a householder age 45 or older, and 68% of homes were built before 2000."
   Talking points state public-data facts only. They never claim expected leads, cost or sales.
approval_required: true
```

Target: a salesperson gets this in under a minute from one input.

## 4. Registry interaction (Milestone 4) — for reference

The generator and checkers read a `RegistrySnapshot`. State changes go through
`RegistryService` with these transitions, each validated and logged:

```
PROPOSED → RESERVED           requires approved_by; sets reservation_date/expires_at; writes assignments (status RESERVED)
RESERVED → RESERVED (extend)  requires approved_by, reason; max_reservation_extensions
RESERVED → ACTIVE_PROTECTED   requires approved_by, contract_start_date; assignments → ACTIVE_PROTECTED
RESERVED → CANCELLED          assignments → RELEASED with date_released
ACTIVE_PROTECTED → PENDING_RELEASE   sets release_date; assignments → PENDING_RELEASE
PENDING_RELEASE → RELEASED    on or after release_date; assignments → RELEASED
```

Writing an assignment for a ZIP that already has a blocking assignment for another territory is
rejected at the service level and, as a backstop, by the `uq_active_zip` database constraint.

Implemented in Milestone 4 (`app/services/registry.py`, `app/repositories/registry.py`) with
these additions:

- `PROPOSED → CANCELLED` is allowed (discarding a proposal blocks nothing).
- A PROPOSED territory keeps its ZIP list in `generation_snapshot_json["zips"]`; assignment
  rows exist only from RESERVED onwards (assignment statuses have no PROPOSED value).
- Creating a proposal that contains another client's blocked ZIP is refused (409
  `ZIP_CONFLICT`); the conflict check runs again at reservation time because state can change
  between the two.
- `PENDING_RELEASE` past its `release_date` counts as available. Before a proposal or
  reservation touches such a ZIP, and on `POST /registry/sweep`, the due release is completed
  (RELEASED, audit note by "system"), which is what Standard section 11 prescribes for the
  release date. Expired reservations are only flagged, never released automatically.
- Every transition appends one audit line to `notes` (`[date] EVENT by actor: detail`); notes
  are never rewritten.
