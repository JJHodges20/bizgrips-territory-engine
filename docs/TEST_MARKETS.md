# Test Markets v1.0

Deterministic fixture markets used by the test suite and for seeding a development database.
All demographic values are **synthetic**: they are shaped like real Census figures for the
named places but are not real data. Real data arrives in Milestone 1.

Fixture files live in `data/fixtures/`. Shared base grids are in `data/fixtures/grids/`;
scenarios in `data/fixtures/scenarios/` reference a grid and apply overrides, territories and
requests. The loader is `app/fixtures.py`. Expected outcomes below become assertions as each
milestone lands (scoring in M3, registry in M4, generator in M5, conflicts in M6).

Distances are great-circle miles between the grid centroids. The Denver grid places 12 ZCTAs in
a 4 × 3 lattice roughly 3 miles apart with rook adjacency (17 edges).

```
 80121 — 80122 — 80111 — 80112
   |       |       |       |
 80120 — 80123 — 80124 — 80126
   |       |       |       |
 80128 — 80127 — 80129 — 80130
```

Approximate fixture values (score with V1 rules; OU = owner 45+ × housing × income factors):

| ZCTA | Owner HH | Owner 45+ | Pre-2000 share | Income | Score (approx.) | OU (approx.) |
|------|----------|-----------|----------------|--------|-----------------|--------------|
| 80123 | 13,400 | 9,300 | 0.57 | 108k | 76 A | 7,300 |
| 80120 | 6,900 | 4,900 | 0.86 | 84k | 74 B | 4,570 |
| 80121 | 5,100 | 3,900 | 0.92 | 118k | 84 A | 3,740 |
| 80122 | 9,400 | 6,900 | 0.90 | 101k | 82 A | 6,560 |
| 80111 | 6,300 | 4,800 | 0.80 | 126k | 74 B | 4,320 |
| 80112 | 4,200 | 2,700 | 0.56 | 92k | 42 D | 2,100 |
| 80124 | 5,900 | 3,700 | 0.40 | 121k | 52 C | 2,600 |
| 80126 | 9,300 | 6,200 | 0.60 | 128k | 66 B | 4,950 |
| 80128 | 10,400 | 7,700 | 0.83 | 104k | 84 A | 7,060 |
| 80127 | 12,100 | 8,700 | 0.78 | 112k | 80 A | 7,750 |
| 80129 | 9,800 | 5,900 | 0.52 | 131k | 63 B | 4,480 |
| 80130 | 7,900 | 5,000 | 0.55 | 134k | 64 B | 3,870 |

Grid total ≈ 59,300 OU, so a Standard territory (20,000–32,000 OU) needs about 4 ZCTAs, a Small
one 2–3 and a Large one 5–6.

---

## Scenario 1 — `denver_suburban_available`

**Setup:** Denver grid, registry empty. Request: start 80123, STANDARD.

**Expected:** proposal status PROPOSED; includes 80123 first; every ZCTA adjacent to an earlier
one (contiguous); OU within 20,000–32,000 (tolerance 10%); no conflicts; all within 30 miles;
flags contain WITHIN_TARGET; approval_required true; explanation has one line per ZCTA.
Rerunning yields the identical ZIP list and order.

## Scenario 2 — `start_zip_protected`

**Setup:** Denver grid. Territory T-000001, client C-ALPHA "Peak Bath Solutions",
ACTIVE_PROTECTED, ZIPs 80123, 80120, 80128. Request: start 80123, STANDARD.

**Expected:** status FAILED, failure code START_ZIP_UNAVAILABLE, blocking_territory_id T-000001,
blocking_status ACTIVE_PROTECTED; suggestions are the nearest available ZCTAs (80122, 80124,
80127 appear); no territory returned; conflict checker on [80123] reports 1 protected.
Registry: attempting to reserve 80123 for another client is rejected.

## Scenario 3 — `surrounded_by_protected`

**Setup:** Denver grid. Territory T-000001 (C-ALPHA) ACTIVE_PROTECTED holds 80121, 80120,
80122 and territory T-000003 (C-CHARLIE) ACTIVE_PROTECTED holds 80127, 80129, 80124, 80111, so
all four rook neighbours of 80123 are blocked (each territory is itself contiguous). Request:
start 80123, STANDARD.

**Expected:** PROPOSED with exactly [80123]; flags contain FRONTIER_EXHAUSTED and
BELOW_MINIMUM_VIABLE (7,300 < 10,000); target status BELOW_MINIMUM_VIABLE; excluded lists the
four neighbours with reason BLOCKED_ACTIVE_PROTECTED; approval_required true.

## Scenario 4 — `rural_large_area`

