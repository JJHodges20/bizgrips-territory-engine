"""Geography ingestion on the 4-polygon fixture: centroids, areas, rook adjacency, state, city."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ingest.geography import (
    AdjacentPair,
    adjacency_degrees,
    read_geonames_places,
    read_zcta_state_overlap,
)
from app.ingest.store import ImportMeta, write_geography
from app.models import DataFieldProvenance, DataSourceImport, ZctaAdjacency, ZctaMarket

gpd = pytest.importorskip("geopandas")

from app.ingest.geography import compute_adjacency, compute_geography, load_boundaries  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
BOUNDARIES = FIXTURES / "zcta_boundaries_four.geojson"
# Expected shared edges: 0.05 deg latitude ~ 5.56 km, 0.05 deg longitude at 39.6N ~ 4.29 km.
EXPECTED_PAIRS = {
    ("11111", "11112"): 5560,
    ("11111", "11113"): 4290,
    ("11112", "11114"): 4290,
    ("11113", "11114"): 5560,
}


@pytest.fixture(scope="module")
def gdf():
    return load_boundaries(BOUNDARIES)


def test_centroids_inside_and_areas_from_attributes(gdf) -> None:
    geography = {g.zcta: g for g in compute_geography(gdf)}
    assert list(geography) == ["11111", "11112", "11113", "11114"]
    a = geography["11111"]
    assert a.latitude == pytest.approx(39.625, abs=1e-3)
    assert a.longitude == pytest.approx(-105.075, abs=1e-3)
    assert a.land_area_sq_miles == pytest.approx(22_000_000 / 2_589_988.11, rel=1e-6)
    assert a.water_area_sq_miles == pytest.approx(1_870_000 / 2_589_988.11, rel=1e-6)
    assert a.geometry_geojson is None
    big = geography["11114"]  # multipolygon: point must land inside the main part
    assert big.land_area_sq_miles > 3800
    assert -105.05 < big.longitude < -104.0 and 38.6 < big.latitude < 39.6
    with_geometry = compute_geography(gdf, with_geometry=True)[0]
    assert with_geometry.geometry_geojson is not None
    assert '"type":"Polygon"' in with_geometry.geometry_geojson.replace(" ", "")


def test_rook_adjacency_excludes_point_touches(gdf) -> None:
    pairs = compute_adjacency(gdf)
    found = {(p.zcta_a, p.zcta_b): p.shared_boundary_length_m for p in pairs}
    assert set(found) == set(EXPECTED_PAIRS)  # 11111-11114 and 11112-11113 touch at a point only
    for key, expected in EXPECTED_PAIRS.items():
        assert found[key] == pytest.approx(expected, rel=0.05), key
    assert all(p.zcta_a < p.zcta_b for p in pairs)
    assert pairs == sorted(pairs)
    assert adjacency_degrees(pairs) == {"11111": 2, "11112": 2, "11113": 2, "11114": 2}


def test_dominant_state_uses_largest_land_overlap() -> None:
    states = read_zcta_state_overlap(FIXTURES / "zcta_county_rel_sample.txt")
    assert states == {"11111": "08", "11112": "08", "11113": "08", "11114": "20"}


def test_geonames_first_place_wins() -> None:
    places = read_geonames_places(FIXTURES / "geonames_sample.txt")
    assert places["11111"].place_name == "Littleton" and places["11111"].state_code == "CO"
    assert places["11114"].place_name == "Tribune"
    assert "11113" not in places and "99998" in places


def _write(session: Session, gdf, pairs: list[AdjacentPair] | None = None, **kwargs):
    with session.begin():
        return write_geography(
            session,
            geography=compute_geography(gdf, **kwargs),
            adjacency=pairs if pairs is not None else compute_adjacency(gdf),
            states=read_zcta_state_overlap(FIXTURES / "zcta_county_rel_sample.txt"),
            places=read_geonames_places(FIXTURES / "geonames_sample.txt"),
            boundary_meta=ImportMeta("cb_zcta520_500k", "2020", checksum="abc"),
            relationship_meta=ImportMeta("zcta520_county20_rel", "2020"),
            places_meta=ImportMeta("geonames_us_postal", "2026-09-29"),
            max_land_area_sq_miles=400.0,
        )


def test_write_geography_end_to_end(session: Session, gdf) -> None:
    first = _write(session, gdf)
    assert first.markets.inserted == 4 and first.adjacency.inserted == 4
    assert first.zctas_without_postal == 1 and first.unserviceable_land_area == 1
    second = _write(session, gdf)
    assert second.markets.updated == 4 and second.markets.inserted == 0
    assert (second.adjacency.inserted, second.adjacency.updated, second.adjacency.deleted) == (
        0,
        4,
        0,
    )
    assert session.scalar(select(func.count()).select_from(ZctaMarket)) == 4
    assert session.scalar(select(func.count()).select_from(ZctaAdjacency)) == 4
    assert session.scalar(select(func.count()).select_from(DataSourceImport)) == 6

    littleton = session.get(ZctaMarket, "11111")
    assert (littleton.state, littleton.state_fips) == ("CO", "08")
    assert (littleton.primary_city, littleton.postal_zip) == ("Littleton", "11111")
    assert littleton.unserviceable_land_area is False and littleton.geometry_geojson is None
    no_postal = session.get(ZctaMarket, "11113")
    assert no_postal.postal_zip is None and no_postal.primary_city is None
    kansas = session.get(ZctaMarket, "11114")
    assert kansas.state == "KS" and kansas.unserviceable_land_area is True
    assert session.get(DataFieldProvenance, "state").dataset == "zcta520_county20_rel"
    assert (
        session.get(DataFieldProvenance, "latitude").import_id
        == second.import_ids["cb_zcta520_500k"]
    )


def test_adjacency_is_replaced_not_accumulated(session: Session, gdf) -> None:
    _write(session, gdf)
    fewer = [p for p in compute_adjacency(gdf) if p.zcta_a != "11113"]
    result = _write(session, gdf, pairs=fewer)
    assert result.adjacency.deleted == 1 and result.adjacency.total == 3
    remaining = set(session.execute(select(ZctaAdjacency.zcta_a, ZctaAdjacency.zcta_b)).all())
    assert ("11113", "11114") not in remaining and len(remaining) == 3


def test_with_geometry_stores_geojson(session: Session, gdf) -> None:
    _write(session, gdf, with_geometry=True)
    stored = session.get(ZctaMarket, "11114").geometry_geojson
    assert stored is not None and "MultiPolygon" in stored
