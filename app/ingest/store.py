"""Database writes for the import scripts: upserts into zcta_markets / zcta_adjacency plus
provenance rows. Portable across SQLite and PostgreSQL (no dialect-specific ON CONFLICT)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import case, delete, func, insert, select, tuple_, update
from sqlalchemy.orm import Session

from app.ingest.census import owner_occupancy_percent
from app.ingest.geography import AdjacentPair, PostalPlace, ZctaGeography
from app.ingest.states import usps_for_fips
from app.models import DataFieldProvenance, DataSourceImport, ZctaAdjacency, ZctaMarket
from app.models.base import utcnow

GEOGRAPHY_FIELDS = (
    "latitude",
    "longitude",
    "land_area_sq_miles",
    "water_area_sq_miles",
    "geometry_geojson",
    "bbox_min_lon",
    "bbox_min_lat",
    "bbox_max_lon",
    "bbox_max_lat",
)
STATE_FIELDS = ("state", "state_fips")
PLACE_FIELDS = ("postal_zip", "primary_city")


@dataclass(frozen=True)
class ImportMeta:
    """What to record in data_source_imports for one source."""

    dataset: str
    vintage: str
    release_label: str | None = None
    source_url: str | None = None
    checksum: str | None = None
    notes: str | None = None
    variables: dict[str, Any] | None = None


@dataclass
class UpsertCounts:
    inserted: int = 0
    updated: int = 0

    @property
    def written(self) -> int:
        return self.inserted + self.updated


@dataclass
class AdjacencyCounts:
    inserted: int = 0
    updated: int = 0
    deleted: int = 0
    total: int = 0


@dataclass
class GeographyWriteResult:
    markets: UpsertCounts
    adjacency: AdjacencyCounts
    import_ids: dict[str, int]
    zctas_without_state: int = 0
    zctas_without_postal: int = 0
    unserviceable_land_area: int = 0
    adjacency_skipped_unknown: int = 0


@dataclass
class DemographicsWriteResult:
    markets: UpsertCounts
    import_id: int
    null_counts: dict[str, int] = field(default_factory=dict)
    zctas_without_geography: int = 0


# ---- provenance -------------------------------------------------------------------------------


def record_import(session: Session, meta: ImportMeta, record_count: int) -> DataSourceImport:
    row = DataSourceImport(
        dataset=meta.dataset,
        vintage=meta.vintage,
        release_label=meta.release_label,
        source_url=meta.source_url,
        variables_json=meta.variables,
        record_count=record_count,
        checksum=meta.checksum,
        notes=meta.notes,
    )
    session.add(row)
    session.flush()
    return row


def record_field_provenance(
    session: Session,
    import_row: DataSourceImport,
    fields: dict[str, tuple[str | None, list[str] | None]],
) -> None:
    """fields: column name -> (table id or None, source variables or None)."""
    now = utcnow()
    for field_name, (table_id, variables) in fields.items():
        session.merge(
            DataFieldProvenance(
                field_name=field_name,
                dataset=import_row.dataset,
                vintage=import_row.vintage,
                table_id=table_id,
                variables_json=variables,
                import_id=import_row.id,
                updated_at=now,
            )
        )
    session.flush()


# ---- generic upsert ---------------------------------------------------------------------------


def upsert_markets(session: Session, rows: list[dict[str, Any]]) -> UpsertCounts:
    """Insert new ZCTAs and update existing ones. Every dict must carry the same keys and
    include ``zcta``; columns absent from the dicts are left untouched on update."""
    counts = UpsertCounts()
    if not rows:
        return counts
    keys = set(rows[0])
    if any(set(row) != keys for row in rows):
        raise ValueError("all upsert rows must have identical keys")
    existing = set(session.scalars(select(ZctaMarket.zcta)))
    inserts = [row for row in rows if row["zcta"] not in existing]
    updates = [row for row in rows if row["zcta"] in existing]
    if inserts:
        session.execute(insert(ZctaMarket), inserts)
        counts.inserted = len(inserts)
    if updates:
        session.execute(update(ZctaMarket), updates)
        counts.updated = len(updates)
    session.flush()
    return counts


def refresh_households_per_sq_mile(session: Session) -> None:
    """Derived column that needs both imports; recomputed after either one."""
    session.execute(
        update(ZctaMarket).values(
            households_per_sq_mile=case(
                (
                    ZctaMarket.total_households.is_not(None)
                    & ZctaMarket.land_area_sq_miles.is_not(None)
                    & (ZctaMarket.land_area_sq_miles > 0),
                    ZctaMarket.total_households / ZctaMarket.land_area_sq_miles,
                ),
                else_=None,
            )
        )
    )


# ---- geography ---------------------------------------------------------------------------------


def write_geography(
    session: Session,
    *,
    geography: list[ZctaGeography],
    adjacency: list[AdjacentPair],
    states: dict[str, str],
    places: dict[str, PostalPlace],
    boundary_meta: ImportMeta,
    relationship_meta: ImportMeta,
    places_meta: ImportMeta,
    max_land_area_sq_miles: float,
    now: datetime | None = None,
) -> GeographyWriteResult:
    """Upsert geography columns for every boundary ZCTA and replace the adjacency graph."""
    now = now or utcnow()
    boundary_import = record_import(session, boundary_meta, len(geography))
    relationship_import = record_import(session, relationship_meta, len(states))
    places_import = record_import(session, places_meta, len(places))

    rows: list[dict[str, Any]] = []
    without_state = without_postal = unserviceable = 0
    for geo in geography:
        state_fips = states.get(geo.zcta)
        state = usps_for_fips(state_fips)
        place = places.get(geo.zcta)
        without_state += int(state is None)
        without_postal += int(place is None)
        flagged = geo.land_area_sq_miles > max_land_area_sq_miles
        unserviceable += int(flagged)
        rows.append(
            {
                "zcta": geo.zcta,
                "latitude": geo.latitude,
                "longitude": geo.longitude,
                "land_area_sq_miles": geo.land_area_sq_miles,
                "water_area_sq_miles": geo.water_area_sq_miles,
                "geometry_geojson": geo.geometry_geojson,
                "bbox_min_lon": geo.bbox[0] if geo.bbox else None,
                "bbox_min_lat": geo.bbox[1] if geo.bbox else None,
                "bbox_max_lon": geo.bbox[2] if geo.bbox else None,
                "bbox_max_lat": geo.bbox[3] if geo.bbox else None,
                "state": state,
                "state_fips": state_fips,
                "postal_zip": place.postal_code if place else None,
                "primary_city": place.place_name if place else None,
                "unserviceable_land_area": flagged,
                "geography_import_id": boundary_import.id,
                "last_updated": now,
            }
        )
    market_counts = upsert_markets(session, rows)

    known = set(session.scalars(select(ZctaMarket.zcta)))
    usable = [p for p in adjacency if p.zcta_a in known and p.zcta_b in known]
    adjacency_counts = replace_adjacency(session, usable, boundary_import.id)

    record_field_provenance(
        session, boundary_import, {name: (None, None) for name in GEOGRAPHY_FIELDS}
    )
    record_field_provenance(
        session, relationship_import, {name: (None, None) for name in STATE_FIELDS}
    )
    record_field_provenance(session, places_import, {name: (None, None) for name in PLACE_FIELDS})
    refresh_households_per_sq_mile(session)
    session.flush()
    return GeographyWriteResult(
        markets=market_counts,
        adjacency=adjacency_counts,
        import_ids={
            boundary_meta.dataset: boundary_import.id,
            relationship_meta.dataset: relationship_import.id,
            places_meta.dataset: places_import.id,
        },
        zctas_without_state=without_state,
        zctas_without_postal=without_postal,
        unserviceable_land_area=unserviceable,
        adjacency_skipped_unknown=len(adjacency) - len(usable),
    )


def replace_adjacency(
    session: Session, pairs: list[AdjacentPair], import_id: int | None
) -> AdjacencyCounts:
    """Make zcta_adjacency equal to ``pairs``: insert new, update changed, delete stale."""
    counts = AdjacencyCounts()
    existing = {
        (a, b): length
        for a, b, length in session.execute(
            select(
                ZctaAdjacency.zcta_a, ZctaAdjacency.zcta_b, ZctaAdjacency.shared_boundary_length_m
            )
        )
    }
    wanted = {(p.zcta_a, p.zcta_b): p.shared_boundary_length_m for p in pairs}

    def row(a: str, b: str) -> dict[str, Any]:
        return {
            "zcta_a": a,
            "zcta_b": b,
            "shared_boundary_length_m": wanted[(a, b)],
            "geography_import_id": import_id,
        }

    to_insert = [row(a, b) for (a, b) in wanted if (a, b) not in existing]
    to_update = [row(a, b) for (a, b) in wanted if (a, b) in existing]
    stale = [key for key in existing if key not in wanted]
    for start in range(0, len(stale), 500):
        chunk = stale[start : start + 500]
        session.execute(
            delete(ZctaAdjacency).where(
                tuple_(ZctaAdjacency.zcta_a, ZctaAdjacency.zcta_b).in_(chunk)
            )
        )
    if to_insert:
        session.execute(insert(ZctaAdjacency), to_insert)
    if to_update:
        session.execute(update(ZctaAdjacency), to_update)
    session.flush()
    counts.inserted, counts.updated, counts.deleted = len(to_insert), len(to_update), len(stale)
    counts.total = len(wanted)
    return counts


# ---- demographics -----------------------------------------------------------------------------


def write_demographics(
    session: Session,
    *,
    records: dict[str, dict[str, int | None]],
    field_columns: list[str],
    field_sources: dict[str, tuple[str, list[str]]],
    meta: ImportMeta,
    source_release: str,
    now: datetime | None = None,
) -> DemographicsWriteResult:
    """Upsert demographic columns for every ZCTA in ``records``. ZCTAs missing from the
    geography import are inserted with NULL geography so nothing is silently dropped."""
    now = now or utcnow()
    import_row = record_import(session, meta, len(records))
    null_counts = dict.fromkeys(field_columns, 0)
    rows: list[dict[str, Any]] = []
    for zcta, record in records.items():
        row: dict[str, Any] = {"zcta": zcta}
        for column in field_columns:
            value = record.get(column)
            null_counts[column] += int(value is None)
            row[column] = value
        row["owner_occupancy_percent"] = owner_occupancy_percent(record)
        row["demographics_import_id"] = import_row.id
        row["source_release"] = source_release
        row["last_updated"] = now
        rows.append(row)
    counts = upsert_markets(session, rows)
    provenance = {column: field_sources[column] for column in field_columns}
    provenance["owner_occupancy_percent"] = ("B25003", ["B25003_001E", "B25003_002E"])
    record_field_provenance(session, import_row, provenance)
    refresh_households_per_sq_mile(session)
    without_geography = session.scalar(
        select(func.count())
        .select_from(ZctaMarket)
        .where(ZctaMarket.latitude.is_(None), ZctaMarket.demographics_import_id == import_row.id)
    )
    session.flush()
    return DemographicsWriteResult(
        markets=counts,
        import_id=import_row.id,
        null_counts=null_counts,
        zctas_without_geography=int(without_geography or 0),
    )
