"""Typed access to app/config/census_variables.yaml (the ACS variable map and geography sources)."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

VARIABLE_ID = re.compile(r"^[A-Z]\d{5}[A-Z]{0,2}_\d{3}[EM]$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CensusField(StrictModel):
    table: str = Field(pattern=r"^[A-Z]\d{5}[A-Z]{0,2}$")
    variables: tuple[str, ...] = Field(min_length=1)
    label_contains: str | None = None

    @field_validator("variables")
    @classmethod
    def _valid_ids(cls, variables: tuple[str, ...]) -> tuple[str, ...]:
        bad = [v for v in variables if not VARIABLE_ID.match(v)]
        if bad:
            raise ValueError(f"invalid ACS variable ids: {bad}")
        return variables

    @model_validator(mode="after")
    def _same_table(self) -> CensusField:
        wrong = [v for v in self.variables if not v.startswith(self.table + "_")]
        if wrong:
            raise ValueError(f"variables {wrong} do not belong to table {self.table}")
        return self


class GeographySource(StrictModel):
    name: str
    dataset: str = Field(pattern=r"^[a-z0-9_]+$")
    url: str = Field(pattern=r"^https://")
    vintage: str | None = None  # None: a rolling export; the import records the download date
    filename: str | None = None  # local name under data/raw; defaults to the URL basename
    fields: dict[str, str] | None = None
    notes: str | None = None

    @property
    def local_filename(self) -> str:
        return self.filename or self.url.rsplit("/", 1)[-1]


class SummaryFileSource(StrictModel):
    """ACS Summary File table-based files: the key-less alternative to the Data API."""

    url_template: str = Field(pattern=r"^https://.*\{vintage\}.*\{table_lower\}")
    zcta_geo_id_prefix: str = Field(min_length=1)
    min_vintage: int = Field(ge=2009)

    def url(self, vintage: int, table: str) -> str:
        return self.url_template.format(vintage=vintage, table_lower=table.lower())


class CensusVariables(StrictModel):
    dataset: str
    vintage: int = Field(ge=2009)
    release_label: str
    api_base: str = Field(pattern=r"^https://")
    geography: str
    summary_file: SummaryFileSource
    sentinels: tuple[int, ...] = Field(min_length=1)
    fields: dict[str, CensusField]
    geography_sources: dict[str, GeographySource]

    @property
    def all_variables(self) -> tuple[str, ...]:
        seen: set[str] = set()
        for field in self.fields.values():
            seen.update(field.variables)
        return tuple(sorted(seen))

    @property
    def tables(self) -> tuple[str, ...]:
        return tuple(sorted({field.table for field in self.fields.values()}))

    def endpoint(self, vintage: int | None = None) -> str:
        return f"{self.api_base}/{vintage or self.vintage}/{self.dataset}"

    def label_checks(self) -> dict[str, str]:
        """Variable id -> required label fragment (checked on the first variable of each field)."""
        return {
            field.variables[0]: field.label_contains
            for field in self.fields.values()
            if field.label_contains
        }


def load_census_variables(path: Path | str | None = None) -> CensusVariables:
    import yaml

    from app.config.settings import get_settings

    variables_path = Path(path) if path is not None else get_settings().census_variables_path
    with open(variables_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return CensusVariables.model_validate(data)


@lru_cache
def get_census_variables() -> CensusVariables:
    return load_census_variables()
