"""On-time in-full (OTIF). PRD 5.3.

    otif = COUNT(on_time AND in_full) / COUNT(due)

On-time and in-full are reported separately as well as combined (PRD C2.4):
a delivery can fail on either axis independently, and the two need
different fixes on the ground.

`in_full` reuses the eaches sums `s30_deliveries` already computed from
`fact_order_line` -- nothing here redoes case-pack conversion. `delay_minutes`
comes from that same step, computed from actual_arrival - planned_arrival
directly; the source delay_minutes column is not read (see that module's
docstring for why).

request.tolerance_minutes must already be resolved by the caller (the
router substitutes the configured default when the client omits it) so the
basis can state the tolerance that produced a given figure (PRD A1).
"""

import sqlite3

from kestrel.metrics.types import Grain, MetricBasis, MetricRequest, OtifResult, OtifRow

METRIC = "otif"

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

# X4 is structural for deliveries -- cancelled/open orders never produce a
# delivery row, so there is no per-row flag for it -- but it is still a real
# exclusion and is worth stating alongside the others, the way fill rate's
# basis does.
DEFAULT_EXCLUSIONS = ["X1", "X2", "X3", "X4", "X5"]

_ON_TIME = "(f.delay_minutes IS NOT NULL AND f.delay_minutes <= ?)"
_IN_FULL = "f.delivered_qty_eaches >= f.ordered_qty_eaches"


def _scope_name(conn: sqlite3.Connection, region_id: int | None) -> str:
    if region_id is None:
        return "National"
    row = conn.execute(
        "SELECT region_name FROM dim_region WHERE region_id = ?", (region_id,)
    ).fetchone()
    return row["region_name"] if row else f"Region {region_id}"


def _row(key: str, label: str, due: int, on_time: int, in_full: int, hit: int) -> OtifRow:
    return OtifRow(
        key=key,
        label=label,
        due_count=due,
        on_time_count=on_time,
        in_full_count=in_full,
        otif_count=hit,
        on_time_rate=(on_time / due) if due else None,
        in_full_rate=(in_full / due) if due else None,
        otif=(hit / due) if due else None,
    )


def compute(conn: sqlite3.Connection, request: MetricRequest) -> OtifResult:
    grain_join, key_source, label_source = _GRAINS[request.grain]
    tolerance = request.tolerance_minutes

    where_filters = ["date(f.planned_arrival) BETWEEN ? AND ?"]
    where_params: list[object] = [
        request.period_start.isoformat(),
        request.period_end.isoformat(),
    ]

    if not request.include_excluded:
        where_filters.append("f.is_excluded = 0")
        # X3: closed outlets are excluded from periods after their closure
        # date, same period-scoped rule fill rate applies.
        where_filters.append("(d2.closed_date IS NULL OR d2.closed_date >= ?)")
        where_params.append(request.period_start.isoformat())

    if request.region_id is not None:
        where_filters.append("f.region_id = ?")
        where_params.append(request.region_id)

    outlet_join = "JOIN dim_outlet d2 ON d2.outlet_id = f.outlet_id"
    where = " AND ".join(where_filters)

    order = "ASC" if request.ascending else "DESC"
    limit_sql = "LIMIT ?" if request.limit else ""

    # `?` order follows the SQL text left to right: the two tolerance
    # placeholders in SELECT come first, then the WHERE params, then the
    # optional search and LIMIT params (both appear only in HAVING/LIMIT).
    select_params = [tolerance, tolerance]
    having_clauses = ["due_count > 0"]
    breakdown_params = [*select_params, *where_params]
    if request.q:
        having_clauses.append("LOWER(label) LIKE ?")
        breakdown_params.append(f"%{request.q.lower()}%")
    having = " AND ".join(having_clauses)
    if request.limit:
        breakdown_params.append(request.limit)
    headline_params = [*select_params, *where_params]

    sql = f"""
        SELECT CAST({key_source} AS TEXT) AS key,
               {label_source} AS label,
               COUNT(*) AS due_count,
               SUM(CASE WHEN {_ON_TIME} THEN 1 ELSE 0 END) AS on_time_count,
               SUM(CASE WHEN {_IN_FULL} THEN 1 ELSE 0 END) AS in_full_count,
               SUM(CASE WHEN {_ON_TIME} AND {_IN_FULL} THEN 1 ELSE 0 END) AS otif_count
        FROM fact_delivery f
        {outlet_join}
        {grain_join}
        WHERE {where}
        GROUP BY {key_source}, {label_source}
        HAVING {having}
        ORDER BY (1.0 * otif_count / due_count) {order}
        {limit_sql}
    """  # noqa: S608 - every fragment comes from the allowlist above; only `?` is parameterised

    rows = [
        _row(
            r["key"], r["label"], r["due_count"], r["on_time_count"],
            r["in_full_count"], r["otif_count"],
        )
        for r in conn.execute(sql, breakdown_params)
    ]

    headline_sql = f"""
        SELECT COUNT(*) AS due_count,
               SUM(CASE WHEN {_ON_TIME} THEN 1 ELSE 0 END) AS on_time_count,
               SUM(CASE WHEN {_IN_FULL} THEN 1 ELSE 0 END) AS in_full_count,
               SUM(CASE WHEN {_ON_TIME} AND {_IN_FULL} THEN 1 ELSE 0 END) AS otif_count,
               SUM(CASE WHEN f.delay_minutes IS NULL THEN 1 ELSE 0 END) AS unmeasured_count
        FROM fact_delivery f
        {outlet_join}
        WHERE {where}
    """  # noqa: S608
    totals = conn.execute(headline_sql, headline_params).fetchone()

    headline = _row(
        "total", _scope_name(conn, request.region_id),
        totals["due_count"] or 0, totals["on_time_count"] or 0,
        totals["in_full_count"] or 0, totals["otif_count"] or 0,
    )

    return OtifResult(
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
            unmeasured_count=totals["unmeasured_count"] or 0,
            tolerance_minutes=tolerance,
            source_row_count=totals["due_count"] or 0,
        ),
    )
