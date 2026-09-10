"""What each measure leaves out of a scope, and why (PRD 6.3, 6.4).

The counts here are only worth showing if they agree with the figures on
every other screen, so the reconciliation tests at the bottom run the real
metric implementations and hold this module to their row counts.
"""

import sqlite3
from datetime import date

import pytest

from kestrel.fiscal import Period, PeriodKind
from kestrel.metrics import excursions, fill_rate, otif, returns
from kestrel.metrics.types import (
    ExcursionsGrain,
    ExcursionsRequest,
    Grain,
    MetricRequest,
    ReturnsGrain,
    ReturnsRequest,
)
from kestrel.quality import exclusions
from kestrel.transform.runner import build
from kestrel.transform.steps import s00_reference, s20_orders, s30_deliveries, s40_returns

FY27_Q1 = Period(start=date(2026, 4, 1), end=date(2026, 6, 30), label="FY27 Q1")
# Starts before outlet 3 closed (2025-06-30), so X3 must not apply to it.
SPANNING = Period(
    start=date(2025, 6, 1), end=date(2026, 6, 30), label="Jun 2025 to Jun 2026",
    kind=PeriodKind.RANGE,
)


@pytest.fixture
def conn(tmp_path, source_db):
    # The shared fixture's only row at closed outlet 3 is also a cancelled
    # order, so X3 never acts alone there and a drift in X3 would hide
    # behind X4. Order 905 is a delivered, chilled order at outlet 3, with a
    # delivery and a credit note: excluded by X3 and nothing else.
    src = sqlite3.connect(source_db)
    src.execute(
        "INSERT INTO orders VALUES (905, 3, '2026-04-13', 1, 11, 1, 'DELIVERED', 'ERP_WEB')"
    )
    src.execute("INSERT INTO order_lines VALUES (8, 905, 200, 2, 'CASE', 6, 2, 50, 0, NULL)")
    src.execute(
        "INSERT INTO deliveries VALUES "
        "(5, 905, '2026-04-18 09:00:00', '2026-04-18 09:10:00', 10, 11, 1, 0, 4.0)"
    )
    src.execute(
        "INSERT INTO returns_credit_notes VALUES (6, 'CN006', 905, 8, 3, 200, '2026-04-25', "
        "1, 'CASE', 'RT02_DAMAGE_TRANSIT', 60, 'SCRAP', 'APPROVED')"
    )
    src.commit()
    src.close()

    path = tmp_path / "curated.db"
    build(source_db, path, steps=[s00_reference, s20_orders, s30_deliveries, s40_returns])
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def _measure(result, name):
    return next(m for m in result.measures if m.measure == name)


def _by_rule(measure):
    return {r.rule_ref: r.count for r in measure.by_rule}


def test_fill_rate_counts_order_lines_in_scope_and_what_excluded_them(conn):
    # FY27 Q1 lines: 1, 2, 7 (order 900), 3 (901), 4 (902: cancelled, and
    # outlet 3 closed before the period), 5 (903: outlet 4 soft-deleted),
    # 8 (905: outlet 3, closed, nothing else wrong with it).
    measure = _measure(exclusions.compute(conn, FY27_Q1, region_id=None), "fill_rate")
    assert measure.entity == "order lines"
    assert measure.in_scope_count == 7
    assert measure.included_count == 4
    assert measure.excluded_count == 3
    assert _by_rule(measure) == {"X1": 1, "X2": 0, "X3": 2, "X4": 1, "X5": 0}


def test_rule_counts_overlap_and_excluded_count_does_not_double_count(conn):
    """Line 4 is both cancelled (X4) and at a closed outlet (X3). It is one
    excluded line, counted under each rule that applies to it."""
    measure = _measure(exclusions.compute(conn, FY27_Q1, region_id=None), "fill_rate")
    assert sum(_by_rule(measure).values()) == 4
    assert measure.excluded_count == 3


def test_closed_outlet_is_retained_in_periods_starting_before_its_closure(conn):
    measure = _measure(exclusions.compute(conn, SPANNING, region_id=None), "fill_rate")
    assert _by_rule(measure)["X3"] == 0


