"""Deliveries, evaluated for on-time performance. PRD 5.3.

N3: actual_arrival is supplied in two different timestamp formats (a
"two-vendor" split, per the Slice 1 design doc's step table). A value
matching neither is logged and stored as NULL, which the OTIF metric then
reports as unmeasured rather than silently dropping it from the denominator.

The source `delay_minutes` column is deliberately not read. Verified against
the real data, it disagrees with actual_arrival - planned_arrival on the
large majority of rows, with no discernible pattern. PRD 5.3 defines on-time
from the two timestamps directly, so this step computes delay itself.
"""

import sqlite3
from datetime import datetime

from kestrel.transform.ledger import Action, QualityLedger

name = "s30_deliveries"

# The two vendor formats seen in `actual_arrival`, tried in order. A value
# matching neither is unparseable (N3). `planned_arrival` is always the
# first (ISO) format in the source data.
_ACTUAL_ARRIVAL_FORMATS = ("%Y-%m-%d %H:%M:%S", "%d-%b-%Y %I:%M %p")
_PLANNED_ARRIVAL_FORMAT = "%Y-%m-%d %H:%M:%S"

SELECT_DELIVERIES = """
SELECT d.delivery_id, d.order_id, d.planned_arrival, d.actual_arrival,
       d.route_id, d.warehouse_id, o.outlet_id, o.region_id, o.source_system
FROM deliveries d
JOIN orders o ON o.order_id = d.order_id
ORDER BY d.delivery_id
"""


def _parse_actual(value: str) -> datetime | None:
    for fmt in _ACTUAL_ARRIVAL_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def run(src: sqlite3.Connection, dst: sqlite3.Connection, ledger: QualityLedger) -> None:
    outlet_exclusions = {
        row["outlet_id"]: row["exclusion_rules"]
        for row in dst.execute(
            "SELECT outlet_id, exclusion_rules FROM dim_outlet WHERE is_excluded = 1"
        )
    }
    eaches_by_order = {
        row["order_id"]: (row["ordered_eaches"], row["delivered_eaches"])
        for row in dst.execute(
            """
            SELECT order_id, SUM(ordered_qty_eaches) AS ordered_eaches,
                   SUM(delivered_qty_eaches) AS delivered_eaches
            FROM fact_order_line
            GROUP BY order_id
            """
        )
    }

    records = []
    for row in src.execute(SELECT_DELIVERIES):
        actual_dt = _parse_actual(row["actual_arrival"])
        if actual_dt is None:
            ledger.record(
                "N3", "Arrival timestamp unparseable", "delivery", row["delivery_id"],
                Action.REJECTED,
                f"actual_arrival={row['actual_arrival']!r} matched no known format",
                row["source_system"],
            )
            delay_minutes = None
        else:
            planned_dt = datetime.strptime(row["planned_arrival"], _PLANNED_ARRIVAL_FORMAT)
            delay_minutes = (actual_dt - planned_dt).total_seconds() / 60

        ordered_eaches, delivered_eaches = eaches_by_order.get(row["order_id"], (0.0, 0.0))
        rules = outlet_exclusions.get(row["outlet_id"], "")

        records.append(
            (
                row["delivery_id"], row["order_id"], row["planned_arrival"], delay_minutes,
                row["outlet_id"], row["region_id"], row["warehouse_id"], row["route_id"],
                ordered_eaches, delivered_eaches,
                1 if rules else 0, rules,
            )
        )

    dst.executemany(
        """
        INSERT INTO fact_delivery (
            delivery_id, order_id, planned_arrival, delay_minutes,
            outlet_id, region_id, warehouse_id, route_id,
            ordered_qty_eaches, delivered_qty_eaches, is_excluded, exclusion_rules
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        records,
    )
