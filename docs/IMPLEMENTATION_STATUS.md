# Implementation Status

Read this first in every session. Update it at the end of every session.

## Current milestone

**Milestone 6 — Conflict checker: complete (2026-09-29).**
Next up: **Milestone 7 — Sales-call market checker** (spec in `MILESTONES.md`, algorithm in
`TERRITORY_ALGORITHM.md` section 3). Plan first; it composes the pieces that now exist
(postal ZIP to ZCTA lookup, score, availability, conflict check, generator preview).

## Completed

### Milestone 0 (2026-09-29)

- Phase 0 specifications: Territory Standard v1.0, Scoring Spec v1.0, Data Dictionary v1.0,
  Territory Algorithm v1.0, Test Markets v1.0, Milestone specs, this status file, roadmap stored
  verbatim.
- Configuration: `app/config/business_rules.yaml` (all tunables) with a validated Pydantic
  loader; `app/config/census_variables.yaml` (ACS variable map, geography sources); `.env`
  settings via pydantic-settings.
- Data model: SQLAlchemy models for `zcta_markets`, `zcta_adjacency`, `territories`,
  `territory_zip_assignments` (with partial unique index `uq_active_zip`), `scoring_configs`,
  `data_source_imports`, `data_field_provenance`; Alembic configured with an initial migration.
- App: FastAPI factory with `/health`, `/config/business-rules`, `/config/census-variables`.
- Fixtures: four base grids and nine scenarios; loader in `app/fixtures.py`;
  `scripts/seed_fixtures.py`. Tooling: `pyproject.toml`, Makefile + `dev.ps1`, docker-compose
  (PostGIS), ruff, pytest.

### Market-research cross-check (2026-09-29)

Twelve client briefs compared with the V1 signals: `MARKET_RESEARCH_CROSSCHECK.md`. Outcome:
keep the 45+ homeowner age floor, no rule values changed, length of home ownership (ACS
B25038) recorded as a V2 candidate.

### Milestone 1 (2026-09-29)

- `app/ingest/`: checksummed downloads (`download.py`), boundary processing (`geography.py`:
  centroids in EPSG:5070, ALAND/AWATER areas, rook adjacency with shared boundary length,
  dominant state from the ZCTA-to-county relationship file, primary city / postal ZIP from
  GeoNames), ACS ingestion (`census.py`: Data API and Summary File backends, sentinel cleaning,
  bucket sums, label validation) and portable upserts with provenance (`store.py`).
- `scripts/import_geography.py` and `scripts/import_census.py` rewritten as thin CLIs
  (`--dry-run`, `--refresh`, `--with-geometry`, `--vintage`, `--source`, local-file overrides).
  `make import-data` / `.\dev.ps1 import-data` run both.
- `app/repositories/markets.py`: get by ZCTA, list by state, search by city, neighbours,
  count; all return `ZctaRecord`.
- Tests on synthetic fixtures in `tests/fixtures/` (4-polygon boundary set, relationship and
  GeoNames samples, ACS API and summary-file samples, label metadata): 77 tests pass.
- Real import run on the laptop (SQLite): 33,791 ZCTAs with geography, 90,128 adjacent pairs
  (median 5 neighbours, 176 ZCTAs isolated, mostly islands), 33,772 ZCTAs with ACS 2023 data
  (the 19 boundary-only ZCTAs keep NULL demographics), 0 cross-table inconsistencies, income
  NULL for 3,154 and home value NULL for 3,461 ZCTAs (sentinels), 1,013 ZCTAs over 400 sq mi
  flagged unserviceable, 149 ZCTAs without a GeoNames postal ZIP. Geography ~35 s, census
  ~6 s (after the ~280 MB of downloads). Spot checks: 80123 has 6 neighbours, 44301 has 4.
  A second run changed no row counts and added new import records only.

### Milestone 2 (2026-09-29)

- Read API: `GET /zctas/{zcta}` (all columns, derived shares, explicit `missing_fields`,
  optional GeoJSON), `GET /zctas?state=&city=&tier=` (paged, ordered by code),
  `GET /zctas/{zcta}/neighbors` (with shared boundary length), `GET /imports` and
  `GET /imports/fields` (provenance). Unknown ZCTAs answer 404 `NO_MARKET_DATA`; malformed
  codes 422. Response models in `app/schemas/api.py` mirror the data dictionary.
- Plumbing: per-request session dependency (`app/api/deps.py`); `create_app(engine=...)`
  serves an existing engine so tests run on in-memory SQLite; fixture seeding moved to
  `app/ingest/seed.py` (the script delegates to it); ORM-row repository variants and
  `app/repositories/provenance.py`.
- Tests: seven endpoint tests on fixture-seeded databases (`denver_suburban_available`,
  `missing_census_fields`); 84 tests pass. Smoke-checked against the real import.
