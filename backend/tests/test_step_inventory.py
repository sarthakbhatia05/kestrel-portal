import sqlite3

import pytest

from kestrel.transform.runner import build
from kestrel.transform.steps import s00_reference, s50_inventory


@pytest.fixture
def curated(tmp_path, source_db):
    path = tmp_path / "curated.db"
    build(source_db, path, steps=[s00_reference, s50_inventory])
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _snapshot(conn, snapshot_id):
    return conn.execute(
        "SELECT * FROM fact_inventory_snapshot WHERE snapshot_id = ?", (snapshot_id,)
    ).fetchone()


def test_available_cases_excludes_allocated_damaged_and_blocked(curated):
    row = _snapshot(curated, 1)
    assert row["available_cases"] == 83  # 100 - 10 - 5 - 2


def test_remaining_shelf_life_is_computed_from_expiry_minus_snapshot_date(curated):
    assert _snapshot(curated, 1)["remaining_shelf_life_days"] == 11
    assert _snapshot(curated, 2)["remaining_shelf_life_days"] == 155
    assert _snapshot(curated, 3)["remaining_shelf_life_days"] == 6


def test_region_is_denormalised_from_the_warehouse(curated):
    assert _snapshot(curated, 1)["region_id"] == 1  # WH1 -> West
    assert _snapshot(curated, 3)["region_id"] == 2  # WH2 -> South


def test_category_is_denormalised_from_the_product(curated):
    assert _snapshot(curated, 1)["category"] == "Snacks"
    assert _snapshot(curated, 2)["category"] == "Beverages"


def test_no_exclusion_rule_applies_to_inventory(curated):
    """s00_reference's outlet processing writes its own ledger rows (X1,
    X2, X5, N5) regardless of this step; what matters here is that
    s50_inventory itself contributes none."""
    assert _snapshot(curated, 1)["is_excluded"] == 0
    rows = curated.execute(
        "SELECT count(*) FROM quality_ledger WHERE entity_type = 'inventory_snapshot'"
    ).fetchone()[0]
    assert rows == 0


def test_all_snapshot_dates_are_loaded(curated):
    dates = {
        row["snapshot_date"]
        for row in curated.execute("SELECT DISTINCT snapshot_date FROM fact_inventory_snapshot")
    }
    assert dates == {"2026-06-29", "2026-06-22"}
