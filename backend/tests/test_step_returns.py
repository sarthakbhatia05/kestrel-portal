import sqlite3

import pytest

from kestrel.transform.runner import build
from kestrel.transform.steps import s00_reference, s20_orders, s40_returns


@pytest.fixture
def curated(tmp_path, source_db):
    path = tmp_path / "curated.db"
    build(source_db, path, steps=[s00_reference, s20_orders, s40_returns])
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _return(conn, return_id):
    return conn.execute(
        "SELECT * FROM fact_return WHERE return_id = ?", (return_id,)
    ).fetchone()


def test_negative_qty_is_normalised_to_positive_magnitude(curated):
    row = _return(curated, 2)
    assert row["return_qty"] == 5
    assert row["return_qty_orig_sign"] == -1


def test_positive_qty_keeps_its_sign(curated):
    row = _return(curated, 1)
    assert row["return_qty"] == 2
    assert row["return_qty_orig_sign"] == 1


def test_sign_normalisation_is_recorded_as_a_repair(curated):
    rows = curated.execute(
        "SELECT entity_id FROM quality_ledger WHERE rule_ref = 'N4'"
    ).fetchall()
    assert [r["entity_id"] for r in rows] == ["2"]


def test_category_is_denormalised_from_the_product(curated):
    assert _return(curated, 1)["category"] == "Snacks"
    assert _return(curated, 2)["category"] == "Beverages"


def test_region_is_denormalised_from_the_order(curated):
    assert _return(curated, 1)["region_id"] == 1


def test_returns_on_excluded_outlets_are_flagged(curated):
    """Outlet 4 is soft-deleted, so its return inherits the exclusion."""
    row = _return(curated, 4)
    assert row["is_excluded"] == 1
    assert "X1" in row["exclusion_rules"]


def test_status_and_reason_and_disposition_pass_through_as_captured(curated):
    row = _return(curated, 3)
    assert row["status"] == "PENDING"
    assert row["return_reason_code"] == "RT06_COLD_CHAIN_BREACH"
    assert row["disposition"] == "SCRAP"
