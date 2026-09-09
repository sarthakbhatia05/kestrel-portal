"""Inventory snapshots and near-expiry stock. PRD 5.5.

remaining_shelf_life_days is computed once here from (expiry_date -
snapshot_date), since both are fixed per row -- the near-expiry threshold
itself stays a query-time parameter (PRD 5.5: "the threshold is
configurable"), so this column is filtered against, never compared to a
hard-coded cutoff.

available_cases here is on_hand_cases minus allocated, damaged AND blocked.
The source's own available_cases column only subtracts allocated -- PRD 5.5
requires damaged and blocked quantities to be excluded from available stock
too, so this column is recomputed rather than copied.

Prices are the current product master (dim_product.list_price_inr), not
resolved as-at any order date (N6): stock sitting in a warehouse has no
order event to resolve a price history window against, so N6 does not apply
here.

No PRD 6.3 exclusion rule is scoped to warehouses or inventory, so this step
records nothing to the quality ledger and every row is included.
"""

import sqlite3
from datetime import date

from kestrel.transform.ledger import QualityLedger

name = "s50_inventory"

SELECT_SNAPSHOTS = """
SELECT s.snapshot_id, s.snapshot_date, s.warehouse_id, s.product_id, s.batch_id,
       s.on_hand_cases, s.allocated_cases, s.damaged_cases, s.blocked_cases,
       s.days_of_cover, s.expiry_date, s.ageing_bucket, s.storage_temp_celsius,
       w.region_id
FROM inventory_snapshots s
JOIN warehouses w ON w.warehouse_id = s.warehouse_id
ORDER BY s.snapshot_id
"""


def run(src: sqlite3.Connection, dst: sqlite3.Connection, ledger: QualityLedger) -> None:
    category_by_product = {
        row["product_id"]: row["category"]
        for row in dst.execute("SELECT product_id, category FROM dim_product")
    }

    records = []
    for row in src.execute(SELECT_SNAPSHOTS):
        snapshot_date = date.fromisoformat(row["snapshot_date"])
        expiry_date = date.fromisoformat(row["expiry_date"])
        remaining_shelf_life_days = (expiry_date - snapshot_date).days

        available_cases = (
            (row["on_hand_cases"] or 0)
            - (row["allocated_cases"] or 0)
            - (row["damaged_cases"] or 0)
            - (row["blocked_cases"] or 0)
        )

        records.append(
            (
                row["snapshot_id"], row["snapshot_date"], row["warehouse_id"],
                row["region_id"], row["product_id"],
                category_by_product.get(row["product_id"]), row["batch_id"],
                row["on_hand_cases"] or 0, row["allocated_cases"] or 0,
                row["damaged_cases"] or 0, row["blocked_cases"] or 0,
                available_cases, row["days_of_cover"], row["expiry_date"],
                remaining_shelf_life_days, row["ageing_bucket"],
                row["storage_temp_celsius"], 0, "",
            )
        )

    dst.executemany(
        """
        INSERT INTO fact_inventory_snapshot (
            snapshot_id, snapshot_date, warehouse_id, region_id, product_id,
            category, batch_id, on_hand_cases, allocated_cases, damaged_cases,
            blocked_cases, available_cases, days_of_cover, expiry_date,
            remaining_shelf_life_days, ageing_bucket, storage_temp_celsius,
            is_excluded, exclusion_rules
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        records,
    )
