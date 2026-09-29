"""Market repository: plain ZctaRecord out, lookups by ZCTA, state, city and neighbours."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import ZctaAdjacency, ZctaMarket
from app.repositories import (
    count_markets,
    get_market,
    get_markets,
    list_markets_by_state,
    neighbour_zctas,
    search_markets_by_city,
)
from app.schemas.market import ZctaRecord


def _seed(session: Session) -> None:
    session.add_all(
        [
            ZctaMarket(zcta="80123", primary_city="Littleton", state="CO", total_households=100,
                       owner_occupied_households=80, land_area_sq_miles=10.0),
            ZctaMarket(zcta="80127", primary_city="Littleton", state="CO", total_households=90,
                       owner_occupied_households=70),
            ZctaMarket(zcta="66213", primary_city="Overland Park", state="KS"),
            ZctaMarket(zcta="80110", primary_city="Englewood", state="CO", total_households=50,
                       owner_occupied_households=60),  # inconsistent source data
        ]
    )  # fmt: skip
    session.flush()
    session.add_all(
        [
            ZctaAdjacency(zcta_a="80123", zcta_b="80127", shared_boundary_length_m=4800.0),
            ZctaAdjacency(zcta_a="80110", zcta_b="80123", shared_boundary_length_m=1200.0),
        ]
    )
    session.commit()


def test_lookups_return_plain_records(session: Session) -> None:
    _seed(session)
    record = get_market(session, "80123")
    assert isinstance(record, ZctaRecord)
    assert record.primary_city == "Littleton" and record.owner_occupancy_share == 0.8
    assert get_market(session, "00000") is None
    assert set(get_markets(session, ["80123", "66213", "99999"])) == {"80123", "66213"}
    assert [r.zcta for r in list_markets_by_state(session, "co")] == ["80110", "80123", "80127"]
    assert [r.zcta for r in search_markets_by_city(session, "litt")] == ["80123", "80127"]
    assert search_markets_by_city(session, "Littleton", state="KS") == []
    assert [r.zcta for r in search_markets_by_city(session, "over", limit=1)] == ["66213"]
    assert count_markets(session) == 4


def test_neighbours_use_both_directions(session: Session) -> None:
    _seed(session)
    assert neighbour_zctas(session, "80123") == ["80110", "80127"]
    assert neighbour_zctas(session, "80127") == ["80123"]
    assert neighbour_zctas(session, "66213") == []


def test_inconsistent_rows_still_readable(session: Session) -> None:
    _seed(session)
    record = get_market(session, "80110")
    assert record is not None and record.owner_occupied_households == 60
    assert record.owner_occupancy_share == 1.2
