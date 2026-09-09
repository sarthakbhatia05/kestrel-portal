import sqlite3

import pytest
from fastapi.testclient import TestClient

from kestrel.dependencies import get_curated_db
from kestrel.main import create_app
from kestrel.transform.runner import build
from kestrel.transform.steps import (
    s00_reference,
    s20_orders,
    s30_deliveries,
    s40_returns,
    s50_inventory,
)


@pytest.fixture
def client(tmp_path, source_db):
    curated = tmp_path / "curated.db"
    build(
        source_db, curated,
        steps=[s00_reference, s20_orders, s30_deliveries, s40_returns, s50_inventory],
    )

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


def test_fill_rate_returns_a_figure_with_its_basis(client):
    response = client.get(
        "/api/service/fill-rate", params={"grain": "outlet", "period": "FY27Q1"}
    )
    assert response.status_code == 200
    body = response.json()
    assert 0 < body["headline"] < 1
    basis = body["basis"]
    assert basis["unit"] == "eaches"
    assert basis["scope"] == "National"
    assert basis["period_label"] == "FY27 Q1"
    assert basis["exclusions_applied"] == ["X1", "X2", "X3", "X4", "X5"]


def test_unit_toggles_to_cases(client):
    response = client.get(
        "/api/service/fill-rate",
        params={"grain": "outlet", "period": "FY27Q1", "unit": "cases"},
    )
    assert response.json()["basis"]["unit"] == "cases"


def test_worst_performers_are_available_without_navigation(client):
    response = client.get(
        "/api/service/fill-rate",
        params={"grain": "outlet", "period": "FY27Q1", "ascending": True, "limit": 1},
    )
    rows = response.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["key"] == "2"


def test_unknown_grain_is_rejected(client):
    response = client.get(
        "/api/service/fill-rate", params={"grain": "salesperson", "period": "FY27Q1"}
    )
    assert response.status_code == 422


def test_malformed_period_returns_a_structured_error(client):
    response = client.get(
        "/api/service/fill-rate", params={"grain": "outlet", "period": "Q1-2026"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_PERIOD"


def test_otif_returns_a_figure_with_its_basis(client):
    response = client.get(
        "/api/service/otif", params={"grain": "outlet", "period": "FY27Q1"}
    )
    assert response.status_code == 200
    body = response.json()
    basis = body["basis"]
    assert basis["metric"] == "otif"
    assert basis["scope"] == "National"
    assert basis["tolerance_minutes"] == 30  # config default, kestrel/config.py


def test_otif_tolerance_is_overridable_and_reflected_in_the_basis(client):
    response = client.get(
        "/api/service/otif",
        params={"grain": "outlet", "period": "FY27Q1", "tolerance_minutes": 5},
    )
    assert response.json()["basis"]["tolerance_minutes"] == 5


def test_otif_headline_reports_due_on_time_and_in_full_separately(client):
    response = client.get(
        "/api/service/otif", params={"grain": "outlet", "period": "FY27Q1"}
    )
    headline = response.json()["headline"]
    assert headline["due_count"] == 3
    assert headline["on_time_count"] == 1
    assert headline["in_full_count"] == 1
    assert headline["otif_count"] == 0


def test_otif_unknown_grain_is_rejected(client):
    response = client.get(
        "/api/service/otif", params={"grain": "salesperson", "period": "FY27Q1"}
    )
    assert response.status_code == 422


def test_otif_tolerance_out_of_range_is_rejected(client):
    response = client.get(
        "/api/service/otif",
        params={"grain": "outlet", "period": "FY27Q1", "tolerance_minutes": -1},
    )
    assert response.status_code == 422


def test_returns_returns_a_figure_with_its_basis(client):
    response = client.get(
        "/api/service/returns", params={"grain": "category", "period": "FY27Q1"}
    )
    assert response.status_code == 200
    body = response.json()
    basis = body["basis"]
    assert basis["metric"] == "returns"
    assert basis["scope"] == "National"
    assert 0 < body["headline"]["returns_rate"] < 1


def test_returns_basis_states_pending_and_rejected_value(client):
    response = client.get(
        "/api/service/returns", params={"grain": "category", "period": "FY27Q1"}
    )
    basis = response.json()["basis"]
    assert basis["pending_count"] == 1
    assert basis["rejected_count"] == 1


def test_returns_unknown_grain_is_rejected(client):
    response = client.get(
        "/api/service/returns", params={"grain": "outlet", "period": "FY27Q1"}
    )
    assert response.status_code == 422


def test_near_expiry_returns_a_figure_with_its_basis(client):
    response = client.get("/api/service/near-expiry", params={"grain": "category"})
    assert response.status_code == 200
    body = response.json()
    basis = body["basis"]
    assert basis["metric"] == "near_expiry"
    assert basis["scope"] == "National"
    assert basis["snapshot_date"] == "2026-06-29"  # the latest snapshot, resolved by default
    assert basis["threshold_days"] == 30  # config default, kestrel/config.py
    assert 0 < body["headline"]["near_expiry_rate"] < 1


def test_near_expiry_snapshot_date_is_overridable(client):
    response = client.get(
        "/api/service/near-expiry",
        params={"grain": "category", "snapshot_date": "2026-06-22"},
    )
    assert response.json()["basis"]["snapshot_date"] == "2026-06-22"


def test_near_expiry_threshold_days_is_overridable(client):
    response = client.get(
        "/api/service/near-expiry",
        params={"grain": "category", "threshold_days": 10},
    )
    assert response.json()["basis"]["threshold_days"] == 10


def test_near_expiry_unknown_grain_is_rejected(client):
    response = client.get(
        "/api/service/near-expiry", params={"grain": "outlet"}
    )
    assert response.status_code == 422