- Not included (by design): ZIP availability / registry state on ZCTA responses, which
  arrives with the registry in Milestone 4; write endpoints.

### Milestone 3 (2026-09-29)

- `app/services/scoring.py`: `score_zcta`, `opportunity_units`, `score_territory`,
  `compare_territories` as pure functions over `ZctaRecord` + `BusinessRules`; schemas in
  `app/schemas/scoring.py`. The worked example reproduces 75.8 / Tier A / 7,299 OU, the
  missing-income variant 74.2 / B with completeness 0.85, and every scenario-5 expectation.
- `scripts/score_all.py` caches score, tier and OU on `zcta_markets` (33,791 rows in about
  3 s) and snapshots the rules in `scoring_configs`; `scripts/calibration_report.py` writes
  `CALIBRATION_REPORT.md`; `GET /zctas/{zcta}/score` computes live and shows the cache.
- Tests: worked example, zero policy, scenario 5, determinism (repeat and input order),
  weight sensitivity (direction and magnitude), ramps and tiers, OU edge cases, territory
  aggregation and comparison, the script end to end, the endpoint; 95 tests pass.
- `TEST_MARKETS.md` fixture table now carries the exact computed scores (grid total 59,000 OU).

### Milestone 4 (2026-09-29)

- `app/services/registry.py`: availability from the blocking-assignment snapshot (own ZIPs are
  never conflicts; PENDING_RELEASE past its date counts as available; expired reservations
  block and carry `RESERVATION_EXPIRED`), pure `plan_*` transition rules (reserve, extend,
  activate, cancel, pending release, release), exception validation against the allowed list,
  audit lines, `T-000001` ids, and `RegistryService` which loads/applies through
  `app/repositories/registry.py`. `uq_active_zip` remains the database backstop.
- API: `POST /territories` (PROPOSED from a ZIP list; 409 on conflicts, 422 on unknown ZCTAs),
  list/get with flags, one endpoint per transition, `POST /territories/{id}/exceptions`,
  `GET /zips/{zip}/availability`, `GET /registry/flags`, `POST /registry/sweep`. Rule
  violations map to JSON errors with stable codes (`INVALID_TRANSITION`, `APPROVAL_REQUIRED`,
  `ZIP_CONFLICT`, `EXCEPTION_NOT_ALLOWED`, `NO_MARKET_DATA`, `TERRITORY_NOT_FOUND`).
- Tests: scenario 2 (active ZIP cannot be assigned twice, own client not in conflict, DB
  backstop), scenario 9 (expired reservation blocks and is flagged until a human cancels it,
  then the ZIPs are re-reserved), the full lifecycle with dates and audit trail, reserve-time
  conflicts, exceptions, due-release completion, and the endpoints; 104 tests pass.

### Milestone 5 (2026-09-29)

- `app/services/territory_generator.py::generate_territory`: start resolution (NO_MARKET_DATA
  / START_ZIP_UNAVAILABLE with nearest available suggestions), requested-ZIP seeding with
  deferral, frontier expansion in the fixed priority order (availability, contiguity,
  serviceability, score minus 1.5 points per mile, target band with 10% tolerance), exclusion
  reasons, aggregates via `score_territory`, target status and flags, one explanation line per
  included ZCTA plus one per exclusion.
- `app/services/market.py::MarketGraph` (records, adjacency, live scores, haversine distances,
  components) built from fixture grids or by `app/repositories/market_graph.py` (bounding box
  around the start, 1.5x the radius); `app/services/conflicts.py` classifies requested ZIPs
  (available / reserved / protected / pending / own / unknown, contiguity) and ranks nearest
  available ZCTAs.
- `POST /territories/propose` (`?persist=true` records the PROPOSED territory with the
  proposal as its generation snapshot; a FAILED proposal is a normal 200).
- Tests: every generator scenario's `expected` block is executed as assertions (1, 3, 4, 5, 6,
  7, 8), start-ZIP failure with suggestions (2), NO_MARKET_DATA, determinism over 100 runs and
  across a separate Python process (fingerprint), endpoint tests; 116 tests pass. Scenario 5
  now requests the unscored ZIPs so their UNSCORED exclusion is observable.
- Real data: a Standard proposal from 80123 takes about 0.1 s (3 ZCTAs, 22,290 OU, Tier A);
  from 82633 (Douglas, WY) the proposal stops at the start ZIP with UNSERVICEABLE_LAND_AREA
  and BELOW_MINIMUM_VIABLE, as designed.

### Milestone 6 (2026-09-29)

