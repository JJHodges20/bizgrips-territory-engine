# Milestones

One milestone per session. Each has inputs, outputs, business rules, edge cases, acceptance
criteria, fixtures and explicit out-of-scope items. Use plan mode for Milestones 1, 3, 4 and 5.

---

## Milestone 0 — Repository + development environment (DONE)

**Outputs:** repository scaffold, `CLAUDE.md`, Phase 0 specifications (`BIZGRIPS_TERRITORY_STANDARD.md`,
`SCORING_SPEC.md`, `DATA_DICTIONARY.md`, `TERRITORY_ALGORITHM.md`, `TEST_MARKETS.md`),
`business_rules.yaml` + validated loader, `census_variables.yaml`, ORM models and initial Alembic
migration, FastAPI app with `/health` and `/config/business-rules`, fixture markets and loader,
seed script, Makefile / `dev.ps1`, docker-compose for PostGIS, pytest suite.

**Acceptance:** `make setup && make test && make lint` pass on a clean checkout; `make dev`
serves `/health`; `make seed-fixtures` loads a scenario into SQLite; the business rules file
fails validation if weights do not sum to 1 or bands overlap.

**Out of scope:** any import of real data, scoring logic, generator logic, UI.

---

## Milestone 1 — Public data ingestion

**Goal:** a repeatable, provenance-recording import of national ZCTA market data.

**Inputs:** `census_variables.yaml`; ACS 5-Year API (`https://api.census.gov/data/{vintage}/acs/acs5`);
CB ZCTA5 2020 boundary shapefile; ZCTA-to-county relationship file; GeoNames US postal file.
Optional `CENSUS_API_KEY`.

**Outputs:**
- `scripts/import_geography.py`: downloads (with checksum) to `data/raw/`, loads boundaries with
  geopandas, computes centroid lat/lon, land/water area in sq mi, rook adjacency with shared
  boundary length (projected CRS, e.g. EPSG:5070), dominant state, primary city, postal_zip;
  writes `zcta_markets` geography columns and `zcta_adjacency`; records `data_source_imports`
  and `data_field_provenance`. Flags `--with-geometry` to store GeoJSON. Idempotent (upsert).
- `scripts/import_census.py`: validates variable labels against the API's `variables.json`
  (`label_contains`), pulls all ZCTAs in batches of ≤ 50 variables, converts sentinels to NULL,
  sums bucket variables, derives `owner_occupancy_percent` and `households_per_sq_mile`, upserts
  demographic columns, records provenance. `--vintage` overrides the YAML with a warning and
  refuses if labels do not match.
- `make import-data` runs both. Re-running updates rows in place and adds a new import record.
- Repository functions: get by ZCTA, list by state, search by city, neighbours of a ZCTA.

**Business rules:** never mix vintages; sentinels → NULL; ZCTA is the key; postal validation
is a lookup, not a filter (all ZCTAs are stored).

**Edge cases:** API pagination/rate limits and retries; ZCTAs missing from one source (store
with NULLs and log counts); multipolygon ZCTAs; generalised boundaries that leave slivers
(adjacency requires shared length > 0 after a 0-width buffer fix); ZCTAs with zero land area;
Windows path handling for downloads.

**Acceptance:** import completes on a laptop in reasonable time; row count within 1% of the
official ZCTA count (~33,000); spot-check five known ZCTAs against data.census.gov; adjacency
symmetric and 80123-style suburban ZCTAs have 4–8 neighbours; `data_source_imports` has one row
per source; a second run changes no counts; unit tests cover parsing, sentinel handling, bucket
sums and adjacency computation on a tiny synthetic shapefile.

**Fixtures:** small synthetic API responses and a 4-polygon GeoDataFrame in `tests/fixtures/`.

**Out of scope:** scoring, API endpoints beyond what tests need, PostGIS geometry columns.

---

## Milestone 2 — ZIP/ZCTA data API

Read endpoints: `GET /zctas/{zcta}`, `GET /zctas?state=&city=&tier=`, `GET /zctas/{zcta}/neighbors`,
`GET /imports` (provenance). Pydantic response models mirror `DATA_DICTIONARY.md`. Acceptance:
endpoints tested against a fixture-seeded SQLite database.

## Milestone 3 — Opportunity scoring + Opportunity Units

Implements `SCORING_SPEC.md` in `app/services/scoring.py`; `scripts/score_all.py` caches results
and records `scoring_configs`; calibration report of metric percentiles; `GET /zctas/{zcta}/score`.
Acceptance: worked example reproduces 75.8/A and OU 7,299; determinism; weight sensitivity;
scenario 5 missing-data behaviour; `compare_territories`.

## Milestone 4 — Territory registry

`RegistryService` with the transitions in `TERRITORY_ALGORITHM.md` §4, audit notes, reservation
expiry flagging, exceptions, `uq_active_zip` enforcement, `POST /territories`, status endpoints.
Acceptance: registry tests from `TEST_MARKETS.md` (scenarios 2, 9).

## Milestone 5 — Territory generator

`app/services/territory_generator.py` per `TERRITORY_ALGORITHM.md` §1; `POST /territories/propose`.
Acceptance: scenarios 1, 3, 4, 6, 7, 8 plus determinism hash test.

## Milestone 6 — Conflict checker

`app/services/conflict_checker.py` per §2; `POST /conflicts/check`. Acceptance: scenarios 2, 6, 9.

## Milestone 7 — Sales-call market checker

`app/services/market_checker.py` per §3; minimal internal HTML page (`/sales`) with one input box
and the sales view; talking points generated from data. Acceptance: one input → full view in
under a minute; wording review for "no performance guarantee".

## Milestones 8–11

Map (only after 5–7 are trusted), onboarding/n8n hooks, Meta provisioning consumer, performance
learning schema. Specs to be written when reached.
