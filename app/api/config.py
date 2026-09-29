"""Read-only views of the version-controlled configuration."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.config import get_business_rules
from app.config.census_variables import get_census_variables

router = APIRouter(prefix="/config", tags=["config"])


@router.get("/business-rules")
def business_rules() -> dict[str, Any]:
    """The active BizGrips Territory Standard values (all V1 hypotheses)."""
    return get_business_rules().model_dump(mode="json")


@router.get("/census-variables")
def census_variables() -> dict[str, Any]:
    """The ACS variable map and geography sources used by the import scripts."""
    variables = get_census_variables()
    payload = variables.model_dump(mode="json")
    payload["endpoint"] = variables.endpoint()
    payload["all_variables"] = list(variables.all_variables)
    return payload
