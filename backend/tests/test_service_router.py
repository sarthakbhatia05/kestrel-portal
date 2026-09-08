import sqlite3

import pytest
from fastapi.testclient import TestClient

from kestrel.dependencies import get_curated_db
from kestrel.main import create_app
from kestrel.transform.runner import build
from kestrel.transform.steps import s00_reference, s20_orders


@pytest.fixture
def client(tmp_path, source_db):
    curated = tmp_path / "curated.db"
    build(source_db, curated, steps=[s00_reference, s20_orders])

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