def test_region_scope_narrows_every_count(conn):
    # South (region 2) has an outlet but no orders, deliveries or returns.
    result = exclusions.compute(conn, FY27_Q1, region_id=2)
    for name in ("fill_rate", "otif", "returns", "excursions"):
        measure = _measure(result, name)
        assert measure.in_scope_count == 0
        assert measure.excluded_count == 0


def test_otif_counts_deliveries_and_states_x4_is_structural(conn):
    # Deliveries planned in FY27 Q1: 1, 2, 3 (outlet 4, X1), 4, 5 (outlet 3, X3).
    measure = _measure(exclusions.compute(conn, FY27_Q1, region_id=None), "otif")
    assert measure.entity == "deliveries"
    assert measure.in_scope_count == 5
    assert measure.excluded_count == 2
    assert _by_rule(measure) == {"X1": 1, "X2": 0, "X3": 1, "X5": 0}
    assert "cancelled" in measure.note.lower()


def test_excursions_counts_only_chilled_deliveries(conn):
    # Chilled: 1, 2, 4, and 5 (X3). Delivery 3 is excluded but not chilled.
    measure = _measure(exclusions.compute(conn, FY27_Q1, region_id=None), "excursions")
    assert measure.entity == "chilled deliveries"
    assert measure.in_scope_count == 4
    assert measure.excluded_count == 1
    assert _by_rule(measure)["X1"] == 0


def test_returns_counts_credit_notes_by_return_date(conn):
    # All six credit notes fall in April; CN004 is at soft-deleted outlet 4,
    # CN006 at closed outlet 3.
    measure = _measure(exclusions.compute(conn, FY27_Q1, region_id=None), "returns")
    assert measure.entity == "credit notes"
    assert measure.in_scope_count == 6
    assert measure.excluded_count == 2
    assert _by_rule(measure) == {"X1": 1, "X2": 0, "X3": 1, "X5": 0}


def test_near_expiry_is_listed_with_no_rules_rather_than_left_out(conn):
    measure = _measure(exclusions.compute(conn, FY27_Q1, region_id=None), "near_expiry")
    assert measure.applies is False
    assert measure.in_scope_count is None
    assert measure.by_rule == []
    assert measure.note


def test_result_states_its_scope_and_period(conn):
    result = exclusions.compute(conn, FY27_Q1, region_id=1)
    assert result.scope == "West"
    assert result.period_label == "FY27 Q1"
    assert result.period_start == date(2026, 4, 1)


# --- Reconciliation against the metric implementations -------------------


def _fill_rate_rows(conn, period, include_excluded):
    return fill_rate.compute(conn, MetricRequest(
        grain=Grain.REGION, period_start=period.start, period_end=period.end,
        period_label=period.label, include_excluded=include_excluded,
    )).basis.source_row_count


def _otif_rows(conn, period, include_excluded):
    return otif.compute(conn, MetricRequest(
        grain=Grain.REGION, period_start=period.start, period_end=period.end,
        period_label=period.label, include_excluded=include_excluded, tolerance_minutes=30,
    )).basis.source_row_count


def _returns_rows(conn, period, include_excluded):
    return returns.compute(conn, ReturnsRequest(
        grain=ReturnsGrain.CATEGORY, period_start=period.start, period_end=period.end,
        period_label=period.label, include_excluded=include_excluded,
    )).basis.source_row_count


def _excursions_rows(conn, period, include_excluded):
    return excursions.compute(conn, ExcursionsRequest(
        grain=ExcursionsGrain.MONTH, period_start=period.start, period_end=period.end,
        period_label=period.label, include_excluded=include_excluded,
    )).basis.source_row_count


@pytest.mark.parametrize(
    ("name", "metric_rows"),
    [
        ("fill_rate", _fill_rate_rows),
        ("otif", _otif_rows),
        ("returns", _returns_rows),
        ("excursions", _excursions_rows),
    ],
)
@pytest.mark.parametrize("period", [FY27_Q1, SPANNING], ids=["fy27q1", "spanning"])
def test_counts_reconcile_with_the_metric_that_serves_the_dashboard(
    conn, name, metric_rows, period
):
    """If a metric's filters change and this module is not changed with
    them, the quality screen would misstate what the dashboard excludes."""
    measure = _measure(exclusions.compute(conn, period, region_id=None), name)
    assert measure.included_count == metric_rows(conn, period, include_excluded=False)
    assert measure.in_scope_count == metric_rows(conn, period, include_excluded=True)
