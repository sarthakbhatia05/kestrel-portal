"""Order lines normalised to eaches.

N1: quantities are converted to eaches using the line-level case pack,
falling back to the product master where the line value is absent or
implausible (A5). Case-denominated figures are later derived from the each
figure, never computed independently, which is what guarantees the case
view and the each view of the same event cannot disagree (PRD 5.1).

X4: cancelled orders are flagged. Open orders are also flagged, as not yet
due (PRD 5.2).
"""

import sqlite3

from kestrel.transform.ledger import Action, QualityLedger

name = "s20_orders"

EXCLUDED_ORDER_STATUSES = {"CANCELLED": "X4", "OPEN": "X4"}

SELECT_LINES = """
SELECT l.order_line_id, l.order_id, l.product_id, l.ordered_qty, l.qty_uom,
       l.case_pack_at_order, l.delivered_qty, l.unit_price_inr,
       l.line_discount_pct, l.short_reason_code,
       o.order_date, o.outlet_id, o.region_id, o.warehouse_id, o.route_id,
       o.order_status, o.source_system,
       p.case_pack AS master_case_pack
FROM order_lines l
JOIN orders   o ON o.order_id   = l.order_id
JOIN products p ON p.product_id = l.product_id
ORDER BY l.order_line_id
"""


def _resolve_case_pack(row, ledger: QualityLedger) -> int:
    """A5: fall back to the product master where the line value is unusable."""
    line_pack = row["case_pack_at_order"]
    master_pack = row["master_case_pack"]
    if line_pack is not None and line_pack > 0:
        return int(line_pack)

    ledger.record(
        "N1", "Case pack fallback to product master", "order_line",
        row["order_line_id"], Action.REPAIRED,
        f"case_pack_at_order={line_pack} implausible, used product master "
        f"case_pack={master_pack}",
        row["source_system"],
    )
    return int(master_pack or 1)


def run(src: sqlite3.Connection, dst: sqlite3.Connection, ledger: QualityLedger) -> None:
    excluded_outlets = {
        row["outlet_id"]: row["exclusion_rules"]
        for row in dst.execute(
            "SELECT outlet_id, exclusion_rules FROM dim_outlet WHERE is_excluded = 1"
        )
    }

    records = []
    for row in src.execute(SELECT_LINES):
        case_pack = _resolve_case_pack(row, ledger)
        multiplier = case_pack if row["qty_uom"] == "CASE" else 1

        # Returns can only happen against stock actually delivered, so the
        # returns metric's dispatch_value is priced off delivered_qty, not
        # ordered_qty (which is what the source line_value_inr reflects).
        dispatched_value_inr = (
            (row["delivered_qty"] or 0)
            * (row["unit_price_inr"] or 0)
            * (1 - (row["line_discount_pct"] or 0) / 100)
        )

        rules: list[str] = []
        status_rule = EXCLUDED_ORDER_STATUSES.get(row["order_status"])
        if status_rule:
            rules.append(status_rule)
            ledger.record(
                status_rule, "Order excluded from service measures", "order_line",
                row["order_line_id"], Action.EXCLUDED,
                f"order_status={row['order_status']}", row["source_system"],
            )

        outlet_rules = excluded_outlets.get(row["outlet_id"])
        if outlet_rules:
            rules.extend(r for r in outlet_rules.split(",") if r)

        records.append(
            (
                row["order_line_id"], row["order_id"], row["order_date"],
                row["outlet_id"], row["region_id"], row["warehouse_id"],
                row["route_id"], row["product_id"], row["order_status"],
                row["source_system"], row["qty_uom"], case_pack,
                (row["ordered_qty"] or 0) * multiplier,
                (row["delivered_qty"] or 0) * multiplier,
                dispatched_value_inr,
                row["short_reason_code"],
                1 if rules else 0, ",".join(dict.fromkeys(rules)),
            )
        )

    dst.executemany(
        """
        INSERT INTO fact_order_line (
            order_line_id, order_id, order_date, outlet_id, region_id,
            warehouse_id, route_id, product_id, order_status, source_system,
            qty_uom, case_pack, ordered_qty_eaches, delivered_qty_eaches,
            dispatched_value_inr, short_reason_code, is_excluded, exclusion_rules
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        records,
    )
