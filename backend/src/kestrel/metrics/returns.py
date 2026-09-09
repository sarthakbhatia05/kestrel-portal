"""Returns and credit note leakage. PRD 5.6.

    returns_rate = SUM(credit_note_value WHERE status = APPROVED)
                 / SUM(dispatch_value)

Only APPROVED credit notes count as leakage: a REJECTED note never resulted
in a credit, and a PENDING one hasn't yet, so including them would overstate
money that was never (or not yet) given back. Both counts and their value
are still reported in the basis (pending_count/rejected_count and their
value), the way OTIF reports unmeasured_count, so the excluded rupee value
is not silently invisible.

dispatch_value comes from fact_order_line.dispatched_value_inr -- priced off
delivered_qty, not ordered_qty's line_value_inr -- since a return can only
happen against stock that was actually delivered. Numerator is scoped by
return_date, denominator by order_date, each over the same period bounds.

Cold-chain-attributable returns (RT01_NEAR_EXPIRY, RT06_COLD_CHAIN_BREACH)
are isolated as a sub-rate (PRD C3.5), the same way OTIF separates on-time
and in-full.

Grain breakdown is category, reason and region (PRD 5.6) -- a different set
from fill rate/OTIF's region/warehouse/route/outlet. Category and region
both exist on dispatched order lines too, so those rows divide by the
matching dispatch slice. Reason has no dispatch-side equivalent -- a
delivered case carries no "reason it might later be returned for" -- so
reason rows divide by the scope's total dispatch value: each row reads as
that reason's share of all dispatch value lost to returns, not a rate
confined to that reason.
"""

import sqlite3

from kestrel.metrics.types import (
    ReturnsBasis,
    ReturnsGrain,
    ReturnsRequest,
    ReturnsResult,
    ReturnsRow,
)

METRIC = "returns"

# X4 has no meaning here (fact_return has no order-status concept of its
# own) so it is left out, unlike fill rate/OTIF's exclusion list.
DEFAULT_EXCLUSIONS = ["X1", "X2", "X3", "X5"]

COLD_CHAIN_REASONS = ("RT01_NEAR_EXPIRY", "RT06_COLD_CHAIN_BREACH")
_COLD_CHAIN_PLACEHOLDERS = ",".join("?" * len(COLD_CHAIN_REASONS))

# (return-side key/label, dispatch-side key or None for "use the scope total")
_GRAINS: dict[ReturnsGrain, tuple[str, str, str | None]] = {
    ReturnsGrain.CATEGORY: ("r.category", "r.category", "p.category"),
    ReturnsGrain.REGION: (
        "CAST(r.region_id AS TEXT)", "d.region_name", "CAST(f.region_id AS TEXT)",
    ),
    ReturnsGrain.REASON: ("r.return_reason_code", "r.return_reason_code", None),
}


def _scope_name(conn: sqlite3.Connection, region_id: int | None) -> str:
    if region_id is None:
        return "National"
    row = conn.execute(
        "SELECT region_name FROM dim_region WHERE region_id = ?", (region_id,)
    ).fetchone()
    return row["region_name"] if row else f"Region {region_id}"


def _returns_where(request: ReturnsRequest) -> tuple[list[str], list[object]]:
    filters = ["r.return_date BETWEEN ? AND ?"]
    params: list[object] = [request.period_start.isoformat(), request.period_end.isoformat()]
    if not request.include_excluded:
        filters.append("r.is_excluded = 0")
        filters.append("(d2.closed_date IS NULL OR d2.closed_date >= ?)")
        params.append(request.period_start.isoformat())
    if request.region_id is not None:
        filters.append("r.region_id = ?")
        params.append(request.region_id)
    return filters, params


def _dispatch_where(request: ReturnsRequest) -> tuple[list[str], list[object]]:
    filters = ["f.order_date BETWEEN ? AND ?"]
    params: list[object] = [request.period_start.isoformat(), request.period_end.isoformat()]
    if not request.include_excluded:
        filters.append("f.is_excluded = 0")
        filters.append("(d2.closed_date IS NULL OR d2.closed_date >= ?)")
        params.append(request.period_start.isoformat())
    if request.region_id is not None:
        filters.append("f.region_id = ?")
        params.append(request.region_id)
    return filters, params