- `app/services/conflict_checker.py::check_conflicts`: classification (from Milestone 5's
  `classify_zips`) plus replacement suggestions per conflicting ZIP, nearest first, then score,
  limited to `generator.replacement_suggestions`, adjacent to the non-conflicting requested
  ZIPs or to an explicit anchor. The generator now routes its requested-ZIP conflicts through
  it with the proposal as anchor, so replacements touch the territory (scenario 9).
- `POST /conflicts/check` with `app/repositories/market_graph.py::load_market_graph_for_zips`
  (bounding box over the known codes); duplicates collapsed, unknown codes reported.
- Tests: scenario 2 (protected ZIP, nearest replacements, own client not in conflict), scenario 9
  (expired reservation flagged, replacements adjacent to 80123, reserving client named),
  scenario 6 (contiguity and components, unknown codes), pending release past its date counts
  as available, determinism, the endpoint; scenario 9 added to the generator scenario run and
  scenario 6's fixture now carries its conflict-check expectation; 122 tests pass.
- Real data: a five-ZIP check around Littleton answers in about 0.1 s and names the fixture
  reservation still present in the dev database.

## Known issues / open questions

- The dev database still contains the fixture territories seeded in Milestone 0 (for example
  a RESERVED T-000002 on 80127/80129), so real proposals around Littleton exclude 80127 as
  BLOCKED_RESERVED. Cancel them through the API or reseed with `--replace` before demos.

- The registry has no authentication yet; `approved_by` is a trusted string. Access control
  is a deployment concern to settle before sales staff use the write endpoints (Milestone 8+).

- **Calibration decision (2026-09-29, BizGrips: keep rules 1.0.0 for now):** with the V1 ramps 40% of scorable ZCTAs
  are Tier A and 34% Tier B, because three ceilings sit below or near the national median
  (owner share ceiling 0.85 vs median 0.78; owner 45+ ceiling 0.80 vs median 0.76; pre-2000
  ceiling 0.85 vs median 0.83), so 29-42% of ZCTAs max out those components. Projections on
  the real data (nothing changed):

  | Option | A | B | C | D | Littleton 80123 | Akron 44301 | Newark 07103 |
  |--------|---|---|---|---|-----------------|-------------|--------------|
  | Current ramps (1.0.0) | 40% | 34% | 13% | 4% | 77.9 A | 60.0 B | 35.7 D |
  | Recommended: keep floors, ceilings to p90 (0.925 / 0.90 / 0.95) | 16% | 40% | 27% | 8% | 67.4 B | 53.5 C | 29.5 D |
  | Full p10-p90 ramps | 8% | 24% | 34% | 27% | 54.3 C | 42.6 D | 16.2 D |

  Recommendation (not applied; revisit once the generator and registry are in use): the middle
  option as business rules 1.1.0 (ceilings only). It keeps
  Tier A meaningful (top ~16%) without pushing solid suburban markets into C. Changing it also
  means updating the worked example in `SCORING_SPEC.md` and the fixture table. Income and
  density ramps already fit the p10-p90 range and need no change.
- OU sanity check: median ZCTA 396 OU, top quartile 1,700-5,700 OU, so a Standard territory
  (20,000-32,000 OU) is roughly 5-15 suburban ZCTAs, consistent with the size-class table.

- All numeric rules are hypotheses. Component ramps need calibration against real ACS
  percentiles (Milestone 3 calibration report); the data for that is now in the dev database.
- The Census Data API requires a free key for data queries (2026 change). Without one the
  census import uses the ACS Summary File downloads; both paths are tested, only the summary
  file path has run against live data so far.
- The dev database (`data/processed/territory.db`) may also hold fixture territories seeded
  during Milestone 0; real market rows overwrote the fixture market rows for the same ZCTAs.
  Use `scripts/seed_fixtures.py --replace` if a clean fixture-only state is needed.
- Alembic migrations are generated against SQLite; verify against PostgreSQL before the first
  shared deployment (`render_as_batch` is enabled for SQLite).
- Postal ZIP validation uses GeoNames; if a stricter USPS source is required later, swap the
  `postal_places` source in `census_variables.yaml`.

## Next task

Milestone 7, step 1: `app/services/market_checker.py::check_market` (`MarketQuery` ->
`MarketCheck`): map a pasted postal ZIP to its ZCTA (or NO_MARKET_DATA), return the score,
tier, OU, availability with blocking details, the conflict result for any pasted list, and a
quick generator preview, then `POST /market/check` for the sales-call flow.

## Decisions log

