"""The ACS variable map must be complete and internally consistent."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import load_census_variables
from app.config.census_variables import VARIABLE_ID, CensusField

REQUIRED_FIELDS = {
    "total_population",
    "total_households",
    "owner_occupied_households",
    "renter_occupied_households",
    "owner_households_age_45_plus",
    "owner_households_age_55_plus",
    "owner_households_age_65_plus",
    "total_housing_units",
    "homes_built_before_2000",
    "homes_built_before_1990",
    "homes_built_before_1980",
    "median_household_income",
    "median_home_value",
}


def test_all_data_dictionary_fields_are_mapped() -> None:
    variables = load_census_variables()
    assert REQUIRED_FIELDS <= set(variables.fields)
    assert variables.vintage == 2023
    assert variables.endpoint() == "https://api.census.gov/data/2023/acs/acs5"


def test_variable_ids_are_well_formed_and_belong_to_their_table() -> None:
    variables = load_census_variables()
    for name, field in variables.fields.items():
        for var in field.variables:
            assert VARIABLE_ID.match(var), (name, var)
            assert var.startswith(field.table + "_"), (name, var)


def test_bucket_sums_match_the_data_dictionary() -> None:
    fields = load_census_variables().fields
    assert fields["owner_households_age_45_plus"].variables == (
        "B25007_006E",
        "B25007_007E",
        "B25007_008E",
        "B25007_009E",
        "B25007_010E",
        "B25007_011E",
    )
    assert fields["owner_households_age_65_plus"].variables == (
        "B25007_009E",
        "B25007_010E",
        "B25007_011E",
    )
    assert len(fields["homes_built_before_2000"].variables) == 7
    assert fields["homes_built_before_2000"].variables[0] == "B25034_005E"
    assert fields["homes_built_before_1980"].variables[0] == "B25034_007E"
    # 55+ and 65+ are strict subsets of 45+; pre-1990 and pre-1980 of pre-2000.
    assert set(fields["owner_households_age_55_plus"].variables) < set(
        fields["owner_households_age_45_plus"].variables
    )
    assert set(fields["homes_built_before_1980"].variables) < set(
        fields["homes_built_before_1990"].variables
    )
    assert set(fields["homes_built_before_1990"].variables) < set(
        fields["homes_built_before_2000"].variables
    )


def test_sentinels_and_geography_sources_present() -> None:
    variables = load_census_variables()
    assert -666666666 in variables.sentinels
    assert {"zcta_boundaries", "zcta_to_county", "postal_places"} <= set(
        variables.geography_sources
    )
    for source in variables.geography_sources.values():
        assert source.url.startswith("https://")
    assert "B25007" in variables.tables
    assert len(variables.all_variables) == len(set(variables.all_variables))


def test_mismatched_table_is_rejected() -> None:
    with pytest.raises(ValidationError, match="do not belong"):
        CensusField(table="B25003", variables=("B25007_001E",))
    with pytest.raises(ValidationError, match="invalid ACS variable"):
        CensusField(table="B25003", variables=("B25003-001E",))
