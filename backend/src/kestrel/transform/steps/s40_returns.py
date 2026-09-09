"""Returns and credit notes. PRD 5.6.

N4: return_qty arrives with an inconsistent sign convention across upstream
feeds and is normalised to a positive magnitude here, with the original sign
retained (return_qty_orig_sign) for audit -- the value column itself
(credit_note_value_inr) is never negative in the source data, so only the
quantity needs normalising.

Region and category are denormalised onto the fact from the order/outlet and
product it references, the same way s30_deliveries denormalises order
context onto the delivery. Reason code, disposition and status are carried
through as captured (PRD 5.6: "reported as captured"), not reinterpreted.
"""

import sqlite3

from kestrel.transform.ledger import Action, QualityLedger

name = "s40_returns"

SELECT_RETURNS = """
SELECT r.return_id, r.credit_note_number, r.order_id, r.order_line_id,
       r.outlet_id, r.product_id, r.return_date, r.return_qty, r.qty_uom,
       r.return_reason_code, r.credit_note_value_inr, r.disposition,
       r.status, o.region_id, o.source_system
FROM returns_credit_notes r
LEFT JOIN orders o ON o.order_id = r.order_id
ORDER BY r.return_id
"""


def run(src: sqlite3.Connection, dst: sqlite3.Connection, ledger: QualityLedger) -> None:
    outlet_exclusions = {
        row["outlet_id"]: row["exclusion_rules"]
        for row in dst.execute(
            "SELECT outlet_id, exclusion_rules FROM dim_outlet WHERE is_excluded = 1"
        )
    }
    category_by_product = {
        row["product_id"]: row["category"]
        for row in dst.execute("SELECT product_id, category FROM dim_product")
    }

    records = []
    for row in src.execute(SELECT_RETURNS):
        raw_qty = row["return_qty"] or 0
        if raw_qty < 0:
            ledger.record(
                "N4", "Return quantity sign-normalised", "return", row["return_id"],
                Action.REPAIRED, f"return_qty={raw_qty} normalised to magnitude",
                row["source_system"],
            )
        qty = abs(raw_qty)
        orig_sign = -1 if raw_qty < 0 else 1

        rules = outlet_exclusions.get(row["outlet_id"], "")

        records.append(
            (
                row["return_id"], row["credit_note_number"], row["order_id"],
                row["order_line_id"], row["outlet_id"], row["region_id"],
                row["product_id"], category_by_product.get(row["product_id"]),
                row["return_date"], qty, orig_sign, row["qty_uom"],
                row["return_reason_code"], row["credit_note_value_inr"] or 0,
                row["disposition"], row["status"],
                1 if rules else 0, rules,
            )
        )

    dst.executemany(
        """
        INSERT INTO fact_return (
            return_id, credit_note_number, order_id, order_line_id, outlet_id,
            region_id, product_id, category, return_date, return_qty,
            return_qty_orig_sign, qty_uom, return_reason_code,
            credit_note_value_inr, disposition, status,
            is_excluded, exclusion_rules
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        records,
    )
