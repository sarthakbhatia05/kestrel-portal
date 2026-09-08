"""Fill rate. PRD 5.2.

    fill_rate_eaches = SUM(delivered_qty_eaches) / SUM(ordered_qty_eaches)
    fill_rate_cases  = SUM(delivered_qty_eaches / case_pack)
                     / SUM(ordered_qty_eaches   / case_pack)

The case figure is derived from the each figure, never computed
independently, so the two views of the same event cannot disagree.

This module is the only implementation of fill rate. The dashboard and
ask-anything both call it, which is what makes G1 enforceable.
"""

import sqlite3

from kestrel.metrics.types import (
    Grain,
    MetricBasis,
    MetricRequest,
    MetricResult,
    MetricRow,
    Unit,
)

METRIC = "fill_rate"

# Grain resolves through this allowlist, never through string interpolation
# of user input. Values are (extra join, key expression, label expression).
#
# dim_outlet is always joined as `d2` regardless of grain, because the X3
# rule is period-scoped and must be applied at every grain. Outlet grain
# therefore needs no extra join and reads its label from d2.
_GRAINS: dict[Grain, tuple[str, str, str]] = {
    Grain.OUTLET: ("", "d2.outlet_id", "d2.outlet_name"),
    Grain.REGION: (
        "JOIN dim_region d ON d.region_id = f.region_id",
        "f.region_id",
        "d.region_name",
    ),
    Grain.WAREHOUSE: ("", "f.warehouse_id", "'Warehouse ' || f.warehouse_id"),
    Grain.ROUTE: ("", "f.route_id", "'Route ' || f.route_id"),
}

DEFAULT_EXCLUSIONS = ["X1", "X2", "X3", "X4", "X5"]


def _scope_name(conn: sqlite3.Connection, region_id: int | None) -> str:
    if region_id is None:
        return "National"
    row = conn.execute(
        "SELECT region_name FROM dim_region WHERE region_id = ?", (region_id,)
    ).fetchone()
    return row["region_name"] if row else f"Region {region_id}"


def compute(conn: sqlite3.Connection, request: MetricRequest) -> MetricResult:
    grain_join, key_source, label_source = _GRAINS[request.grain]

    if request.unit is Unit.CASES:
        numerator = "SUM(f.delivered_qty_eaches / f.case_pack)"
        denominator = "SUM(f.ordered_qty_eaches / f.case_pack)"
    else:
        numerator = "SUM(f.delivered_qty_eaches)"
        denominator = "SUM(f.ordered_qty_eaches)"

    filters = ["f.order_date BETWEEN ? AND ?"]
    params: list[object] = [
        request.period_start.isoformat(),
        request.period_end.isoformat(),
    ]

    if not request.include_excluded:
        filters.append("f.is_excluded = 0")
        # X3: closed outlets are excluded from periods after their closure
        # date, and retained in periods up to it.
        filters.append("(d2.closed_date IS NULL OR d2.closed_date >= ?)")
        params.append(request.period_start.isoformat())

    if request.region_id is not None:
        filters.append("f.region_id = ?")
        params.append(request.region_id)

    # dim_outlet is always joined so the period-scoped X3 rule can be applied
    # at every grain, not only at outlet grain.
    outlet_join = "JOIN dim_outlet d2 ON d2.outlet_id = f.outlet_id"

    order = "ASC" if request.ascending else "DESC"
    limit_sql = "LIMIT ?" if request.limit else ""
    # The filters and their parameters are shared by both queries below; only
    # the breakdown query appends a LIMIT parameter.
    where = " AND ".join(filters)
    breakdown_params = [*params, request.limit] if request.limit else params

    sql = f"""
        SELECT CAST({key_source} AS TEXT) AS key,
               {label_source} AS label,
               {numerator} AS numerator,
               {denominator} AS denominator,
               COUNT(*) AS row_count
        FROM fact_order_line f
        {outlet_join}
        {grain_join}
        WHERE {where}
        GROUP BY {key_source}, {label_source}
        HAVING {denominator} > 0
        ORDER BY (1.0 * {numerator} / {denominator}) {order}
        {limit_sql}
    """  # noqa: S608 - every fragment comes from the allowlist above

    rows = [
        MetricRow(
            key=row["key"],
            label=row["label"],
            numerator=row["numerator"],
            denominator=row["denominator"],
            value=row["numerator"] / row["denominator"],
        )
        for row in conn.execute(sql, breakdown_params)
    ]

    # The headline is recomputed over the whole scope rather than aggregated
    # from `rows`, because `rows` may be limited to the worst performers.
    headline_sql = f"""
        SELECT {numerator} AS numerator, {denominator} AS denominator,
               COUNT(*) AS row_count
        FROM fact_order_line f
        {outlet_join}
        WHERE {where}
    """  # noqa: S608
    totals = conn.execute(headline_sql, params).fetchone()

    denom = totals["denominator"] or 0
    headline = (totals["numerator"] / denom) if denom else None

    return MetricResult(
        headline=headline,
        rows=rows,
        basis=MetricBasis(
            metric=METRIC,
            period_start=request.period_start,
            period_end=request.period_end,
            period_label=request.period_label,
            unit=request.unit,
            scope=_scope_name(conn, request.region_id),
            exclusions_applied=[] if request.include_excluded else DEFAULT_EXCLUSIONS,
            unmeasured_count=0,
            source_row_count=totals["row_count"] or 0,
        ),
    )
