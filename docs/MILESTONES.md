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

## Milestone 8 — Territory workspace (registry board, map, custom groupings)

**Goal:** an internal web app that lets sales and managers see which areas are taken, manage
the registry by hand, view ZCTAs on a map, select custom ZIP groupings and score them, and run
the sales check, all from one professional interface. BizGrips decided (2026-09-29) to build
this now and to keep onboarding/n8n hooks, Meta provisioning and performance learning on hold.

**Inputs:** the existing API (registry, generator, conflicts, market check, scores) plus:
- `GET /map/zctas?bbox=minLon,minLat,maxLon,maxLat&as_of=&client_id=` — GeoJSON
  FeatureCollection of the ZCTAs whose bounding box intersects the viewport, with score, tier,
  OU, households, availability, blocking territory/client and flags as properties.
- `GET /map/territories/{territory_id}` — the territory's ZCTAs as GeoJSON plus bounds.
- `GET /map/locate?q=` — a ZIP or "City, ST" resolved to a centre and bounds.
- `POST /territories/evaluate` — score a custom ZIP grouping: aggregates, target status for a
  size class, contiguity and components, conflicts, per-ZIP details, flags.
- Geometry: `scripts/import_geography.py --with-geometry` stores simplified polygons
  (Douglas-Peucker, 0.0005 degrees, topology preserved) and every import stores each ZCTA's
  WGS84 bounding box (four new `zcta_markets` columns, Alembic revision `b7c1d2e3f4a5`).

**Outputs:** `app/static/` single-page app served at `/app` (vanilla ES modules, vendored
Leaflet 1.9.4, OpenStreetMap tiles by default with the tile URL configurable in
`app/static/config.js`), with three views:
1. **Registry board** — territories with status, flags (expired reservation, release due),
   client, ZIP count, dates; filters; detail drawer (overview, ZIPs, audit trail, exceptions);
   every registry transition and exception as a form; manual "new territory" from a ZIP list;
   "show on map".
2. **Map** — ZCTA polygons coloured by availability or by tier/score (toggle), legend, hover
   card (ZIP, city, tier, score, OU, status, client), search-and-fly, click to add/remove ZCTAs
   to a custom grouping, selection panel with live evaluation (score, tier, OU, households,
   owner 45+, contiguity, conflicts, target band), "generate from here", "save as proposal".
3. **Sales check** — the Milestone 7 view (input box, availability, talking points,
   statistics, suggested territory) in the same design system, with "show on map".
A shared design system: layout with navigation rail, typography and colour tokens, status
badges, tables, drawers, modals, toasts, empty and loading states, responsive down to tablet.

**Business rules:** the UI changes registry state only through the existing endpoints (named
approver, reasons, dates); the map never writes except "save selection as proposal", which
creates a PROPOSED territory; client names on conflicts are internal-use only; wording never
implies performance guarantees; colours: available green, reserved amber, protected red,
pending release violet, unscored grey; tiers A-D on a single hue ramp.

**Edge cases:** viewport too large (the server refuses bboxes over 4 x 4 degrees or more than
3,000 features with a "zoom in" message); ZCTAs without geometry (skipped and counted);
multipolygons; unscored ZCTAs; selections containing blocked or unknown ZIPs (evaluated,
flagged, cannot be saved while blocked); tile server unreachable (polygons still render on a
plain background); a territory whose ZCTAs lack geometry (list still shown).

**Acceptance:** Denver-metro viewport loads in under 2 s from the local database; evaluating a
five-ZCTA selection returns in under 1 s; saving creates a PROPOSED territory visible on the
board; each transition works from the board; sales check runs from the UI; all new endpoints
covered by API tests on fixture-seeded databases with synthetic square geometries; every
JavaScript module parses (esprima check in the test suite); no console errors on load.

**Fixtures:** `tests/fixtures/zcta_boundaries_four.geojson` (bbox/geometry pipeline) and
synthetic square geometries attached to the Denver grid rows in tests.

**Out of scope:** authentication and roles (internal network only for now), editing market
data, vector tiles or PostGIS, printing/exports, onboarding/n8n, Meta, performance learning.

---

## Milestones 9–11 (on hold)

Onboarding/n8n hooks, Meta provisioning consumer, performance learning schema. Specs to be
written when BizGrips brings them forward.
