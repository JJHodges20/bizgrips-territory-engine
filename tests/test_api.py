"""The FastAPI app boots and exposes health and configuration."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_reports_rules_version_and_database() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["business_rules_version"] == "1.0.0"
    assert body["database"] == {"dialect": "sqlite", "status": "ok", "detail": None}


def test_business_rules_endpoint_exposes_weights_and_bands() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/config/business-rules")
    assert response.status_code == 200
    body = response.json()
    assert body["scoring"]["weights"]["owner_concentration"] == 0.35
    assert body["territory_sizes"]["bands"]["standard"] == {
        "target_min": 20000,
        "target_max": 32000,
    }
    assert body["registry"]["blocking_statuses"] == [
        "RESERVED",
        "ACTIVE_PROTECTED",
        "PENDING_RELEASE",
    ]


def test_census_variables_endpoint() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/config/census-variables")
    assert response.status_code == 200
    body = response.json()
    assert body["endpoint"] == "https://api.census.gov/data/2023/acs/acs5"
    assert "B25007_006E" in body["all_variables"]
