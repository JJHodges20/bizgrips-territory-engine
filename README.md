# BizGrips Territory Engine

Internal territory intelligence system for BizGrips. It turns a prospect's starting ZIP into a
recommended, contiguous, conflict-free exclusive territory sized by measurable bathroom-conversion
opportunity, using only public Census data, and it keeps the registry of who holds which ZIPs.

The engine recommends; a human approves.

## Status

| Milestone | Scope | State |
|-----------|-------|-------|
| 0 | Repository, dev environment, Phase 0 specifications, fixture markets | Done |
| 1 | Public data ingestion (ACS 5-year + CB ZCTA boundaries, adjacency, provenance) | Done |
| 2 | ZIP/ZCTA data API | Done |
| 3 | Opportunity scoring + Opportunity Units | Done |
| 4 | Territory registry | Next |
| 5 | Territory generator | Planned |
| 6 | Conflict checker | Planned |
| 7 | Sales-call market checker | Planned |
| 8+ | Map, onboarding/n8n, Meta, performance learning | Later |

See `docs/IMPLEMENTATION_STATUS.md` for the live state and `docs/MILESTONES.md` for specs.

## Quick start

Requirements: Python 3.12+ (the local venv uses 3.14; geopandas/shapely wheels install fine),
git. Docker only if you want PostgreSQL/PostGIS instead of SQLite.

Windows (PowerShell):

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,geo]"
Copy-Item .env.example .env
python -m pytest -q
python -m uvicorn app.main:app --reload
```

Or use the task runner: `.\dev.ps1 setup`, `.\dev.ps1 test`, `.\dev.ps1 dev`.

macOS / Linux / CI: `make setup && make test && make dev`.

The API then answers at http://127.0.0.1:8000 (`/docs` for the interactive reference).

| Endpoint | Returns |
|----------|---------|
| `GET /health` | app, rules version, database status |
| `GET /config/business-rules`, `GET /config/census-variables` | the version-controlled configuration |
| `GET /zctas/{zcta}` | every stored column for one ZCTA, derived shares, `missing_fields`; `?include_geometry=true` adds GeoJSON |
| `GET /zctas?state=&city=&tier=&limit=&offset=` | paged list filtered by state, primary-city prefix and market tier |
| `GET /zctas/{zcta}/neighbors` | rook-adjacent ZCTAs with shared boundary length |
| `GET /zctas/{zcta}/score` | live Opportunity Score, tier, components, Opportunity Units, plus the cached values |
| `GET /imports`, `GET /imports/fields` | import runs and which import last wrote each field |

Unknown ZCTAs answer 404 with `detail.code = NO_MARKET_DATA`.

## Scoring the data (Milestone 3)

```powershell
python scripts/score_all.py            # cache score, tier and OU on every ZCTA; snapshot the rules version
python scripts/calibration_report.py   # docs/CALIBRATION_REPORT.md: ramps vs. the real ACS distribution
```

Scoring is a pure function of the stored record and `app/config/business_rules.yaml`
(`app/services/scoring.py`, spec in `docs/SCORING_SPEC.md`). Re-run `score_all.py` after any
import or rules change; the cached tier drives `GET /zctas?tier=` and the generator.

## Importing the public data (Milestone 1)

```powershell
.\dev.ps1 import-data        # or: make import-data
```

This runs `scripts/import_geography.py` then `scripts/import_census.py`:

- downloads the CB ZCTA5 2020 boundary shapefile (67 MB), the ZCTA-to-county relationship
  file, GeoNames US postal codes and six ACS 2019-2023 summary-file tables (~215 MB) into
  `data/raw/` with sha256 checksums (cached; `--refresh` re-downloads);
- computes centroids, land/water area and rook adjacency with shared boundary lengths
  (EPSG:5070) for ~33,800 ZCTAs, assigns the dominant state and primary city;
- validates the ACS variable labels, converts sentinels to NULL, sums the age and year-built
  buckets and upserts every ZCTA with provenance rows in `data_source_imports` and
  `data_field_provenance`. Re-running updates rows in place and adds new import records.

A free Census API key (`CENSUS_API_KEY` in `.env`) switches the census import to the Data API;
without one it reads the same estimates from the summary files. The whole import takes a few
minutes on a laptop. `--dry-run` prints the plan; `--with-geometry` also stores GeoJSON polygons.

Optional PostgreSQL: `docker compose up -d db`, then set `DATABASE_URL` in `.env` to
`postgresql+psycopg://bizgrips:bizgrips@localhost:5432/bizgrips_territory` and install the
`postgres` extra (`pip install -e ".[dev,postgres]"`). Run `make db-upgrade` to create the schema.

## Repository map

```
CLAUDE.md                     guidance for Claude Code sessions (read first)
docs/
  ROADMAP_V1.1.md             master roadmap (verbatim from BizGrips)
  BIZGRIPS_TERRITORY_STANDARD.md   business rules v1.0 (Phase 0 deliverable)
  SCORING_SPEC.md             Opportunity Score + Opportunity Units
  TERRITORY_ALGORITHM.md      generator / conflict checker / market checker
  DATA_DICTIONARY.md          every field, its Census source and provenance
  TEST_MARKETS.md             fixture scenarios with expected behaviour
  MILESTONES.md               per-milestone specs and acceptance criteria
  IMPLEMENTATION_STATUS.md    current milestone, decisions, next task
app/
  config/                     settings, business_rules.yaml, census_variables.yaml, loaders
  models/                     SQLAlchemy ORM (markets, adjacency, territories, assignments, config, provenance)
  repositories/               DB access (Milestone 2+)
  services/                   pure domain logic (Milestone 3+)
  api/                        FastAPI routers
  ingest/                     public-data ingestion (downloads, geography, ACS, upserts)
  fixtures.py                 scenario fixture loader
  main.py                     FastAPI app factory
data/fixtures/                deterministic synthetic markets used by tests
scripts/                      import and seed CLIs
migrations/                   Alembic migrations
tests/                        pytest suite (tests/fixtures: synthetic ingestion inputs)
```

## Data sources (all free and public)

- Census ACS 5-Year Estimates (tenure, householder age, year built, income, home value), via
  the Data API (free key) or the ACS Summary File table-based downloads (no key)
- Census cartographic boundary files for ZCTAs (geometry, land area, adjacency)
- Census ZCTA-to-county relationship file (state assignment)
- GeoNames US postal codes (primary city names and postal ZIP existence)

Details, variable IDs and refresh rules: `docs/DATA_DICTIONARY.md`.

## Important caveats

- Market data is published for ZCTAs, which approximate USPS ZIP codes. Before a territory is
  contracted or pushed to ad targeting the ZIP list must be validated against usable postal ZIPs.
- All V1 thresholds, weights and bands are hypotheses held in `app/config/business_rules.yaml`.
- Scores and Opportunity Units are comparative indices for sales intelligence. They do not
  predict or guarantee marketing performance.
