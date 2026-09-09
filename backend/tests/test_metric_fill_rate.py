import sqlite3

import pytest

from kestrel.metrics import fill_rate
from kestrel.metrics.types import Grain, MetricRequest, Unit
from kestrel.transform.runner import build
from kestrel.transform.steps import s00_reference, s20_orders


@pytest.fixture
def conn(tmp_path, source_db):
    path = tmp_path / "curated.db"
    build(source_db, path, steps=[s00_reference, s20_orders])
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def _request(**overrides):
    defaults = dict(
        grain=Grain.OUTLET,
        period_start="2026-04-01",
        period_end="2026-06-30",
        period_label="FY27 Q1",
    )
    return MetricRequest(**{**defaults, **overrides})


def test_headline_is_delivered_over_ordered_in_eaches(conn):
    # Included lines in the period: line 1 (120/108), line 2 (50/50),
    # line 3 (120/60), line 7 (12/12). Lines 4, 5 and 6 are excluded.
    result = fill_rate.compute(conn, _request())
    assert result.basis.unit == Unit.EACHES
    assert result.headline == pytest.approx((108 + 50 + 60 + 12) / (120 + 50 + 120 + 12))


def test_result_carries_the_raw_totals_behind_the_headline(conn):
    result = fill_rate.compute(conn, _request())
    assert result.numerator == pytest.approx(108 + 50 + 60 + 12)
    assert result.denominator == pytest.approx(120 + 50 + 120 + 12)


def test_cancelled_and_deleted_and_out_of_period_lines_are_absent(conn):
    result = fill_rate.compute(conn, _request())
    keys = {row.key for row in result.rows}
    assert keys == {"1", "2"}


def test_include_excluded_lifts_the_default_filter(conn):
    """PRD 6.3: exclusions are reversible on request, not a rebuild."""
    default = fill_rate.compute(conn, _request())
    lifted = fill_rate.compute(conn, _request(include_excluded=True))
    assert lifted.basis.source_row_count > default.basis.source_row_count
    assert lifted.basis.exclusions_applied == []


def test_case_unit_is_derived_from_the_each_figure(conn):
    result = fill_rate.compute(conn, _request(unit=Unit.CASES))
    expected = (108 / 12 + 50 / 6 + 60 / 6 + 12 / 12) / (
        120 / 12 + 50 / 6 + 120 / 6 + 12 / 12
    )
    assert result.headline == pytest.approx(expected)
    assert result.basis.unit == Unit.CASES


def test_region_scope_narrows_the_result_and_is_named_in_the_basis(conn):
    result = fill_rate.compute(conn, _request(region_id=2))
    assert result.basis.scope == "South"
    assert result.rows == []


def test_national_scope_is_the_default(conn):
    assert fill_rate.compute(conn, _request()).basis.scope == "National"


def test_basis_names_every_exclusion_rule_applied(conn):
    basis = fill_rate.compute(conn, _request()).basis
    assert basis.exclusions_applied == ["X1", "X2", "X3", "X4", "X5"]
    assert basis.metric == "fill_rate"
    assert basis.period_label == "FY27 Q1"


def test_ascending_limit_returns_the_worst_performers(conn):
    result = fill_rate.compute(conn, _request(ascending=True, limit=1))
    assert len(result.rows) == 1
    # Outlet 2 delivered 60 of 120; outlet 1 delivered 170 of 182.
    assert result.rows[0].key == "2"


def test_headline_is_none_when_nothing_matches(conn):
    result = fill_rate.compute(conn, _request(region_id=2))
    assert result.headline is None


def test_closed_outlet_is_excluded_from_a_period_after_its_closure(conn):
    """X3 is period-scoped: outlet 3 closed on 2025-06-30."""
    result = fill_rate.compute(conn, _request())
    assert "3" not in {row.key for row in result.rows}


def test_q_filters_rows_by_case_insensitive_label_substring(conn):
    result = fill_rate.compute(conn, _request(q="good"))
    assert {row.key for row in result.rows} == {"1"}


def test_q_does_not_change_the_headline(conn):
    default = fill_rate.compute(conn, _request())
    searched = fill_rate.compute(conn, _request(q="good"))
    assert searched.headline == default.headline
