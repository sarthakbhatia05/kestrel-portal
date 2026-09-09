"""Temperature excursion rate. PRD 5.4.

    excursion_rate = COUNT(chilled deliveries with excursion) / COUNT(chilled deliveries)

A delivery is chilled if `fact_delivery.is_chilled` was set by `s30_deliveries`
(derived from any line's product being chilled, PRD 5.4). The breach flag and
peak temperature are copied straight from the source; duration and severity
are not captured and must not be inferred (PRD 5.4), so no such figure is
computed here.

Reported by month (C3.1, the headline breakdown) and by route/warehouse for
concentration (C3.2) -- a third grain set, distinct from fill rate/OTIF's
region/warehouse/route/outlet and returns' category/reason/region.

Exclusions mirror OTIF's: a chilled delivery still belongs to an outlet, and
X4 is structural here for the same reason it is for OTIF -- a cancelled or
open order never produces a delivery row.
"""

import sqlite3

from kestrel.metrics.types import (
    ExcursionsBasis,
    ExcursionsGrain,
    ExcursionsRequest,
    ExcursionsResult,
    ExcursionsRow,
)

METRIC = "excursions"

DEFAULT_EXCLUSIONS = ["X1", "X2", "X3", "X4", "X5"]

_GRAINS: dict[ExcursionsGrain, tuple[str, str, str]] = {
    ExcursionsGrain.MONTH: ("", "strftime('%Y-%m', f.planned_arrival)", "key"),
    ExcursionsGrain.ROUTE: (
        "LEFT JOIN dim_route dr ON dr.route_id = f.route_id",
        "CAST(f.route_id AS TEXT)",
        "COALESCE(dr.route_name, 'Route ' || f.route_id)",
    ),
    ExcursionsGrain.WAREHOUSE: (
        "LEFT JOIN dim_warehouse dw ON dw.warehouse_id = f.warehouse_id",
        "CAST(f.warehouse_id AS TEXT)",
        "COALESCE(dw.warehouse_name, 'Warehouse ' || f.warehouse_id)",
    ),
}


def _scope_name(conn: sqlite3.Connection, region_id: int | None) -> str:
    if region_id is None:
        return "National"
    row = conn.execute(
        "SELECT region_name FROM dim_region WHERE region_id = ?", (region_id,)
    ).fetchone()
    return row["region_name"] if row else f"Region {region_id}"


def _row(key: str, label: str, chilled: int, excursions: int) -> ExcursionsRow:
    return ExcursionsRow(
        key=key,
        label=label,
        chilled_count=chilled,
        excursion_count=excursions,
        excursion_rate=(excursions / chilled) if chilled else None,
    )


def compute(conn: sqlite3.Connection, request: ExcursionsRequest) -> ExcursionsResult:
    grain_join, key_source, label_source = _GRAINS[request.grain]
    # The month grain's label is the same value as its key (e.g. "2026-04"),
    # so the SELECT below aliases it once and reuses the alias for both.
    label_expr = key_source if label_source == "key" else label_source

    where_filters = [
        "date(f.planned_arrival) BETWEEN ? AND ?",
        "f.is_chilled = 1",
    ]
    where_params: list[object] = [
        request.period_start.isoformat(),
        request.period_end.isoformat(),
    ]

    if not request.include_excluded:
        where_filters.append("f.is_excluded = 0")
        where_filters.append("(d2.closed_date IS NULL OR d2.closed_date >= ?)")
        where_params.append(request.period_start.isoformat())

    if request.region_id is not None:
        where_filters.append("f.region_id = ?")
        where_params.append(request.region_id)

    outlet_join = "JOIN dim_outlet d2 ON d2.outlet_id = f.outlet_id"
    where = " AND ".join(where_filters)

    order = "ASC" if request.ascending else "DESC"
    limit_sql = "LIMIT ?" if request.limit else ""

    having_clauses = ["chilled_count > 0"]
    breakdown_params = list(where_params)
    if request.q:
        having_clauses.append("LOWER(label) LIKE ?")
        breakdown_params.append(f"%{request.q.lower()}%")
    having = " AND ".join(having_clauses)
    if request.limit:
        breakdown_params.append(request.limit)

    sql = f"""
        SELECT {key_source} AS key,
               {label_expr} AS label,
               COUNT(*) AS chilled_count,
               SUM(CASE WHEN f.temperature_excursion_flag = 1 THEN 1 ELSE 0 END)
                   AS excursion_count
        FROM fact_delivery f
        {outlet_join}
        {grain_join}
        WHERE {where}
        GROUP BY {key_source}, {label_expr}
        HAVING {having}
        ORDER BY (1.0 * excursion_count / chilled_count) {order}
        {limit_sql}
    """  # noqa: S608 - every fragment comes from the allowlist above; only `?` is parameterised

    rows = [
        _row(r["key"], r["label"], r["chilled_count"], r["excursion_count"])
        for r in conn.execute(sql, breakdown_params)
    ]

    headline_sql = f"""
        SELECT COUNT(*) AS chilled_count,
               SUM(CASE WHEN f.temperature_excursion_flag = 1 THEN 1 ELSE 0 END)
                   AS excursion_count
        FROM fact_delivery f
        {outlet_join}
        WHERE {where}
    """  # noqa: S608
    totals = conn.execute(headline_sql, where_params).fetchone()

    scope = _scope_name(conn, request.region_id)
    headline = _row(
        "total", scope, totals["chilled_count"] or 0, totals["excursion_count"] or 0
    )

    return ExcursionsResult(
        headline=headline,
        rows=rows,
        basis=ExcursionsBasis(
            metric=METRIC,
            period_start=request.period_start,
            period_end=request.period_end,
            period_label=request.period_label,
            scope=scope,
            exclusions_applied=[] if request.include_excluded else DEFAULT_EXCLUSIONS,
            source_row_count=totals["chilled_count"] or 0,
        ),
    )
