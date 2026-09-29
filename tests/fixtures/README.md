# Ingestion test fixtures (Milestone 1)

Tiny synthetic inputs shaped exactly like the real public sources so the import code can be
unit tested offline. None of it is real Census or GeoNames data.

| File | Mimics | Cases covered |
|------|--------|---------------|
| `zcta_boundaries_four.geojson` | CB ZCTA5 shapefile (`ZCTA5CE20`, `ALAND20`, `AWATER20`) | 2x2 grid where diagonal cells touch at a point only (not rook-adjacent); one MultiPolygon with an island; one cell over 400 sq mi |
| `zcta_county_rel_sample.txt` | 2020 ZCTA-to-county relationship file (BOM, pipe-delimited) | ZCTA split across two states; county-remainder rows without a ZCTA |
| `geonames_sample.txt` | GeoNames `US.txt` | duplicate postal code (first place wins); ZCTA without a postal row; postal ZIP without a ZCTA |
| `acs_api_response.json` | Data API JSON (header + rows) | sentinel `-666666666`; missing bucket value; ZCTA absent from boundaries |
| `acs_summary/acsdt5y2023-*.dat` | ACS Summary File table-based files | same values as the API fixture plus state/county rows that must be skipped |
| `acs_variable_labels.json` | `variables/<id>.json` labels | label drift detection |

Regenerate the ACS files after editing the values in `generate_acs_fixtures.py`:

    venv/Scripts/python.exe tests/fixtures/generate_acs_fixtures.py
