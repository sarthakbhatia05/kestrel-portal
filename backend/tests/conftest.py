import sqlite3

import pytest

SOURCE_DDL = """
CREATE TABLE regions (
    region_id INTEGER, region_code TEXT, region_name TEXT
);
CREATE TABLE outlets (
    outlet_id INTEGER, outlet_code TEXT, outlet_name TEXT, channel TEXT,
    city TEXT, region_id INTEGER, route_id INTEGER, salesperson_id INTEGER,
    gst_number TEXT, status TEXT, closed_date TEXT, is_deleted INTEGER
);
CREATE TABLE products (
    product_id INTEGER, sku_code TEXT, case_pack INTEGER, category TEXT,
    list_price_inr REAL
);
CREATE TABLE warehouses (
    warehouse_id INTEGER, warehouse_code TEXT, warehouse_name TEXT,
    region_id INTEGER, status TEXT
);
CREATE TABLE inventory_snapshots (
    snapshot_id INTEGER, snapshot_date TEXT, warehouse_id INTEGER,
    product_id INTEGER, batch_id TEXT, on_hand_cases REAL,
    allocated_cases REAL, damaged_cases REAL, blocked_cases REAL,
    days_of_cover REAL, expiry_date TEXT, ageing_bucket TEXT,
    storage_temp_celsius REAL
);
CREATE TABLE orders (
    order_id INTEGER, outlet_id INTEGER, order_date TEXT, region_id INTEGER,
    route_id INTEGER, warehouse_id INTEGER, order_status TEXT, source_system TEXT
);
CREATE TABLE order_lines (
    order_line_id INTEGER, order_id INTEGER, product_id INTEGER,
    ordered_qty REAL, qty_uom TEXT, case_pack_at_order INTEGER,
    delivered_qty REAL, unit_price_inr REAL, line_discount_pct REAL,
    short_reason_code TEXT
);
CREATE TABLE deliveries (
    delivery_id INTEGER, order_id INTEGER, planned_arrival TEXT,
    actual_arrival TEXT, delay_minutes INTEGER, route_id INTEGER,
    warehouse_id INTEGER
);
CREATE TABLE returns_credit_notes (
    return_id INTEGER, credit_note_number TEXT, order_id INTEGER,
    order_line_id INTEGER, outlet_id INTEGER, product_id INTEGER,
    return_date TEXT, return_qty REAL, qty_uom TEXT,
    return_reason_code TEXT, credit_note_value_inr REAL,
    disposition TEXT, status TEXT
);
"""


