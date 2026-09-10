"""GET /api/service/reference/scope -- what the scope selectors offer."""

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


def test_scope_returns_regions_and_periods(client):
    body = client.get("/api/service/reference/scope").json()
    assert body["regions"] == [
        {"region_id": 1, "region_name": "West"},
        {"region_id": 2, "region_name": "South"},
    ]
    assert body["periods"][0]["value"] == "latest"


def test_every_period_offered_is_a_period_the_api_accepts(client):
    """The contract that matters: nothing in the dropdown can 400."""
    for option in client.get("/api/service/reference/scope").json()["periods"]:
        response = client.get(
            "/api/service/fill-rate", params={"grain": "outlet", "period": option["value"]}
        )
        assert response.status_code == 200, f"{option['value']} was offered but rejected"
