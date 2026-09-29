"""ZCTA geography from public boundary files: centroids, areas, rook adjacency, state, city.

Heavy geospatial dependencies (geopandas, shapely, pyproj) are imported inside the functions
that need them so the rest of the application runs without the ``geo`` extra. Everything here
is a pure function over files or GeoDataFrames; database writes live in ``app.ingest.store``.
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    import geopandas as gpd

SQ_METRES_PER_SQ_MILE = 2_589_988.110336
EQUAL_AREA_CRS = "EPSG:5070"  # NAD83 / Conus Albers (metres): boundary lengths and centroids
WGS84 = "EPSG:4326"
DEFAULT_ZCTA_COLUMN = "ZCTA5CE20"
DEFAULT_LAND_COLUMN = "ALAND20"
DEFAULT_WATER_COLUMN = "AWATER20"

# 2020 ZCTA-to-county relationship file columns (pipe-delimited, UTF-8 with BOM).
REL_ZCTA_COLUMN = "GEOID_ZCTA5_20"
REL_COUNTY_COLUMN = "GEOID_COUNTY_20"
REL_LAND_PART_COLUMN = "AREALAND_PART"
REL_WATER_PART_COLUMN = "AREAWATER_PART"

# GeoNames postal-code export: tab-delimited, no header; column 1 = postal code,
# 2 = place name, 4 = admin code 1 (state).
GEONAMES_POSTAL_INDEX = 1
GEONAMES_PLACE_INDEX = 2
GEONAMES_STATE_INDEX = 4


@dataclass(frozen=True)
class ZctaGeography:
    zcta: str
    latitude: float
    longitude: float
    land_area_sq_miles: float
    water_area_sq_miles: float
    geometry_geojson: str | None = None


@dataclass(frozen=True, order=True)
class AdjacentPair:
    """One unordered rook-adjacent pair, stored with zcta_a < zcta_b."""

    zcta_a: str
    zcta_b: str
    shared_boundary_length_m: float


@dataclass(frozen=True)
class PostalPlace:
    postal_code: str
    place_name: str
    state_code: str | None


def ordered_pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


# ---- boundaries ------------------------------------------------------------------------------


def load_boundaries(
    path: Path | str, *, zcta_column: str = DEFAULT_ZCTA_COLUMN
) -> gpd.GeoDataFrame:
    """Read a boundary file (shapefile, GeoJSON, GeoPackage...) with one row per ZCTA."""
    import geopandas as gpd

    gdf = gpd.read_file(Path(path))
    if zcta_column not in gdf.columns:
        raise ValueError(f"{path}: expected a {zcta_column!r} column, found {list(gdf.columns)}")
    if gdf.crs is None:
        gdf = gdf.set_crs(WGS84)
    gdf[zcta_column] = gdf[zcta_column].astype(str).str.zfill(5)
    if not gdf[zcta_column].is_unique:
        duplicates = gdf[zcta_column][gdf[zcta_column].duplicated()].tolist()
        raise ValueError(f"{path}: duplicate ZCTA codes {duplicates[:5]}")
    return gdf


def compute_geography(
    gdf: gpd.GeoDataFrame,
    *,
    zcta_column: str = DEFAULT_ZCTA_COLUMN,
    land_column: str = DEFAULT_LAND_COLUMN,
    water_column: str = DEFAULT_WATER_COLUMN,
    with_geometry: bool = False,
) -> list[ZctaGeography]:
    """Centroid (WGS84) and land/water area in square miles for every ZCTA.

    The centroid is computed in an equal-area projection. When it falls outside the polygon
    (crescents, multipolygons) the representative point is used instead, so the stored point is
    always inside the ZCTA. Areas come from the file's ALAND/AWATER attributes (authoritative,
    un-generalised); the projected geometry area is the fallback when an attribute is missing.
    """
    import geopandas as gpd
    import numpy as np
    import shapely

    projected = gdf.to_crs(EQUAL_AREA_CRS)
    geoms = projected.geometry
    centroids = geoms.centroid
    inside = centroids.within(geoms).to_numpy()
    representative = geoms.representative_point()
    points = np.where(inside, centroids.to_numpy(), representative.to_numpy())
    lonlat = gpd.GeoSeries(points, crs=EQUAL_AREA_CRS).to_crs(WGS84)
    areas_m2 = geoms.area.to_numpy()
    wgs_geoms = gdf.to_crs(WGS84).geometry.to_numpy() if with_geometry else None

    codes = gdf[zcta_column].astype(str).to_numpy()
    land_attr = gdf[land_column].to_numpy() if land_column in gdf.columns else None
    water_attr = gdf[water_column].to_numpy() if water_column in gdf.columns else None

    out: list[ZctaGeography] = []
    for i, code in enumerate(codes):
        land_m2 = _attribute_or(land_attr, i, areas_m2[i])
        water_m2 = _attribute_or(water_attr, i, 0.0)
        point = lonlat.iloc[i]
        out.append(
            ZctaGeography(
                zcta=code,
                latitude=float(point.y),
                longitude=float(point.x),
                land_area_sq_miles=land_m2 / SQ_METRES_PER_SQ_MILE,
                water_area_sq_miles=water_m2 / SQ_METRES_PER_SQ_MILE,
                geometry_geojson=shapely.to_geojson(wgs_geoms[i]) if with_geometry else None,
            )
        )
    out.sort(key=lambda g: g.zcta)
    return out


def _attribute_or(values: Any, index: int, fallback: float) -> float:
    if values is None:
        return float(fallback)
    try:
        number = float(values[index])
    except (TypeError, ValueError):
        return float(fallback)
    if number != number:  # NaN
        return float(fallback)
    return number


def compute_adjacency(
    gdf: gpd.GeoDataFrame, *, zcta_column: str = DEFAULT_ZCTA_COLUMN
) -> list[AdjacentPair]:
    """Rook adjacency: pairs whose polygons intersect with a shared boundary length > 0.

    Polygons touching at a single point are not adjacent. Invalid geometries (self-touching
    rings left by generalisation) get the classic zero-width buffer fix first. Slight overlaps
    between generalised boundaries count as shared boundary (the intersection perimeter).
    """
    import numpy as np
    import shapely
    from shapely.strtree import STRtree

    projected = gdf.to_crs(EQUAL_AREA_CRS)
    geoms = np.array(projected.geometry.to_numpy(), dtype=object)
    invalid = ~shapely.is_valid(geoms)
    if invalid.any():
        geoms[invalid] = shapely.buffer(geoms[invalid], 0)

    tree = STRtree(geoms)
    left, right = tree.query(geoms, predicate="intersects")
    keep = left < right
    left, right = left[keep], right[keep]
    lengths = shapely.length(shapely.intersection(geoms[left], geoms[right]))

    codes = gdf[zcta_column].astype(str).to_numpy()
    pairs: dict[tuple[str, str], float] = {}
    for i, j, length in zip(left.tolist(), right.tolist(), lengths.tolist(), strict=True):
        if length <= 0 or codes[i] == codes[j]:
            continue
        key = ordered_pair(codes[i], codes[j])
        pairs[key] = max(pairs.get(key, 0.0), float(length))
    return sorted(AdjacentPair(a, b, length) for (a, b), length in pairs.items())


def adjacency_degrees(pairs: list[AdjacentPair]) -> dict[str, int]:
    degrees: dict[str, int] = defaultdict(int)
    for pair in pairs:
        degrees[pair.zcta_a] += 1
        degrees[pair.zcta_b] += 1
    return dict(degrees)


# ---- ZCTA -> county relationship file (dominant state) -----------------------------------------


def read_zcta_state_overlap(path: Path | str) -> dict[str, str]:
    """ZCTA -> state FIPS of the state with the largest land-area overlap.

    Ties are broken by total (land + water) overlap, then by the lower FIPS code, so the result
    is deterministic. Rows without a ZCTA (county remainders) are skipped.
    """
    land: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    total: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="|")
        for row in reader:
            zcta = (row.get(REL_ZCTA_COLUMN) or "").strip()
            county = (row.get(REL_COUNTY_COLUMN) or "").strip()
            if len(zcta) != 5 or len(county) < 2:
                continue
            state_fips = county[:2]
            land_part = _int_or_zero(row.get(REL_LAND_PART_COLUMN))
            water_part = _int_or_zero(row.get(REL_WATER_PART_COLUMN))
            land[zcta][state_fips] += land_part
            total[zcta][state_fips] += land_part + water_part
    result: dict[str, str] = {}
    for zcta, by_state in land.items():
        result[zcta] = min(by_state, key=lambda fips: (-by_state[fips], -total[zcta][fips], fips))
    return result


def _int_or_zero(value: str | None) -> int:
    if value in (None, ""):
        return 0
    try:
        return int(float(value))
    except ValueError:
        return 0


# ---- GeoNames postal codes (primary city, postal_zip) ------------------------------------------


def read_geonames_places(path: Path | str) -> dict[str, PostalPlace]:
    """Postal code -> first listed place. Accepts the GeoNames ``US.zip`` or its ``US.txt``."""
    path = Path(path)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            names = [n for n in archive.namelist() if n.lower().endswith(".txt")]
            names = [n for n in names if not n.lower().startswith("readme")] or names
            if not names:
                raise ValueError(f"{path}: no .txt member found")
            with archive.open(names[0]) as member:
                text = io.TextIOWrapper(member, encoding="utf-8", newline="")
                return _parse_geonames(text)
    with open(path, encoding="utf-8", newline="") as fh:
        return _parse_geonames(fh)


def _parse_geonames(lines: Any) -> dict[str, PostalPlace]:
    places: dict[str, PostalPlace] = {}
    reader = csv.reader(lines, delimiter="\t", quoting=csv.QUOTE_NONE)
    for row in reader:
        if len(row) <= GEONAMES_STATE_INDEX:
            continue
        postal = row[GEONAMES_POSTAL_INDEX].strip()
        place_name = row[GEONAMES_PLACE_INDEX].strip()
        if not postal or not place_name or postal in places:
            continue
        state = row[GEONAMES_STATE_INDEX].strip().upper() or None
        places[postal] = PostalPlace(postal, place_name, state)
    return places
