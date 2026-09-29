# Data Dictionary v1.0

Every stored field, where it comes from, how it is derived, and how provenance is recorded.
ORM definitions: `app/models/`. Census variable map: `app/config/census_variables.yaml`.

All sources are free and public. Vintage recorded here: ACS 2019–2023 5-Year (vintage 2023),
2020 ZCTA boundaries. Never mix vintages within one import; bump the vintage in the YAML and add
a row to section 8 when refreshing.

---

## 1. `zcta_markets` — one row per ZCTA

### Geography

| Column | Type | Source | Notes |
|--------|------|--------|-------|
| zcta | CHAR(5) PK | CB ZCTA5 2020 `ZCTA5CE20` | Census ZIP Code Tabulation Area |
| postal_zip | CHAR(5) NULL | GeoNames US postal codes | Same code if a deliverable postal ZIP exists; NULL otherwise |
| primary_city | TEXT NULL | GeoNames place name | First place listed for the ZIP |
| state | CHAR(2) NULL | ZCTA→county relationship file | State of the county with the largest land overlap |
| state_fips | CHAR(2) NULL | same | |
| latitude, longitude | FLOAT NULL | Centroid of the boundary geometry (EPSG:5070); the representative point when the centroid falls outside the polygon | WGS84; always inside the ZCTA |
| land_area_sq_miles | FLOAT NULL | `ALAND20` / 2,589,988.11 | |
| water_area_sq_miles | FLOAT NULL | `AWATER20` / 2,589,988.11 | |
| geometry_geojson | TEXT NULL | CB boundary polygon, simplified (Douglas-Peucker 0.0005 deg, topology preserved) | Loaded with `--with-geometry` (default in `make import-data` since Milestone 8); about 3 KB per ZCTA. |
| bbox_min_lon, bbox_min_lat, bbox_max_lon, bbox_max_lat | FLOAT NULL | WGS84 bounding box of the boundary | Map viewport queries (`GET /map/zctas`); always stored. |

### Households

| Column | Type | ACS variables | Notes |
|--------|------|---------------|-------|
| total_population | INT NULL | B01003_001E | context only |
| total_households | INT NULL | B25003_001E | occupied housing units |
| owner_occupied_households | INT NULL | B25003_002E | |
| renter_occupied_households | INT NULL | B25003_003E | |
| owner_occupancy_percent | FLOAT NULL | derived: owner / total × 100 | NULL if total is 0 or missing |

### Homeowner age

| Column | Type | ACS variables | Notes |
|--------|------|---------------|-------|
| owner_households_age_45_plus | INT NULL | B25007_006E + 007E + 008E + 009E + 010E + 011E | primary V1 signal |
| owner_households_age_55_plus | INT NULL | B25007_007E … 011E | analysis only |
| owner_households_age_65_plus | INT NULL | B25007_009E + 010E + 011E | analysis only |

B25007 buckets (owner occupied): 003 15–24, 004 25–34, 005 35–44, 006 45–54, 007 55–59,
008 60–64, 009 65–74, 010 75–84, 011 85+.

### Housing stock

| Column | Type | ACS variables | Notes |
|--------|------|---------------|-------|
| total_housing_units | INT NULL | B25034_001E | all units, occupied or not |
| homes_built_before_2000 | INT NULL | B25034_005E … 011E | |
| homes_built_before_1990 | INT NULL | B25034_006E … 011E | |
| homes_built_before_1980 | INT NULL | B25034_007E … 011E | |

B25034 buckets (vintage 2020+): 002 2020 or later, 003 2010–2019, 004 2000–2009, 005 1990–1999,
006 1980–1989, 007 1970–1979, 008 1960–1969, 009 1950–1959, 010 1940–1949, 011 1939 or earlier.
Vintages 2019 and earlier split the newest buckets differently (002 = 2014 or later, 003 =
2010–2013); the "before 2000/1990/1980" sums are unaffected but the label check must be updated.

### Economics

