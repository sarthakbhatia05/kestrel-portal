import sqlite3

import pytest

from kestrel.ask import catalogue
from kestrel.transform.runner import build
from kestrel.transform.steps import (
    s00_reference,
    s20_orders,
    s30_deliveries,
    s40_returns,
    s50_inventory,
)


@pytest.fixture
def curated(tmp_path, source_db):
    path = tmp_path / "curated.db"
    build(
        source_db, path,
        steps=[s00_reference, s20_orders, s30_deliveries, s40_returns, s50_inventory],
    )
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def test_regions_carry_the_ids_the_metric_layer_accepts(curated):
    entries = catalogue.build(curated).regions
    assert {(e.region_id, e.region_name) for e in entries} == {(1, "West"), (2, "South")}


def test_warehouses_and_categories_are_enumerated(curated):
    result = catalogue.build(curated)
    assert result.warehouses == ["South Hub", "West Hub"]
    assert result.categories == ["Beverages", "Snacks"]


def test_return_reasons_come_from_the_data(curated):
    reasons = catalogue.build(curated).return_reasons
    assert "RT05_OVERSUPPLY" in reasons
    assert all(r.startswith("RT") for r in reasons)
