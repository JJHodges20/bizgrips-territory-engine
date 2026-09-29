# BizGrips Territory Engine

Internal territory intelligence system for BizGrips. It turns a prospect's starting ZIP into a
recommended, contiguous, conflict-free exclusive territory sized by measurable bathroom-conversion
opportunity, using only public Census data, and it keeps the registry of who holds which ZIPs.

The engine recommends; a human approves.

## Status

| Milestone | Scope | State |
|-----------|-------|-------|
| 0 | Repository, dev environment, Phase 0 specifications, fixture markets | Done |
| 1 | Public data ingestion (ACS 5-year + TIGER ZCTA boundaries) | Next |
| 2 | ZIP/ZCTA data API | Planned |
| 3 | Opportunity scoring + Opportunity Units | Planned |
| 4 | Territory registry | Planned |
| 5 | Territory generator | Planned |
| 6 | Conflict checker | Planned |
| 7 | Sales-call market checker | Planned |
| 8+ | Map, onboarding/n8n, Meta, performance learning | Later |

See `docs/IMPLEMENTATION_STATUS.md` for the live state and `docs/MILESTONES.md` for specs.

## Quick start

Requirements: Python 3.12+ (the local venv was created with 3.14), git. Docker only if you want
PostgreSQL/PostGIS instead of SQLite.

Windows (PowerShell):

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
python -m pytest -q
python -m uvicorn app.main:app --reload
```

Or use the task runner: `.\dev.ps1 setup`, `.\dev.ps1 test`, `.\dev.ps1 dev`.

macOS / Linux / CI: `make setup && make test && make dev`.

The API then answers at http://127.0.0.1:8000 (`/health`, `/config/business-rules`, `/docs`).

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
  fixtures.py                 scenario fixture loader
  main.py                     FastAPI app factory
data/fixtures/                deterministic synthetic markets used by tests
scripts/                      import and seed CLIs
migrations/                   Alembic migrations
tests/                        pytest suite
```

## Data sources (all free and public)

- Census ACS 5-Year Estimates (tenure, householder age, year built, income, home value)
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