| Column | Type | ACS variables | Notes |
|--------|------|---------------|-------|
| median_household_income | INT NULL | B19013_001E | inflation-adjusted dollars of the vintage year |
| median_home_value | INT NULL | B25077_001E | analysis only in V1 |

### Derived and scoring cache

| Column | Type | Notes |
|--------|------|-------|
| households_per_sq_mile | FLOAT NULL | total_households / land_area_sq_miles |
| opportunity_score | FLOAT NULL | cached result of `score_zcta`; recomputed when rules or data change |
| market_tier | CHAR(1) NULL | A/B/C/D/U |
| opportunity_units | FLOAT NULL | cached result |
| score_config_version | TEXT NULL | `business_rules.yaml` version used for the cache |
| scored_at | DATETIME NULL | |
| unserviceable_land_area | BOOL | land_area_sq_miles > `serviceability.max_zcta_land_area_sq_miles` |

### Provenance

| Column | Type | Notes |
|--------|------|-------|
| demographics_import_id | INT FK → data_source_imports | the ACS import that wrote the demographic columns |
| geography_import_id | INT FK → data_source_imports | the boundary import that wrote the geography columns |
| source_release | TEXT | e.g. `acs5-2023` |
| last_updated | DATETIME | |

Territory state is **not** stored on this table. Availability is derived from
`territory_zip_assignments` (section 4) so that there is one source of truth.

## 2. `zcta_adjacency` — rook contiguity graph

| Column | Type | Notes |
|--------|------|-------|
| zcta_a | CHAR(5) PK | lexically smaller code |
| zcta_b | CHAR(5) PK | lexically larger code |
| shared_boundary_length_m | FLOAT NULL | length of the shared boundary in metres (projected) |
| geography_import_id | INT FK | |

One row per unordered pair; queries look up both columns. Computed at import time from the
boundary polygons (intersection with a shared boundary length > 0). ZCTAs touching only at a
point are not adjacent.

## 3. `territories`

| Column | Type | Notes |
|--------|------|-------|
| territory_id | TEXT PK | `T-` + zero-padded sequence, e.g. `T-000001` |
| client_id | TEXT | external CRM identifier |
| client_business_name | TEXT | |
| starting_zip | CHAR(5) | ZCTA the proposal started from |
| territory_size_class | TEXT | SMALL / STANDARD / LARGE |
| status | TEXT | PROPOSED / RESERVED / ACTIVE_PROTECTED / PENDING_RELEASE / RELEASED / CANCELLED |
| approved_by | TEXT NULL | required for RESERVED and ACTIVE_PROTECTED |
| approved_at | DATETIME NULL | |
| reservation_date | DATE NULL | |
| reservation_expires_at | DATE NULL | reservation_date + 30 days (+ extensions) |
| reservation_extensions | INT | count |
| contract_start_date | DATE NULL | |
| contract_end_date | DATE NULL | |
| release_date | DATE NULL | date ZCTAs become available |
| exceptions_json | JSON NULL | list of {type, approved_by, reason, at} |
| generation_snapshot_json | JSON NULL | the proposal (explanation, aggregates, rules version); `zips` holds the ZIP list while the territory is PROPOSED |
| notes | TEXT NULL | append-only audit trail: one `[date] EVENT by actor: detail` line per transition or exception |
| created_at, updated_at | DATETIME | |

## 4. `territory_zip_assignments`

| Column | Type | Notes |
|--------|------|-------|
| id | INT PK | |
| territory_id | TEXT FK → territories | |
| client_id | TEXT | denormalised for fast conflict lookup |
| zip | CHAR(5) | ZCTA code |
| status | TEXT | RESERVED / ACTIVE_PROTECTED / PENDING_RELEASE / RELEASED |
| date_assigned | DATE | |
| date_released | DATE NULL | |

Constraint `uq_active_zip`: a partial unique index on `zip` where status is a blocking status,
so the database itself prevents the same ZCTA from being active for two territories.

**Availability query:** a ZCTA is AVAILABLE when no assignment exists for it with status in
`registry.blocking_statuses`.

## 5. `scoring_configs`