| Date | Decision | Why |
|------|----------|-----|
| 2026-09-29 | Territory size measured in Opportunity Units, not population or raw owner households. | Roadmap principle 4: fairness = comparable economic opportunity. |
| 2026-09-29 | OU = owner households × age factor × housing factor × income factor with `age_45_plus_floor = 0`, so OU ≈ owner 45+ discounted. | Keeps the index explainable ("about N desirable homeowner households") while honouring the 45+ priority. |
| 2026-09-29 | Runtime engine is relational-only; adjacency/centroids/area precomputed at import. | SQLite for dev/tests, no PostGIS dependency for scoring or generation; PostGIS remains optional for the map. |
| 2026-09-29 | Territory state derived solely from `territory_zip_assignments`; no status cache on `zcta_markets`. | One source of truth (roadmap principle 6). |
| 2026-09-29 | Rook contiguity (shared boundary length > 0), not queen. | Point-touching ZCTAs are not practically contiguous. |
| 2026-09-29 | Selection priority = score − 1.5 points per mile from start. | "Rational outward expansion" without snaking along high-score ZIPs; tunable. |
| 2026-09-29 | Expired reservations stay blocking until a human releases them. | Roadmap principle 5; automation is a Phase 11 concern. |
| 2026-09-29 | ACS vintage 2023 (2019–2023 5-year) recorded; label checks guard bucket drift. | Provenance and safe refreshes. |
| 2026-09-29 | Fixture values are synthetic but placed on real ZIP codes from the roadmap examples. | Keeps examples relatable while making clear that tests do not depend on live data. |
| 2026-09-29 | Homeowner age floor stays at 45+ after the market-research cross-check. | Half the client ICPs start at 45; adult-child decision makers fall in 45–60; a 55+ floor would shrink OU everywhere without improving ranking. |
| 2026-09-29 | ACS Summary File table-based downloads are the default census backend; the Data API is used when a key is configured. | The API now needs a key; the summary files are free, keyless, checksummed and carry identical estimates. |
| 2026-09-29 | Centroid = polygon centroid in EPSG:5070, falling back to the representative point when the centroid is outside the polygon. | Distances need a true centre; the fallback keeps every stored point inside its ZCTA. |
| 2026-09-29 | Land and water area come from the file's ALAND/AWATER attributes, not from the generalised geometry. | The attributes are the un-generalised official areas. |
| 2026-09-29 | Bucket sums are NULL when any component is unavailable; negative values outside the sentinel list are also NULL. | Never store a partial sum or a jam value as a number. |
| 2026-09-29 | The read API exposes `missing_fields` and `NO_MARKET_DATA` explicitly; `tier` filters match the stored tier exactly (null until scored). | Missing data is explicit, never a silent zero; unscored is distinguishable from tier U. |
| 2026-09-29 | Scores are cached by `score_all.py` but `GET /zctas/{zcta}/score` always computes live and returns the cache beside it. | Rules changes become visible immediately; drift between cache and rules is never hidden. |
| 2026-09-29 | Territory shares use paired totals; OU of a ZCTA with zero owner households is 0, not None. | No bias from a single missing field; empty is different from unknown. |
| 2026-09-29 | Ramp recalibration deferred to a BizGrips decision; report and projections recorded instead of changing rules 1.0.0. | Every rule change is a human decision; the projections give the numbers needed to make it. |
| 2026-09-29 | BizGrips chose to keep the 1.0.0 ramps for now after reviewing the projections. | Operational evidence first; the report and projections stay on file for a later revision. |
| 2026-09-29 | Proposals keep their ZIP list in `generation_snapshot_json`; assignments exist from RESERVED onwards. | Assignment statuses have no PROPOSED value and proposals must not block anyone. |
| 2026-09-29 | A proposal containing another client's blocked ZIP is refused, and the check repeats at reservation. | Proposals never carry known conflicts; state can change between proposal and reservation. |
| 2026-09-29 | Due releases (PENDING_RELEASE past `release_date`) complete automatically when touched or swept; expired reservations never do. | Standard section 11 makes the release date the event; section 8 keeps expiry a human decision. |
| 2026-09-29 | `as_of` is an explicit parameter of every registry action; the API defaults it to today (UTC). | Deterministic tests and back-dated actions without clock reads inside services. |
| 2026-09-29 | Requested ZIPs must be scored, like frontier ZIPs; an unscored requested ZIP is excluded UNSCORED. | Sizing relies on OU; an unscored ZIP would silently add zero opportunity. |
| 2026-09-29 | `excluded` lists only ZCTAs that were on the frontier or requested; neighbours never reached are absent. | Reasons are only given for ZCTAs the algorithm actually evaluated; scenario 5 was adjusted to request the unscored ZIPs. |
| 2026-09-29 | Proposals are not stored unless `persist=true`; the stored snapshot is the full proposal JSON. | Sales can explore freely; only a deliberate step creates registry state, and the approved list keeps its explanation. |
| 2026-09-29 | Replacement suggestions must touch the non-conflicting part of the request (or the proposal); a lone blocked ZIP gets the nearest available ZCTAs instead. | A replacement is only useful if it keeps the territory contiguous; with nothing to touch, distance is the best guide. |
