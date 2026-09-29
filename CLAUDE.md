# CLAUDE.md — BizGrips Territory Engine

## Purpose
Internal BizGrips territory intelligence system. Given a contractor's starting ZIP it scores
nearby ZCTAs for bathroom-conversion opportunity using public Census data, builds a contiguous
territory of comparable opportunity, checks exclusivity conflicts against the registry, and
requires a named human to approve before a territory becomes protected.
Master roadmap: `docs/ROADMAP_V1.1.md`.

## Current milestone
Milestone 0 (repository + development environment + Phase 0 specifications) is complete.
Next: Milestone 1 (public data ingestion). Always read `docs/IMPLEMENTATION_STATUS.md` first.

## Read these before changing territory logic
1. `docs/BIZGRIPS_TERRITORY_STANDARD.md` — the business rules the software enforces
2. `docs/SCORING_SPEC.md` — Opportunity Score and Opportunity Units
3. `docs/TERRITORY_ALGORITHM.md` — generator, conflict checker, market checker
4. `docs/DATA_DICTIONARY.md` — fields, Census sources, provenance
5. `app/config/business_rules.yaml` — every tunable number (all are V1 hypotheses)
6. `docs/TEST_MARKETS.md` and `data/fixtures/` — scenarios with expected behavior
7. `docs/MILESTONES.md` — spec for the milestone you are building

## Architecture
- Python 3.12+, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic 2, pytest, ruff.
- Database: SQLite by default for development and tests; PostgreSQL (PostGIS optional) via
  `docker-compose.yml` for shared deployments. Set `DATABASE_URL` in `.env`.
- The runtime engine is relational-only. Adjacency, centroids and land area are precomputed
  during import (geopandas/shapely, optional `geo` extra), so scoring and territory generation
  never need PostGIS.
- Layers: `app/config` (settings + business rules), `app/models` (ORM), `app/repositories`
  (DB access), `app/services` (pure domain logic: scoring, opportunity units, generator,
  conflicts, registry), `app/api` (FastAPI routers), `scripts/` (import CLIs), `app/fixtures.py`
  (scenario loader).
- Domain services are pure functions over plain data plus `BusinessRules`. No DB sessions
  inside scoring or generation. Repositories load data; services compute; API serialises.

## Canonical terminology
- **ZCTA**: Census ZIP Code Tabulation Area (5 digits). Market data is keyed by ZCTA. "ZIP" in
  UI text means ZCTA unless a postal ZIP is explicitly meant.
- **Owner households**: owner-occupied housing units (ACS `B25003_002E`).
- **Owner 45+**: owner households whose householder is 45 or older (`B25007_006E`–`_011E`).
- **Opportunity Score**: 0–100 per ZCTA from weighted component scores (see SCORING_SPEC).
- **Market Tier**: A/B/C/D from score thresholds; `U` means unscored (insufficient data).
- **Opportunity Units (OU)**: comparative index ≈ owner 45+ households discounted for newer
  housing stock and lower purchasing power. Territory size bands are expressed in OU.
- **Territory statuses**: PROPOSED, RESERVED, ACTIVE_PROTECTED, PENDING_RELEASE, RELEASED,
  CANCELLED. **AVAILABLE** is a ZIP-level state meaning "no blocking assignment".
- **Contiguity**: rook adjacency (shared boundary length > 0). A territory must be one
  connected component of the adjacency graph.

## Business rules in one breath (config is the source of truth)
- Size bands in OU: small 10k–20k, standard 20k–32k, large 32k–45k; absolute max 50k OU or
  40 ZCTAs; minimum viable 10k.
- Serviceability: default radius 30 mi, hard max 45 mi from the starting ZCTA centroid; a ZCTA
  over 400 sq mi of land is flagged unserviceable and never auto-selected.
- Score weights: owner concentration .35, owner 45+ .25, housing age .20, purchasing power .15,
  serviceability .05.
- A ZIP that is RESERVED, ACTIVE_PROTECTED or PENDING_RELEASE for another client is a conflict.
  The engine never overrides a conflict; only a human exception with a recorded reason can, and
  never against ACTIVE_PROTECTED.
- The engine proposes. RESERVED and ACTIVE_PROTECTED require `approved_by`.

## Commands
```
make setup        # create/upgrade venv, install [dev] extras, copy .env.example -> .env
make test         # pytest -q
make lint         # ruff check
make format       # ruff format + fix
make dev          # uvicorn app.main:app --reload
make db-upgrade   # alembic upgrade head
make seed-fixtures SCENARIO=denver_suburban_available   # load a fixture market into the dev DB
make import-data  # Milestone 1 (not implemented yet)
```
Windows without GNU make: `.\dev.ps1 <target>` provides the same targets.
Direct equivalents: `venv/Scripts/python.exe -m pytest -q`, `... -m ruff check .`.

## Conventions
- Never hard-code a business number. Add it to `app/config/business_rules.yaml`, model it in
  `app/config/business_rules.py`, and document it in the Territory Standard.
- Deterministic logic only: stable sort keys with explicit tie-breakers (distance asc, OU desc,
  zcta asc); round only at output; no randomness; no wall-clock reads inside services (pass
  `as_of` in).
- Missing data is explicit: `None` in, `missing_fields` / flags out. Never coerce to 0.
- Every import records provenance (dataset, vintage, variables, import timestamp).
- Tests use scenario fixtures from `data/fixtures/`. Add or extend a scenario before changing
  generator behaviour, and record expected behaviour in `docs/TEST_MARKETS.md`.
- ruff, line length 100, type hints throughout `app/`.
- Commit at milestone boundaries with `docs/IMPLEMENTATION_STATUS.md` updated.

## Constraints
- V1 and V2 must work with zero BizGrips performance data.
- Do not build the map before the generator and registry are trusted (Milestone 8).
- Canonical scoring and geography logic lives here, never only in n8n.
- Scores and OU are comparative indices, not predictions or guarantees. Output wording must
  never imply otherwise.
