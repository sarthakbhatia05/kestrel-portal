"""Near-expiry stock. PRD 5.5.

Stock is near-expiry when remaining shelf life at the snapshot date is at or
below the configured threshold (PRD A2, 30 days by default, exposed as a
query parameter the same way OTIF exposes tolerance_minutes).

Inventory is a weekly snapshot, not a period range like the other three
metrics -- there is no "SUM over dates" to compute, only a single as-at
figure -- so NearExpiryRequest carries snapshot_date instead of
period_start/period_end, and the basis states that date instead of a period
label (PRD 5.5: "must be labelled with the snapshot date wherever
displayed").

available_cases already excludes damaged/blocked (s50_inventory); those are
reported separately in the basis, the same way returns' basis surfaces
pending/rejected value instead of folding it into the rate.

Grain breakdown is warehouse and category (PRD C3.3), a different set from
every other metric's grains.
"""

import sqlite3

from kestrel.metrics.types import (
    NearExpiryBasis,
    NearExpiryGrain,
    NearExpiryRequest,
    NearExpiryResult,
    NearExpiryRow,
)

METRIC = "near_expiry"

_GRAINS: dict[NearExpiryGrain, tuple[str, str]] = {
    NearExpiryGrain.WAREHOUSE: ("CAST(s.warehouse_id AS TEXT)", "w.warehouse_name"),
    NearExpiryGrain.CATEGORY: ("s.category", "s.category"),
}


def latest_snapshot_date(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT MAX(snapshot_date) AS latest FROM fact_inventory_snapshot"
    ).fetchone()
    return row["latest"] if row else None


def _scope_name(conn: sqlite3.Connection, region_id: int | None) -> str:
    if region_id is None:
        return "National"
    row = conn.execute(
        "SELECT region_name FROM dim_region WHERE region_id = ?", (region_id,)
    ).fetchone()
    return row["region_name"] if row else f"Region {region_id}"


def _where(request: NearExpiryRequest) -> tuple[list[str], list[object]]:
    filters = ["s.snapshot_date = ?"]
    params: list[object] = [request.snapshot_date.isoformat()]
    if request.region_id is not None:
        filters.append("s.region_id = ?")
        params.append(request.region_id)
    return filters, params


def compute(conn: sqlite3.Connection, request: NearExpiryRequest) -> NearExpiryResult:
    grain_key, grain_label = _GRAINS[request.grain]
    filters, params = _where(request)
    where = " AND ".join(filters)
    warehouse_join = (
        "JOIN dim_warehouse w ON w.warehouse_id = s.warehouse_id"
        if request.grain is NearExpiryGrain.WAREHOUSE else ""
    )

    headline_sql = f"""
        SELECT
            SUM(CASE WHEN s.remaining_shelf_life_days <= ?
                     THEN s.available_cases ELSE 0 END) AS near_expiry_cases,
            SUM(CASE WHEN s.remaining_shelf_life_days <= ?
                     THEN s.available_cases * p.case_pack * p.list_price_inr
                     ELSE 0 END) AS near_expiry_value,
            SUM(s.available_cases) AS total_cases,
            SUM(s.damaged_cases) AS damaged_cases,
            SUM(s.damaged_cases * p.case_pack * p.list_price_inr) AS damaged_value,
            SUM(s.blocked_cases) AS blocked_cases,
            SUM(s.blocked_cases * p.case_pack * p.list_price_inr) AS blocked_value,
            COUNT(*) AS row_count
        FROM fact_inventory_snapshot s
        JOIN dim_product p ON p.product_id = s.product_id
        WHERE {where}
    """  # noqa: S608 - every fragment comes from the allowlist above; only `?` is parameterised
    headline_row = conn.execute(
        headline_sql, [request.threshold_days, request.threshold_days, *params]
    ).fetchone()

    scope = _scope_name(conn, request.region_id)
    total_cases = headline_row["total_cases"] or 0
    headline = NearExpiryRow(
        key="total",
        label=scope,
        near_expiry_cases=headline_row["near_expiry_cases"] or 0,
        total_available_cases=total_cases,
        near_expiry_rate=(headline_row["near_expiry_cases"] or 0) / total_cases
        if total_cases else None,
        near_expiry_value_inr=headline_row["near_expiry_value"] or 0,
    )

    breakdown_sql = f"""
        SELECT {grain_key} AS key, {grain_label} AS label,
               SUM(CASE WHEN s.remaining_shelf_life_days <= ?
                        THEN s.available_cases ELSE 0 END) AS near_expiry_cases,
               SUM(CASE WHEN s.remaining_shelf_life_days <= ?
                        THEN s.available_cases * p.case_pack * p.list_price_inr
                        ELSE 0 END) AS near_expiry_value,
               SUM(s.available_cases) AS total_cases
        FROM fact_inventory_snapshot s
        JOIN dim_product p ON p.product_id = s.product_id
        {warehouse_join}
        WHERE {where}
        GROUP BY {grain_key}, {grain_label}
    """  # noqa: S608
    breakdown_rows = conn.execute(
        breakdown_sql, [request.threshold_days, request.threshold_days, *params]
    ).fetchall()

    rows = []
    for row in breakdown_rows:
        if row["key"] is None:
            continue
        denom = row["total_cases"] or 0
        if not denom:
            # No available stock in scope for this key -- a rate against a
            # zero denominator has nothing to report, same as fill
            # rate/OTIF/returns' HAVING denominator > 0.
            continue
        rows.append(
            NearExpiryRow(
                key=row["key"],
                label=row["label"],
                near_expiry_cases=row["near_expiry_cases"] or 0,
                total_available_cases=denom,
                near_expiry_rate=(row["near_expiry_cases"] or 0) / denom,
                near_expiry_value_inr=row["near_expiry_value"] or 0,
            )
        )

    if request.q:
        q_lower = request.q.lower()
        rows = [r for r in rows if q_lower in r.label.lower()]

    rows.sort(key=lambda r: r.near_expiry_rate, reverse=not request.ascending)
    if request.limit:
        rows = rows[: request.limit]

    return NearExpiryResult(
        headline=headline,
        rows=rows,
        basis=NearExpiryBasis(
            metric=METRIC,
            snapshot_date=request.snapshot_date,
            scope=scope,
            threshold_days=request.threshold_days,
            damaged_cases=headline_row["damaged_cases"] or 0,
            damaged_value_inr=headline_row["damaged_value"] or 0,
            blocked_cases=headline_row["blocked_cases"] or 0,
            blocked_value_inr=headline_row["blocked_value"] or 0,
            source_row_count=headline_row["row_count"] or 0,
        ),
    )
