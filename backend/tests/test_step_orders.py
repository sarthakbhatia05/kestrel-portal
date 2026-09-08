import sqlite3

import pytest

from kestrel.transform.runner import build
from kestrel.transform.steps import s00_reference, s20_orders


@pytest.fixture
def curated(tmp_path, source_db):
    path = tmp_path / "curated.db"
    build(source_db, path, steps=[s00_reference, s20_orders])
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _line(conn, line_id):
    return conn.execute(
        "SELECT * FROM fact_order_line WHERE order_line_id = ?", (line_id,)
    ).fetchone()


def test_case_lines_are_multiplied_by_case_pack(curated):
    row = _line(curated, 1)
    assert row["ordered_qty_eaches"] == 120  # 10 cases x 12
    assert row["delivered_qty_eaches"] == 108  # 9 cases x 12


def test_each_lines_are_left_alone(curated):
    row = _line(curated, 2)
    assert row["ordered_qty_eaches"] == 50
    assert row["delivered_qty_eaches"] == 50


def test_implausible_case_pack_falls_back_to_product_master(curated):
    row = _line(curated, 7)
    assert row["case_pack"] == 12
    assert row["ordered_qty_eaches"] == 12


def test_case_pack_fallback_is_recorded_as_a_repair(curated):
    rows = curated.execute(
        "SELECT entity_id, reason FROM quality_ledger WHERE rule_ref = 'N1'"
    ).fetchall()
    assert [r["entity_id"] for r in rows] == ["7"]


def test_cancelled_lines_are_flagged_not_removed(curated):
    row = _line(curated, 4)
    assert row is not None
    assert row["is_excluded"] == 1
    assert "X4" in row["exclusion_rules"]


def test_lines_on_excluded_outlets_are_flagged(curated):
    """Outlet 4 is soft-deleted, so its line inherits the exclusion."""
    row = _line(curated, 5)
    assert row["is_excluded"] == 1
    assert "X1" in row["exclusion_rules"]


def test_order_context_is_denormalised_onto_the_line(curated):
    row = _line(curated, 1)
    assert row["order_date"] == "2026-04-10"
    assert row["outlet_id"] == 1
    assert row["region_id"] == 1
