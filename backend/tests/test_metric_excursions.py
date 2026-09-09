import sqlite3

import pytest

from kestrel.metrics import excursions
from kestrel.metrics.types import ExcursionsGrain, ExcursionsRequest
from kestrel.transform.runner import build
from kestrel.transform.steps import s00_reference, s20_orders, s30_deliveries


@pytest.fixture
def conn(tmp_path, source_db):
    path = tmp_path / "curated.db"
    build(source_db, path, steps=[s00_reference, s20_orders, s30_deliveries])
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def _request(**overrides):
    defaults = dict(
        grain=ExcursionsGrain.MONTH,
        period_start="2026-04-01",
        period_end="2026-06-30",
        period_label="FY27 Q1",
    )
    return ExcursionsRequest(**{**defaults, **overrides})


def test_headline_counts_only_chilled_deliveries(conn):
    # Chilled and in period: deliveries 1, 2, 4. Delivery 3 (order 903)
    # carries only product 100, which is not chilled, and is also excluded
    # (outlet 4, X1).
    result = excursions.compute(conn, _request())
    assert result.headline.chilled_count == 3
    assert result.headline.excursion_count == 2  # deliveries 1 and 4
    assert result.headline.excursion_rate == pytest.approx(2 / 3)


def test_non_chilled_deliveries_never_reach_the_denominator(conn):
    """Delivery 3's breach flag would change the rate if it were counted;
    it isn't, because its order carries no chilled product."""
    result = excursions.compute(conn, _request(include_excluded=True))
    assert result.headline.chilled_count == 3  # unchanged: delivery 3 is not chilled


def test_excluded_outlet_delivery_is_left_out_by_default(conn):
    """Delivery 3 is chilled=0 regardless, but confirms the exclusion filter
    still applies to chilled deliveries the way OTIF's does."""
    default = excursions.compute(conn, _request())
    lifted = excursions.compute(conn, _request(include_excluded=True))
    assert lifted.basis.exclusions_applied == []
    assert default.basis.exclusions_applied == ["X1", "X2", "X3", "X4", "X5"]


def test_month_grain_breaks_down_by_calendar_month(conn):
    """Delivery 4 (order 904) is chilled and breached, planned in May --
    a distinct bucket from the other two chilled deliveries' April."""
    result = excursions.compute(conn, _request(grain=ExcursionsGrain.MONTH))
    by_key = {row.key: row for row in result.rows}
    assert by_key["2026-04"].chilled_count == 2  # deliveries 1, 2
    assert by_key["2026-04"].excursion_count == 1  # delivery 1
    assert by_key["2026-05"].chilled_count == 1  # delivery 4
    assert by_key["2026-05"].excursion_count == 1


def test_route_grain_breaks_down_by_route_with_names(conn):
    result = excursions.compute(conn, _request(grain=ExcursionsGrain.ROUTE))
    by_key = {row.key: row for row in result.rows}
    assert by_key["10"].label == "West Loop A"
    assert by_key["10"].chilled_count == 2  # deliveries 1, 4
    assert by_key["10"].excursion_count == 2
    assert by_key["11"].label == "West Loop B"
    assert by_key["11"].chilled_count == 1  # delivery 2
    assert by_key["11"].excursion_count == 0
    assert by_key["11"].excursion_rate == pytest.approx(0.0)


def test_warehouse_grain_breaks_down_by_warehouse(conn):
    result = excursions.compute(conn, _request(grain=ExcursionsGrain.WAREHOUSE))
    by_key = {row.key: row for row in result.rows}
    assert by_key["1"].label == "West Hub"
    assert by_key["1"].chilled_count == 3


def test_national_scope_is_the_default(conn):
    assert excursions.compute(conn, _request()).basis.scope == "National"


def test_region_scope_narrows_the_result(conn):
    result = excursions.compute(conn, _request(region_id=2))
    assert result.basis.scope == "South"
    assert result.headline.chilled_count == 0
    assert result.headline.excursion_rate is None


def test_q_filters_rows_by_case_insensitive_label_substring(conn):
    result = excursions.compute(conn, _request(grain=ExcursionsGrain.ROUTE, q="loop b"))
    assert {row.key for row in result.rows} == {"11"}


def test_worst_route_first_when_descending(conn):
    result = excursions.compute(
        conn, _request(grain=ExcursionsGrain.ROUTE, ascending=False)
    )
    assert result.rows[0].key == "10"  # higher rate (2/3) first


def test_limit_caps_the_breakdown(conn):
    result = excursions.compute(conn, _request(grain=ExcursionsGrain.ROUTE, limit=1))
    assert len(result.rows) == 1
