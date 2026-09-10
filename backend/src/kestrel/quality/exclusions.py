"""What each measure leaves out of a scope, and which rule removed it.

PRD 6.4: the quality view "must state, in counts, what the numbers on every
other screen exclude". The ledger alone cannot: it records one entry per
soft-deleted *outlet*, while the dashboard excludes every *order line*,
delivery and credit note belonging to it. And X3 is never in the ledger at
all, because whether a closed outlet counts depends on the period viewed.

So the counts here are taken over the same fact table, date column and
filters each metric uses, and tests/test_quality_exclusions.py holds them to
the metrics' own row counts. Build-time rules are read from each row's
`exclusion_rules` flags; X3 is evaluated exactly as the metrics evaluate it.
"""

import sqlite3
from dataclasses import dataclass

from kestrel.fiscal import Period
from kestrel.quality.rules import RULES_BY_REF
from kestrel.quality.types import MeasureExclusions, QualityResult, RuleCount

_NO_DELIVERY_FOR_X4 = (
    "Cancelled and open orders never produce a delivery, so they are absent "
    "here rather than counted."
)


@dataclass(frozen=True)
class _Measure:
    measure: str
    label: str
    entity: str
    table: str
    # The period column the metric filters on; the table is aliased `f`.
    date_expr: str
    rules: tuple[str, ...]
    extra_filter: str | None = None
    note: str | None = None


_FILL_RATE = _Measure(
    "fill_rate", "Fill rate", "order lines", "fact_order_line", "f.order_date",
    ("X1", "X2", "X3", "X4", "X5"),
)
_OTIF = _Measure(
    "otif", "OTIF", "deliveries", "fact_delivery", "date(f.planned_arrival)",
    ("X1", "X2", "X3", "X5"), note=_NO_DELIVERY_FOR_X4,
)
_RETURNS = _Measure(
    "returns", "Returns", "credit notes", "fact_return", "f.return_date",
    ("X1", "X2", "X3", "X5"),
    note="The dispatch value returns are divided by comes from the order lines "
    "counted under fill rate.",
)
_EXCURSIONS = _Measure(
    "excursions", "Temperature excursions", "chilled deliveries", "fact_delivery",
    "date(f.planned_arrival)", ("X1", "X2", "X3", "X5"),
    extra_filter="f.is_chilled = 1", note=_NO_DELIVERY_FOR_X4,
)

_NEAR_EXPIRY = MeasureExclusions(
    measure="near_expiry",
    label="Near-expiry stock",
    entity="inventory batches",
    applies=False,
    in_scope_count=None,
    included_count=None,
    excluded_count=None,
    by_rule=[],
    note="No exclusion rule applies to warehouse stock: every batch in the "
    "snapshot is counted.",
)

# X3 as the metrics apply it: an outlet that closed before the period began.
_CLOSED_BEFORE_PERIOD = "(d2.closed_date IS NOT NULL AND d2.closed_date < :start)"
_INCLUDED = "(f.is_excluded = 0 AND (d2.closed_date IS NULL OR d2.closed_date >= :start))"


def _rule_expr(ref: str) -> str:
    if ref == "X3":
        return _CLOSED_BEFORE_PERIOD
    # exclusion_rules is a comma-separated list such as "X4,X1,X5"; wrapping
    # both sides in commas stops X1 matching a hypothetical X10.
    return f"(',' || f.exclusion_rules || ',' LIKE '%,{ref},%')"


def _count(
    conn: sqlite3.Connection, spec: _Measure, period: Period, region_id: int | None
) -> MeasureExclusions:
    filters = [f"{spec.date_expr} BETWEEN :start AND :end"]
    if spec.extra_filter:
        filters.append(spec.extra_filter)
    if region_id is not None:
        filters.append("f.region_id = :region_id")

    rule_columns = ",\n".join(
        f"SUM(CASE WHEN {_rule_expr(ref)} THEN 1 ELSE 0 END) AS {ref}" for ref in spec.rules
    )
    # Every fragment is from the fixed definitions above; only `:` names are
    # parameterised. dim_outlet is inner-joined exactly as the metrics join it.
    sql = f"""
        SELECT COUNT(*) AS in_scope,
               SUM(CASE WHEN {_INCLUDED} THEN 1 ELSE 0 END) AS included,
               {rule_columns}
        FROM {spec.table} f
        JOIN dim_outlet d2 ON d2.outlet_id = f.outlet_id
        WHERE {" AND ".join(filters)}
    """  # noqa: S608
    row = conn.execute(
        sql,
        {
            "start": period.start.isoformat(),
            "end": period.end.isoformat(),
            "region_id": region_id,
        },
    ).fetchone()

    in_scope = row["in_scope"]
    included = row["included"] or 0
    return MeasureExclusions(
        measure=spec.measure,
        label=spec.label,
        entity=spec.entity,
        applies=True,
        in_scope_count=in_scope,
        included_count=included,
        excluded_count=in_scope - included,
        by_rule=[
            RuleCount(rule_ref=ref, rule_name=RULES_BY_REF[ref].name, count=row[ref] or 0)
            for ref in spec.rules
        ],
        note=spec.note,
    )


def _scope_name(conn: sqlite3.Connection, region_id: int | None) -> str:
    if region_id is None:
        return "National"
    row = conn.execute(
        "SELECT region_name FROM dim_region WHERE region_id = ?", (region_id,)
    ).fetchone()
    return row["region_name"] if row else f"Region {region_id}"


def compute(conn: sqlite3.Connection, period: Period, region_id: int | None) -> QualityResult:
    """Exclusions for every measure, in the order the control tower shows them."""
    return QualityResult(
        period_start=period.start,
        period_end=period.end,
        period_label=period.label,
        scope=_scope_name(conn, region_id),
        measures=[
            _count(conn, _FILL_RATE, period, region_id),
            _count(conn, _OTIF, period, region_id),
            _count(conn, _RETURNS, period, region_id),
            _NEAR_EXPIRY,
            _count(conn, _EXCURSIONS, period, region_id),
        ],
    )
