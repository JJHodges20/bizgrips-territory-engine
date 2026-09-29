"""Regenerate the synthetic ACS fixtures (API response JSON + summary-file .dat files).

    venv/Scripts/python.exe tests/fixtures/generate_acs_fixtures.py

Values are invented but internally consistent (owner <= total households, bucket sums add up)
except where a case is deliberately broken to exercise sentinel and missing-value handling:
  11112  median income is the -666666666 sentinel
  11113  B25007_007E (owner 55-59) is missing -> 45+ and 55+ sums are NULL, 65+ is not
  11115  present in ACS but absent from the boundary fixture
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SENTINEL = -666666666
ZCTAS = ["11111", "11112", "11113", "11114", "11115"]
POP = {"11111": 41000, "11112": 28000, "11113": 9000, "11114": 1200, "11115": 3000}
# total households, owner, renter
HH = {
    "11111": (16500, 13400, 3100),
    "11112": (11000, 6000, 5000),
    "11113": (3500, 3000, 500),
    "11114": (500, 400, 100),
    "11115": (1200, 900, 300),
}
# B25007 owner buckets 003..011: 15-24, 25-34, 35-44, 45-54, 55-59, 60-64, 65-74, 75-84, 85+
OWNER_AGE = {
    "11111": [200, 1500, 2100, 3200, 1500, 1400, 2400, 900, 200],
    "11112": [100, 900, 900, 1500, 700, 600, 900, 300, 100],
    "11113": [50, 300, 600, 800, None, 400, 600, 200, 50],
    "11114": [5, 40, 65, 90, 40, 40, 80, 30, 10],
    "11115": [10, 100, 160, 200, 100, 100, 150, 60, 20],
}
# B25034 buckets 002..011: 2020+, 2010-19, 2000-09, 1990-99, 1980-89, 1970-79, 60s, 50s, 40s, <1940
BUILT = {
    "11111": [300, 1600, 2000, 4000, 3500, 3000, 1500, 800, 200, 100],
    "11112": [250, 2300, 3000, 2000, 1500, 1200, 900, 500, 100, 50],
    "11113": [30, 300, 500, 900, 800, 700, 300, 100, 50, 20],
    "11114": [10, 60, 70, 100, 90, 120, 60, 40, 20, 30],
    "11115": [20, 150, 200, 300, 250, 200, 100, 50, 20, 10],
}
INCOME = {"11111": 98500, "11112": SENTINEL, "11113": 72000, "11114": 58000, "11115": 61000}
VALUE = {"11111": 520000, "11112": 410000, "11113": 350000, "11114": 180000, "11115": 240000}
API_VARIABLES = [
    "B01003_001E", "B25003_001E", "B25003_002E", "B25003_003E",
    "B25007_006E", "B25007_007E", "B25007_008E", "B25007_009E", "B25007_010E", "B25007_011E",
    "B25034_001E", "B25034_005E", "B25034_006E", "B25034_007E", "B25034_008E", "B25034_009E",
    "B25034_010E", "B25034_011E", "B19013_001E", "B25077_001E",
]  # fmt: skip


def table_values() -> dict[str, dict[str, list[int | None]]]:
    """table -> zcta -> estimate columns 001..N (None = missing)."""
    tables = ("B01003", "B25003", "B25007", "B25034", "B19013", "B25077")
    out: dict[str, dict[str, list[int | None]]] = {t: {} for t in tables}
    for z in ZCTAS:
        total, owner, renter = HH[z]
        renter_buckets = [renter // 9] * 9
        renter_buckets[0] += renter - sum(renter_buckets)
        out["B01003"][z] = [POP[z]]
        out["B25003"][z] = [total, owner, renter]
        out["B25007"][z] = [total, owner, *OWNER_AGE[z], renter, *renter_buckets]
        out["B25034"][z] = [total + 500, *BUILT[z]]
        out["B19013"][z] = [INCOME[z]]
        out["B25077"][z] = [VALUE[z]]
    return out


def write_api_response(values: dict[str, dict[str, list[int | None]]]) -> None:
    rows: list[list[str | None]] = [[*API_VARIABLES, "zip code tabulation area"]]
    for z in ZCTAS:
        row: list[str | None] = []
        for var in API_VARIABLES:
            v = values[var[:6]][z][int(var[7:10]) - 1]
            row.append(None if v is None else str(v))
        rows.append([*row, z])
    path = HERE / "acs_api_response.json"
    path.write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")


def write_summary_files(values: dict[str, dict[str, list[int | None]]]) -> None:
    folder = HERE / "acs_summary"
    folder.mkdir(exist_ok=True)
    for table, by_zcta in values.items():
        width = len(next(iter(by_zcta.values())))
        header = ["GEO_ID"]
        for n in range(1, width + 1):
            header += [f"{table}_E{n:03d}", f"{table}_M{n:03d}"]
        filler = ["1000"] * (2 * width)
        lines = ["|".join(header)]
        lines.append("|".join(["0400000US08", *filler]))  # state row: must be skipped
        lines.append("|".join(["0500000US08059", *filler]))  # county row: must be skipped
        for z in ZCTAS:
            cells = [f"860Z200US{z}"]
            for v in by_zcta[z]:
                if v is None:
                    cells += ["", ""]
                elif v == SENTINEL:
                    cells += [str(v), "*****"]
                else:
                    cells += [str(v), str(max(v // 10, 1))]
            lines.append("|".join(cells))
        name = f"acsdt5y2023-{table.lower()}.dat"
        (folder / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    data = table_values()
    write_api_response(data)
    write_summary_files(data)
    print("fixtures written under", HERE)
