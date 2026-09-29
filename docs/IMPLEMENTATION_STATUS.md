# Implementation Status

Read this first in every session. Update it at the end of every session.

## Current milestone

**Milestone 0 — Repository + development environment: complete (2026-09-29).**
Next up: **Milestone 1 — Public data ingestion** (spec in `MILESTONES.md`). Use plan mode first.

## Completed

- Phase 0 specifications: Territory Standard v1.0, Scoring Spec v1.0, Data Dictionary v1.0,
  Territory Algorithm v1.0, Test Markets v1.0, Milestone specs, this status file, roadmap stored
  verbatim.
- Configuration: `app/config/business_rules.yaml` (all tunables) with a validated Pydantic
  loader; `app/config/census_variables.yaml` (ACS variable map, geography sources); `.env`
  settings via pydantic-settings.
- Data model: SQLAlchemy models for `zcta_markets`, `zcta_adjacency`, `territories`,
  `territory_zip_assignments` (with partial unique index `uq_active_zip`), `scoring_configs`,
  `data_source_imports`, `data_field_provenance`; Alembic configured with an initial migration.
- App: FastAPI factory with `/health` and `/config/business-rules`.
- Fixtures: three base grids (Denver suburban lattice, Wyoming rural chain, Kansas City state
  border, symmetric chain) and nine scenarios; loader in `app/fixtures.py`; `scripts/seed_fixtures.py`.
- Tooling: `pyproject.toml`, Makefile + `dev.ps1`, docker-compose (PostGIS), ruff, pytest.
- Tests: business-rules validation, settings, ORM schema + `uq_active_zip`, fixture integrity
  (adjacency symmetric, references resolve, scenarios parse), health endpoint.

## Known issues / open questions

- All numeric rules are hypotheses. Component ramps need calibration against real ACS
  percentiles (Milestone 3 calibration report).
- Python 3.14 venv: geospatial extras (`geopandas`, `pyogrio`) are only needed by import
  scripts; confirm wheels install on 3.14 at the start of Milestone 1, otherwise pin 3.12 for
  the import environment.
- Alembic migrations are generated against SQLite; verify against PostgreSQL before the first
  shared deployment (`render_as_batch` is enabled for SQLite).
- Postal ZIP validation uses GeoNames; if a stricter USPS source is required later, swap the
  `postal_places` source in `census_variables.yaml`.

## Next task

Milestone 1, step 1: implement `scripts/import_geography.py` download + boundary load +
adjacency on a tiny synthetic shapefile fixture, then the real CB file.

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
