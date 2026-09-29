# Fixture markets

Deterministic synthetic markets for tests and development seeding. **None of these numbers are
real Census data**; they are shaped like plausible values for the named places so that examples
read naturally. Real data arrives with Milestone 1.

Layout:

```
grids/<grid_id>.json          ZCTA records + rook adjacency (shared by several scenarios)
scenarios/<scenario_id>.json  grid reference, field overrides, registry state, requests, expectations
```

Loader: `app/fixtures.py` (`load_scenario`, `load_grid`, `list_scenarios`).
Seed a scenario into the dev database: `make seed-fixtures SCENARIO=<scenario_id>`.

Scenario expectations are described in `docs/TEST_MARKETS.md`. The `expected` blocks inside
request objects are consumed by milestone tests as each capability lands (scoring M3, registry
M4, generator M5, conflicts M6); until then `tests/test_fixtures.py` only checks integrity.

Record fields follow `app/schemas/market.py::ZctaRecord`. Overrides may set any field to `null`
to simulate missing Census data. Adjacency pairs are unordered; the loader normalises them.
