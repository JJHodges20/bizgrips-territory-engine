"""ACS 5-Year estimates for every ZCTA, from the Data API or the Summary File.

Both backends produce the same structure: ``{zcta: {variable_id: int | None}}`` with every
sentinel already converted to ``None``. ``build_records`` then sums bucket variables into the
stored fields of ``census_variables.yaml``. Only ``fetch_api`` and ``fetch_variable_labels``
touch the network; both take an ``httpx.Client`` so tests can inject a mock transport.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app.config.census_variables import VARIABLE_ID, CensusField

API_BATCH_SIZE = 50
API_TIMEOUT = httpx.Timeout(60.0, read=300.0)
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_VARIABLE_PARTS = re.compile(r"^([A-Z]\d{5}[A-Z]{0,2})_(\d{3})([EM])$")
_NULL_TOKENS = frozenset({"", ".", "null", "none", "n", "(x)", "-", "*", "**", "***", "*****"})


class CensusApiError(RuntimeError):
    pass


class CensusApiKeyRequired(CensusApiError):
    pass


@dataclass
class ParseStats:
    """Counts kept while cleaning raw values, reported by the import CLI."""

    values: int = 0
    sentinels: int = 0
    unexpected_negatives: int = 0
    unparseable: int = 0
    nulls: int = 0

    def as_dict(self) -> dict[str, int]:
        return dict(vars(self))


@dataclass
class AcsValues:
    """Raw per-ZCTA variable values from one backend, with what was read to get them."""

    values: dict[str, dict[str, int | None]]
    backend: str
    vintage: int
    source_urls: list[str] = field(default_factory=list)
    checksum: str | None = None
    stats: ParseStats = field(default_factory=ParseStats)


# ---- value cleaning ---------------------------------------------------------------------------


def clean_value(raw: Any, sentinels: Iterable[int], stats: ParseStats | None = None) -> int | None:
    """Convert one raw estimate to an int, or None for sentinels/blanks/negatives.

    Counts and dollar medians can never be negative, so any negative number is treated as an
    unavailable estimate even when it is not in the configured sentinel list; such values are
    counted separately so a new Census jam value gets noticed.
    """
    stats = stats if stats is not None else ParseStats()
    stats.values += 1
    if raw is None:
        stats.nulls += 1
        return None
    text = str(raw).strip()
    if text.lower() in _NULL_TOKENS:
        stats.nulls += 1
        return None
    try:
        number = float(text)
    except ValueError:
        stats.unparseable += 1
        return None
    if number != number:  # NaN
        stats.nulls += 1
        return None
    if int(number) in set(sentinels):
        stats.sentinels += 1
        return None
    if number < 0:
        stats.unexpected_negatives += 1
        return None
    return int(round(number))


# ---- Data API backend -------------------------------------------------------------------------


def parse_api_table(
    rows: list[list[Any]],
    *,
    geography: str,
    sentinels: Iterable[int],
    stats: ParseStats | None = None,
) -> dict[str, dict[str, int | None]]:
    """Turn one API response (header row + data rows) into {zcta: {variable: value}}."""
    if not rows:
        return {}
    header = [str(h) for h in rows[0]]
    if geography not in header:
        raise CensusApiError(f"API response has no {geography!r} column: {header}")
    geo_index = header.index(geography)
    variable_columns = [(i, h) for i, h in enumerate(header) if VARIABLE_ID.match(h)]
    sentinel_set = set(sentinels)
    out: dict[str, dict[str, int | None]] = {}
    for row in rows[1:]:
        zcta = str(row[geo_index]).strip().zfill(5)
        bucket = out.setdefault(zcta, {})
        for i, variable in variable_columns:
            bucket[variable] = clean_value(row[i], sentinel_set, stats)
    return out


def fetch_api(
    client: httpx.Client,
    *,
    endpoint: str,
    variables: Iterable[str],
    geography: str,
    api_key: str | None,
    sentinels: Iterable[int],
    batch_size: int = API_BATCH_SIZE,
    retries: int = 3,
    backoff_seconds: float = 2.0,
    stats: ParseStats | None = None,
) -> dict[str, dict[str, int | None]]:
    """Pull every ZCTA for the given variables in batches of at most ``batch_size``."""
    ordered = sorted(set(variables))
    merged: dict[str, dict[str, int | None]] = {}
    for start in range(0, len(ordered), batch_size):
        batch = ordered[start : start + batch_size]
        params: dict[str, str] = {"get": ",".join(batch), "for": f"{geography}:*"}
        if api_key:
            params["key"] = api_key
        rows = _get_json_with_retries(client, endpoint, params, retries, backoff_seconds)
        parsed = parse_api_table(rows, geography=geography, sentinels=sentinels, stats=stats)
        for zcta, values in parsed.items():
            merged.setdefault(zcta, {}).update(values)
    return merged


def _get_json_with_retries(
    client: httpx.Client, url: str, params: dict[str, str], retries: int, backoff: float
) -> Any:
    attempt = 0
    while True:
        attempt += 1
        try:
            response = client.get(url, params=params)
        except httpx.TransportError as exc:
            if attempt > retries:
                raise CensusApiError(f"{url}: {exc}") from exc
            time.sleep(backoff * attempt)
            continue
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("location", "")
            if "missing_key" in location or response.headers.get("x-datawebapi-keyerror"):
                raise CensusApiKeyRequired(
                    "the Census Data API requires a (free) API key for data queries; set "
                    "CENSUS_API_KEY or use --source summary-file"
                )
            raise CensusApiError(f"{url}: unexpected redirect to {location!r}")
        if response.status_code in RETRY_STATUSES and attempt <= retries:
            time.sleep(backoff * attempt)
            continue
        if response.status_code != 200:
            raise CensusApiError(f"{url}: HTTP {response.status_code}: {response.text[:200]}")
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise CensusApiError(f"{url}: response is not JSON: {response.text[:200]}") from exc


# ---- Summary File backend ---------------------------------------------------------------------


def summary_column(variable: str) -> str:
    """API variable id -> summary-file column name (``B25007_006E`` -> ``B25007_E006``)."""
    match = _VARIABLE_PARTS.match(variable)
    if not match:
        raise ValueError(f"not an ACS variable id: {variable!r}")
    table, number, kind = match.groups()
    return f"{table}_{kind}{number}"


def read_summary_file(
    path: Path | str,
    *,
    variables: Iterable[str],
    zcta_geo_id_prefix: str,
    sentinels: Iterable[int],
    stats: ParseStats | None = None,
) -> dict[str, dict[str, int | None]]:
    """Read the ZCTA rows of one table-based summary file for the requested variables."""
    wanted = {summary_column(v): v for v in variables}
    sentinel_set = set(sentinels)
    out: dict[str, dict[str, int | None]] = {}
    with open(path, encoding="utf-8-sig", newline="") as fh:
        header = fh.readline().rstrip("\r\n").split("|")
        positions = {name: i for i, name in enumerate(header)}
        missing = sorted(set(wanted) - set(positions))
        if missing:
            raise ValueError(f"{path}: columns {missing} not found in header")
        columns = [(positions[name], variable) for name, variable in wanted.items()]
        prefix_len = len(zcta_geo_id_prefix)
        for line in fh:
            if not line.startswith(zcta_geo_id_prefix):
                continue
            parts = line.rstrip("\r\n").split("|")
            zcta = parts[0][prefix_len:].strip().zfill(5)
            bucket = out.setdefault(zcta, {})
            for index, variable in columns:
                raw = parts[index] if index < len(parts) else None
                bucket[variable] = clean_value(raw, sentinel_set, stats)
    return out


def merge_values(
    parts: Iterable[dict[str, dict[str, int | None]]],
) -> dict[str, dict[str, int | None]]:
    merged: dict[str, dict[str, int | None]] = {}
    for part in parts:
        for zcta, values in part.items():
            merged.setdefault(zcta, {}).update(values)
    return merged


# ---- variable label validation ----------------------------------------------------------------


def fetch_variable_labels(
    client: httpx.Client,
    *,
    endpoint: str,
    variables: Iterable[str],
    retries: int = 3,
    backoff_seconds: float = 2.0,
) -> dict[str, str]:
    """Labels from ``{endpoint}/variables/{id}.json`` (served without an API key)."""
    labels: dict[str, str] = {}
    for variable in sorted(set(variables)):
        payload = _get_json_with_retries(
            client, f"{endpoint}/variables/{variable}.json", {}, retries, backoff_seconds
        )
        label = payload.get("label") if isinstance(payload, Mapping) else None
        if not isinstance(label, str):
            raise CensusApiError(f"no label returned for {variable}: {payload!r}")
        labels[variable] = label
    return labels


def check_labels(labels: Mapping[str, str], expected: Mapping[str, str]) -> list[str]:
    """Return one problem per variable whose label lacks its expected fragment."""
    problems: list[str] = []
    for variable, fragment in sorted(expected.items()):
        label = labels.get(variable)
        if label is None:
            problems.append(f"{variable}: no label available")
        elif fragment.lower() not in label.lower():
            problems.append(f"{variable}: label {label!r} does not contain {fragment!r}")
    return problems


# ---- field assembly ---------------------------------------------------------------------------


def build_field_values(
    values: Mapping[str, int | None], fields: Mapping[str, CensusField]
) -> dict[str, int | None]:
    """Sum each field's variables; a field is None when any of its variables is missing."""
    out: dict[str, int | None] = {}
    for name, spec in fields.items():
        components = [values.get(variable) for variable in spec.variables]
        if any(component is None for component in components):
            out[name] = None
        else:
            out[name] = sum(component for component in components if component is not None)
    return out


def build_records(
    values_by_zcta: Mapping[str, Mapping[str, int | None]], fields: Mapping[str, CensusField]
) -> dict[str, dict[str, int | None]]:
    return {
        zcta: build_field_values(values, fields) for zcta, values in sorted(values_by_zcta.items())
    }


def owner_occupancy_percent(record: Mapping[str, int | None]) -> float | None:
    owner = record.get("owner_occupied_households")
    total = record.get("total_households")
    if owner is None or total is None or total <= 0:
        return None
    return round(owner / total * 100, 2)