@pytest.fixture
def source_db(tmp_path):
    """A miniature source database mirroring the real column names.

    Deliberately hand-built rather than sampled, so tests never depend on
    the real database being present.
    """
    path = tmp_path / "source.db"
    conn = sqlite3.connect(path)
    conn.executescript(SOURCE_DDL)

    conn.executemany(
        "INSERT INTO regions VALUES (?, ?, ?)",
        [(1, "W", "West"), (2, "S", "South")],
    )
    conn.executemany(
        "INSERT INTO outlets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            # id, code, name, channel, city, region, route, sp, gst, status, closed, deleted
            (1, "OUT1", "Good Mart", "GT", "Bengaluru", 1, 10, 5, "GST1", "ACTIVE", None, 0),
            (2, "OUT2", "Fine Store", "MT", "Bangalore", 1, 10, 5, "GST2", "ACTIVE", None, 0),
            (3, "OUT3", "Old Shop", "GT", "Mumbai", 1, 11, 6, "GST3", "CLOSED", "2025-06-30", 0),
            (4, "OUT4", "Gone Ltd", "GT", "Mumbai", 1, 11, 6, "GST4", "DELETED", None, 1),
            (5, "TST1", "Test Outlet", "GT", "Mumbai", 1, 11, 6, "GST5", "ACTIVE", None, 0),
            # Shares GST2 with outlet 2: the survivor is the lowest outlet_id.
            (6, "OUT6", "Fine Store 2", "MT", "New Delhi", 2, 12, 7, "GST2", "ACTIVE", None, 0),
        ],
    )
    conn.executemany(
        "INSERT INTO products VALUES (?, ?, ?, ?, ?)",
        [
            (100, "SKU100", 12, "Snacks", 100),
            (200, "SKU200", 6, "Beverages", 20),
        ],
    )
    conn.executemany(
        "INSERT INTO warehouses VALUES (?, ?, ?, ?, ?)",
        [
            (1, "WH1", "West Hub", 1, "ACTIVE"),
            (2, "WH2", "South Hub", 2, "ACTIVE"),
        ],
    )
    conn.executemany(
        "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (900, 1, "2026-04-10", 1, 10, 1, "DELIVERED", "ERP_WEB"),
            (901, 2, "2026-04-11", 1, 10, 1, "PARTIAL", "SFA_MOBILE"),
            (902, 3, "2026-04-12", 1, 11, 1, "CANCELLED", "ERP_WEB"),
            (903, 4, "2026-05-01", 1, 11, 1, "DELIVERED", "PARTNER_API"),
            (904, 1, "2026-01-05", 1, 10, 1, "DELIVERED", "ERP_WEB"),
        ],
    )
    conn.executemany(
        "INSERT INTO order_lines VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            # 10 cases of 12 = 120 eaches ordered, 9 cases = 108 delivered
            # dispatched_value_inr = 9 * 100 * (1-0) = 900
            (1, 900, 100, 10, "CASE", 12, 9, 100, 0, "STOCKOUT"),
            # 50 eaches ordered, 50 delivered. dispatched_value_inr = 50*10 = 500
            (2, 900, 200, 50, "EACH", 6, 50, 10, 0, None),
            # 20 cases of 6 = 120 ordered, 60 delivered. dispatched = 10*50 = 500
            (3, 901, 200, 20, "CASE", 6, 10, 50, 0, "DAMAGE"),
            # cancelled order: must not reach the numerator or denominator
            (4, 902, 100, 100, "CASE", 12, 0, 100, 0, None),
            # deleted outlet. dispatched = 5*100 = 500
            (5, 903, 100, 5, "CASE", 12, 5, 100, 0, None),
            # out of period. dispatched = 5*100 = 500
            (6, 904, 100, 5, "CASE", 12, 5, 100, 0, None),
            # implausible case pack: falls back to the product master's 12
            # dispatched = 1*100 = 100
            (7, 900, 100, 1, "CASE", 0, 1, 100, 0, None),
        ],
    )
    conn.executemany(
        "INSERT INTO deliveries VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            # order 900 (outlet 1): 30 min late, exactly on the default
            # tolerance boundary. Source delay_minutes says 0 -- wrong on
            # purpose, to prove the transform recomputes rather than trusts it.
            (1, 900, "2026-04-15 10:00:00", "2026-04-15 10:30:00", 0, 10, 1),
            # order 901 (outlet 2): 65 min late, in the alternate vendor
            # timestamp format (12-hour, DD-Mon-YYYY).
            (2, 901, "2026-04-16 09:00:00", "16-Apr-2026 10:05 AM", 5, 10, 1),
            # order 903 (outlet 4, soft-deleted / X1): on time. Only visible
            # with include_excluded=True.
            (3, 903, "2026-04-17 09:00:00", "2026-04-17 09:00:00", 999, 11, 1),
            # order 904 (outlet 1): unparseable actual_arrival -> N3, and
            # counted as unmeasured rather than dropped.
            (4, 904, "2026-05-01 12:00:00", "not-a-real-timestamp", None, 10, 1),
        ],
    )
    conn.executemany(
        "INSERT INTO returns_credit_notes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            # outlet 1 (Snacks/product 100), approved, in period.
            (1, "CN001", 900, 1, 1, 100, "2026-04-20", 2, "CASE",
             "RT05_OVERSUPPLY", 200, "RESTOCK", "APPROVED"),
            # outlet 1 (Beverages/product 200), approved, cold-chain
            # (RT01_NEAR_EXPIRY), negative qty -> N4 sign normalisation.
            (2, "CN002", 900, 2, 1, 200, "2026-04-21", -5, "EACH",
             "RT01_NEAR_EXPIRY", 50, "SCRAP", "APPROVED"),
            # outlet 2 (Beverages/product 200), cold-chain but PENDING ->
            # excluded from the rate, counted in the basis's pending value.
            (3, "CN003", 901, 3, 2, 200, "2026-04-22", 1, "CASE",
             "RT06_COLD_CHAIN_BREACH", 75, "SCRAP", "PENDING"),
            # outlet 4 is soft-deleted (X1): excluded by default.
            (4, "CN004", 903, 5, 4, 100, "2026-04-23", 1, "CASE",
             "RT02_DAMAGE_TRANSIT", 100, "SCRAP", "APPROVED"),
            # REJECTED -> never resulted in a credit, excluded from the rate.
            (5, "CN005", 900, 1, 1, 100, "2026-04-24", 1, "CASE",
             "RT03_WRONG_SKU", 100, "VENDOR_RECOVERY", "REJECTED"),
        ],
    )
    conn.executemany(
        "INSERT INTO inventory_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            # WH1/West/Snacks: expiry 11 days out from the snapshot -> near-expiry.
            # available = 100 - 10 - 5 - 2 = 83
            (1, "2026-06-29", 1, 100, "B1", 100, 10, 5, 2, 20, "2026-07-10", "0-30", 25),
            # WH1/West/Beverages: expiry 155 days out -> not near-expiry.
            # available = 200 - 20 - 0 - 0 = 180
            (2, "2026-06-29", 1, 200, "B2", 200, 20, 0, 0, 50, "2026-12-01", "90+", 25),
            # WH2/South/Snacks: expiry 6 days out -> near-expiry.
            # available = 50 - 5 - 1 - 0 = 44
            (3, "2026-06-29", 2, 100, "B3", 50, 5, 1, 0, 10, "2026-07-05", "0-30", 4),
            # Prior week's snapshot: only visible when snapshot_date is
            # given explicitly, never picked up by "latest".
            # available = 90 - 5 - 0 - 0 = 85, expiry 11 days out -> near-expiry.
            (4, "2026-06-22", 1, 100, "B4", 90, 5, 0, 0, 18, "2026-07-03", "0-30", 25),
        ],
    )
    conn.commit()
    conn.close()
    return path
