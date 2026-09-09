import sqlite3

import pytest

from kestrel.transform.runner import build
from kestrel.transform.steps import s00_reference, s20_orders, s30_deliveries


@pytest.fixture
def curated(tmp_path, source_db):
    path = tmp_path / "curated.db"
    build(source_db, path, steps=[s00_reference, s20_orders, s30_deliveries])
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _delivery(conn, delivery_id):
    return conn.execute(
        "SELECT * FROM fact_delivery WHERE delivery_id = ?", (delivery_id,)
    ).fetchone()


def test_delay_is_computed_from_timestamps_not_the_source_column(curated):
    """Delivery 1's source delay_minutes says 0; actual is 30 min after planned."""
    row = _delivery(curated, 1)
    assert row["delay_minutes"] == pytest.approx(30.0)


def test_alternate_vendor_timestamp_format_parses(curated):
    """Delivery 2's actual_arrival is '16-Apr-2026 10:05 AM', not ISO."""
    row = _delivery(curated, 2)
    assert row["delay_minutes"] == pytest.approx(65.0)


def test_unparseable_actual_arrival_is_recorded_as_n3(curated):
    row = _delivery(curated, 4)
    assert row["delay_minutes"] is None

    ledger_rows = curated.execute(
        "SELECT entity_id, action, reason FROM quality_ledger WHERE rule_ref = 'N3'"
    ).fetchall()
    assert [r["entity_id"] for r in ledger_rows] == ["4"]
    assert ledger_rows[0]["action"] == "REJECTED"


def test_eaches_sums_come_from_fact_order_line(curated):
    """Order 900 (delivery 1): lines sum to 182 ordered, 170 delivered."""
    row = _delivery(curated, 1)
    assert row["ordered_qty_eaches"] == pytest.approx(182.0)
    assert row["delivered_qty_eaches"] == pytest.approx(170.0)


def test_excluded_outlet_flag_is_copied_from_dim_outlet(curated):
    """Delivery 3 belongs to outlet 4, which is soft-deleted (X1)."""
    row = _delivery(curated, 3)
    assert row["is_excluded"] == 1
    assert "X1" in row["exclusion_rules"]


def test_non_excluded_outlet_carries_no_rules(curated):
    row = _delivery(curated, 1)
    assert row["is_excluded"] == 0
    assert row["exclusion_rules"] == ""


def test_region_and_grain_fields_are_denormalised(curated):
    row = _delivery(curated, 1)
    assert row["outlet_id"] == 1
    assert row["region_id"] == 1
    assert row["route_id"] == 10
    assert row["warehouse_id"] == 1