def compute(conn: sqlite3.Connection, request: ReturnsRequest) -> ReturnsResult:
    return_key, return_label, dispatch_key = _GRAINS[request.grain]
    return_filters, return_params = _returns_where(request)
    dispatch_filters, dispatch_params = _dispatch_where(request)
    return_where = " AND ".join(return_filters)
    dispatch_where = " AND ".join(dispatch_filters)

    region_label_join = (
        "LEFT JOIN dim_region d ON d.region_id = r.region_id"
        if request.grain is ReturnsGrain.REGION else ""
    )

    headline_sql = f"""
        SELECT
            SUM(CASE WHEN r.status = 'APPROVED' THEN r.credit_note_value_inr ELSE 0 END)
                AS approved_value,
            SUM(CASE WHEN r.status = 'APPROVED'
                     AND r.return_reason_code IN ({_COLD_CHAIN_PLACEHOLDERS})
                     THEN r.credit_note_value_inr ELSE 0 END) AS cold_chain_value,
            SUM(CASE WHEN r.status = 'PENDING' THEN 1 ELSE 0 END) AS pending_count,
            SUM(CASE WHEN r.status = 'PENDING' THEN r.credit_note_value_inr ELSE 0 END)
                AS pending_value,
            SUM(CASE WHEN r.status = 'REJECTED' THEN 1 ELSE 0 END) AS rejected_count,
            SUM(CASE WHEN r.status = 'REJECTED' THEN r.credit_note_value_inr ELSE 0 END)
                AS rejected_value,
            COUNT(*) AS row_count
        FROM fact_return r
        JOIN dim_outlet d2 ON d2.outlet_id = r.outlet_id
        WHERE {return_where}
    """  # noqa: S608 - every fragment comes from the allowlist above; only `?` is parameterised
    headline_row = conn.execute(
        headline_sql, [*COLD_CHAIN_REASONS, *return_params]
    ).fetchone()

    dispatch_headline_sql = f"""
        SELECT SUM(f.dispatched_value_inr) AS dispatch_value
        FROM fact_order_line f
        JOIN dim_outlet d2 ON d2.outlet_id = f.outlet_id
        WHERE {dispatch_where}
    """  # noqa: S608
    dispatch_total = (
        conn.execute(dispatch_headline_sql, dispatch_params).fetchone()["dispatch_value"] or 0
    )

    scope = _scope_name(conn, request.region_id)
    headline = ReturnsRow(
        key="total",
        label=scope,
        credit_note_value_inr=headline_row["approved_value"] or 0,
        dispatch_value_inr=dispatch_total,
        returns_rate=(headline_row["approved_value"] or 0) / dispatch_total
        if dispatch_total else None,
        cold_chain_value_inr=headline_row["cold_chain_value"] or 0,
        cold_chain_rate=(headline_row["cold_chain_value"] or 0) / dispatch_total
        if dispatch_total else None,
    )

    breakdown_sql = f"""
        SELECT {return_key} AS key, {return_label} AS label,
               SUM(CASE WHEN r.status = 'APPROVED' THEN r.credit_note_value_inr ELSE 0 END)
                   AS credit_value,
               SUM(CASE WHEN r.status = 'APPROVED'
                        AND r.return_reason_code IN ({_COLD_CHAIN_PLACEHOLDERS})
                        THEN r.credit_note_value_inr ELSE 0 END) AS cold_value
        FROM fact_return r
        JOIN dim_outlet d2 ON d2.outlet_id = r.outlet_id
        {region_label_join}
        WHERE {return_where}
        GROUP BY {return_key}, {return_label}
    """  # noqa: S608
    breakdown_rows = conn.execute(
        breakdown_sql, [*COLD_CHAIN_REASONS, *return_params]
    ).fetchall()

    if dispatch_key is None:
        dispatch_by_key: dict[str, float] = {}
    else:
        product_join = (
            "JOIN dim_product p ON p.product_id = f.product_id"
            if request.grain is ReturnsGrain.CATEGORY else ""
        )
        dispatch_breakdown_sql = f"""
            SELECT {dispatch_key} AS key, SUM(f.dispatched_value_inr) AS denom
            FROM fact_order_line f
            JOIN dim_outlet d2 ON d2.outlet_id = f.outlet_id
            {product_join}
            WHERE {dispatch_where}
            GROUP BY {dispatch_key}
        """  # noqa: S608
        dispatch_by_key = {
            row["key"]: row["denom"] or 0
            for row in conn.execute(dispatch_breakdown_sql, dispatch_params)
        }

    rows = []
    for row in breakdown_rows:
        if row["key"] is None:
            continue
        denom = dispatch_total if dispatch_key is None else dispatch_by_key.get(row["key"], 0)
        if not denom:
            # No corresponding dispatch value in scope -- a rate against a
            # zero denominator has nothing to report, same as fill
            # rate/OTIF's HAVING denominator > 0.
            continue
        rows.append(
            ReturnsRow(
                key=row["key"],
                label=row["label"],
                credit_note_value_inr=row["credit_value"] or 0,
                dispatch_value_inr=denom,
                returns_rate=(row["credit_value"] or 0) / denom,
                cold_chain_value_inr=row["cold_value"] or 0,
                cold_chain_rate=(row["cold_value"] or 0) / denom,
            )
        )

    if request.q:
        q_lower = request.q.lower()
        rows = [r for r in rows if q_lower in r.label.lower()]

    rows.sort(key=lambda r: r.returns_rate, reverse=not request.ascending)
    if request.limit:
        rows = rows[: request.limit]

    return ReturnsResult(
        headline=headline,
        rows=rows,
        basis=ReturnsBasis(
            metric=METRIC,
            period_start=request.period_start,
            period_end=request.period_end,
            period_label=request.period_label,
            scope=scope,
            exclusions_applied=[] if request.include_excluded else DEFAULT_EXCLUSIONS,
            pending_count=headline_row["pending_count"] or 0,
            pending_value_inr=headline_row["pending_value"] or 0,
            rejected_count=headline_row["rejected_count"] or 0,
            rejected_value_inr=headline_row["rejected_value"] or 0,
            source_row_count=headline_row["row_count"] or 0,
        ),
    )
