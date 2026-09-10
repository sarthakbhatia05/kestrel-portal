"""GET /api/service/quality and /api/service/quality/ledger."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from kestrel.dependencies import get_curated_db
from kestrel.main import create_app
from kestrel.transform.runner import build
from kestrel.transform.steps import s00_reference, s20_orders, s30_deliveries, s40_returns


@pytest.fixture
def client(tmp_path, source_db):
    curated = tmp_path / "curated.db"
    build(source_db, curated, steps=[s00_reference, s20_orders, s30_deliveries, s40_returns])

    def _override():
        conn = sqlite3.connect(curated)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    app = create_app()
    app.dependency_overrides[get_curated_db] = _override
    return TestClient(app)


def test_quality_returns_scoped_measures_rules_and_build_time(client):
    response = client.get("/api/service/quality", params={"period": "FY27Q1"})
    assert response.status_code == 200
    body = response.json()
    assert body["period_label"] == "FY27 Q1"
    assert body["scope"] == "National"
    assert [m["measure"] for m in body["measures"]] == [
        "fill_rate", "otif", "returns", "near_expiry", "excursions",
    ]
    assert len(body["rules"]) == 11
    assert body["built_at"] is not None


def test_quality_applies_region_scope(client):
    body = client.get("/api/service/quality", params={"period": "FY27Q1", "region_id": 2}).json()
    assert body["scope"] == "South"
    assert body["measures"][0]["in_scope_count"] == 0


def test_quality_rejects_an_unreadable_period(client):
    response = client.get("/api/service/quality", params={"period": "last tuesday"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_PERIOD"


def test_ledger_returns_entries_for_a_rule(client):
    body = client.get("/api/service/quality/ledger", params={"rule": "X4"}).json()
    assert body["rule_ref"] == "X4"
    assert body["total"] == 1
    assert body["entries"][0]["entity_id"] == "4"


def test_ledger_bounds_the_page_size(client):
    response = client.get("/api/service/quality/ledger", params={"rule": "X4", "limit": 0})
    assert response.status_code == 422


def test_ledger_rejects_an_unknown_rule(client):
    response = client.get("/api/service/quality/ledger", params={"rule": "X9"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "UNKNOWN_RULE"