Snapshot of each business-rules version that has been used to score data, so historical
scores can be reproduced.

| Column | Type | Notes |
|--------|------|-------|
| config_version | TEXT PK | matches `business_rules.yaml` `version` |
| effective_date | DATE | |
| owner_household_weight, age_45_plus_weight, housing_age_weight, income_weight, serviceability_weight | FLOAT | |
| small_target_min, small_target_max, standard_target_min, standard_target_max, large_target_min, large_target_max | INT | OU |
| full_config_json | JSON | complete YAML content |
| created_at | DATETIME | |

## 6. `data_source_imports` — provenance per import run

| Column | Type | Notes |
|--------|------|-------|
| id | INT PK | |
| dataset | TEXT | `acs/acs5`, `cb_zcta520_500k`, `zcta520_county20_rel`, `geonames_us_postal` (ids from `census_variables.yaml`) |
| vintage | TEXT | e.g. `2023`, `2020` |
| release_label | TEXT | human label |
| source_url | TEXT | |
| variables_json | JSON | field → variables mapping used |
| record_count | INT | |
| checksum | TEXT NULL | sha256 of the downloaded file; for multi-file sources a sha256 over the sorted per-file digests |
| imported_at | DATETIME | |
| notes | TEXT NULL | |

## 7. `data_field_provenance` — which import last wrote each field

| Column | Type | Notes |
|--------|------|-------|
| field_name | TEXT PK | column name in `zcta_markets` |
| dataset | TEXT | |
| vintage | TEXT | |
| table_id | TEXT NULL | e.g. `B25007` |
| variables_json | JSON | |
| import_id | INT FK → data_source_imports | |
| updated_at | DATETIME | |

Together, sections 6 and 7 satisfy the roadmap's provenance requirement: for any demographic
field one can identify the dataset, release, variables and import timestamp.

## 8. Vintage log

| Date | Dataset | Vintage | Note |
|------|---------|---------|------|
| 2026-09-29 | ACS 5-Year | 2023 | Variable map recorded in `census_variables.yaml`. |
| 2026-09-29 | CB ZCTA5 | 2020 | 1:500k generalised boundaries selected for adjacency and centroids. |
| 2026-09-29 | ACS 5-Year | 2023 | First national import (Milestone 1) from the ACS Summary File table-based files (`acsdt5y2023-<table>.dat`), the same 2019-2023 estimates the Data API serves. |
| 2026-09-29 | CB ZCTA5 + relationship file + GeoNames | 2020 / 2020 / download date | First national geography import (Milestone 1). |

## 9. Sentinels and edge cases

- ACS returns negative sentinel values (e.g. `-666666666`) where an estimate is unavailable.
  These are converted to NULL, never stored as numbers. Any other negative value is also
  treated as unavailable (counts and dollar medians cannot be negative) and counted separately
  in the import summary so a new jam value is noticed.
- A bucket sum (e.g. owner 45+) is NULL when any of its component variables is unavailable;
  it is never a partial sum.
- The Census Data API requires a free key for data queries (since 2026); variable metadata is
  served without one. `scripts/import_census.py` uses the API when `CENSUS_API_KEY` is set and
  otherwise reads the ACS Summary File table-based files (`summary_file` in
  `census_variables.yaml`), which carry the same estimates for every summary level; only the
  ZCTA rows (GEO_ID prefix `860Z200US`) are read.
- Rows whose values are mutually inconsistent across tables (rare, e.g. occupied units above
  total units after rounding) are stored as published and counted in the import notes;
  `ZctaRecord.from_row` returns them unvalidated so reads never fail.
- ZCTAs with zero households (industrial, parks, PO-box-like areas) are stored and marked
  unscored (tier U).
- ZCTAs can cross state lines; `state` is the dominant state and `crosses_state_line` is
  computed at territory level from adjacency.
- Postal ZIPs without a ZCTA (PO boxes, unique ZIPs) do not appear in `zcta_markets`; the
  market checker maps a pasted postal ZIP to its ZCTA when one exists and otherwise reports it
  as `NO_MARKET_DATA`.