**Setup:** Wyoming-style chain 82633 — 82637 — 82636 — 82609 — 82604 (plus 82609 — 82604).
82633 (1,850 sq mi) and 82637 (1,210 sq mi) and 82604 (1,650 sq mi) exceed the 400 sq mi cap.
Request: start 82633, SMALL.

**Expected:** 82633 included (starting ZIP) with flag UNSERVICEABLE_LAND_AREA; 82637 excluded
UNSERVICEABLE_LAND_AREA so the frontier is empty; proposal = [82633], FRONTIER_EXHAUSTED,
BELOW_MINIMUM_VIABLE. Serviceability component for 82633 is 0 (density < 10 HH/sq mi). A second
request from 82609 (28 sq mi) adds compact 82636 but never oversized 82604, and still ends
FRONTIER_EXHAUSTED and BELOW_MINIMUM_VIABLE (about 2,700 OU): rural markets need a human
exception, which is the point of the scenario.

## Scenario 5 — `missing_census_fields`

**Setup:** Denver grid with overrides: 80124 median_household_income = null; 80126
total_housing_units and homes_built_before_* = null; 80112 owner_occupied_households and
owner_households_age_45_plus = null; 80130 total_households = null.

**Expected scoring:** 80124 scored with purchasing_power missing, data_completeness 0.85,
weights renormalised; 80126 scored with housing_age missing (completeness 0.80), OU uses
neutral housing factor and lists missing_factors [housing_age]; 80112 unscored (U,
MISSING_REQUIRED_OWNER_CONCENTRATION), OU None; 80130 unscored (INSUFFICIENT_HOUSEHOLDS /
missing required component). Generator from 80123 never selects 80112 or 80130 (excluded
UNSCORED) but can select 80124 and 80126.

## Scenario 6 — `disconnected_request`

**Setup:** Denver grid, registry empty. Request: start 80123, SMALL, requested_zips
[80124, 80130].

**Expected:** 80124 added with reason REQUESTED (adjacent to start). Small band (10,000–20,000)
is reached after 80123 + 80124 + one more selected neighbour, so 80130 never becomes adjacent;
it is reported in excluded with NOT_CONTIGUOUS and in the request conflict result as
non-contiguous. No conflicts.

## Scenario 7 — `state_border_kansas_city`

**Setup:** Kansas side 66205 — 66206 — 66208; Missouri side 64112 — 64113 — 64114, with
cross-state edges 66208 — 64112, 66208 — 64113, 66206 — 64113, 66206 — 64114. Registry empty.
Request A: start 66208, SMALL, allow_cross_state true. Request B: same with
allow_cross_state false.

**Expected:** A includes at least one Missouri ZCTA and carries flag CROSSES_STATE_LINE.
B contains only Kansas ZCTAs; Missouri neighbours are excluded with CROSS_STATE_DISALLOWED.

## Scenario 8 — `symmetric_multi_path`

**Setup:** Linear chain 40010 — 40011 — 40012 — 40013 — 40014 where 40011 and 40013 are
identical in every field and equidistant from 40012; 40010 and 40014 are also identical.
Request: start 40012, SMALL.

**Expected:** after 40012 the tie between 40011 and 40013 is broken by ZCTA code ascending, so
40011 is second; then 40013 (closer than 40010) is third. The ordered ZIP list is identical
across 100 consecutive runs and across process restarts (hash of the serialised proposal).

## Scenario 9 — `reserved_expired`

**Setup:** Denver grid. Territory T-000002, client C-BRAVO "Front Range Showers", RESERVED,
reservation_date 2026-07-15, reservation_expires_at 2026-08-14, ZIPs 80127, 80129. Fixture
`as_of` = 2026-09-29. Request: start 80123, STANDARD, requested_zips [80127].

**Expected:** 80127 and 80129 remain conflicts (status RESERVED) with flag RESERVATION_EXPIRED
and the reserving client named; the proposal excludes them (BLOCKED_RESERVED) and still reaches
the Standard band via other neighbours; conflict result suggests replacements adjacent to the
proposal. Registry: releasing the expired reservation (human action) makes both ZIPs available on
the next run.

---

## Acceptance tests derived from these scenarios

Scoring (M3): determinism (1, 8); weight change moves score predictably (1); missing-data
behaviour (5).

Registry (M4): active ZIP cannot be assigned twice (2); released ZIP becomes available (9);
reserved ZIP is unavailable to another prospect (9).

Generator (M5): contiguity (1, 6, 7, 8); protected ZIPs excluded (2, 3, 9); starting ZIP
included when available (1, 3, 4); target band respected within tolerance (1, 6, 7).

Conflict checker (M6): deterministic results (2, 9); suggestions adjacent and available (2, 9).
