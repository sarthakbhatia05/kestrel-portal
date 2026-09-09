import sqlite3

import pytest

from kestrel.metrics import otif
from kestrel.metrics.types import Grain, MetricRequest
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
        grain=Grain.OUTLET,
        period_start="2026-04-01",
        period_end="2026-06-30",
        period_label="FY27 Q1",
        tolerance_minutes=30,
    )
    return MetricRequest(**{**defaults, **overrides})


def test_headline_counts_due_on_time_in_full_and_otif(conn):
    # Due: deliveries 1 (outlet 1), 2 (outlet 2), 4 (outlet 1). Delivery 3
    # (outlet 4) is excluded by default (X1).
    # On time (<=30 min): delivery 1 only (30 min, exactly on the boundary).
    # In full: delivery 4 only (order 904's line is fully delivered).
    # OTIF (both): none.
    result = otif.compute(conn, _request())
    assert result.headline.due_count == 3
    assert result.headline.on_time_count == 1
    assert result.headline.in_full_count == 1
    assert result.headline.otif_count == 0
    assert result.headline.on_time_rate == pytest.approx(1 / 3)
    assert result.headline.in_full_rate == pytest.approx(1 / 3)
    assert result.headline.otif == pytest.approx(0.0)


def test_unmeasured_deliveries_are_counted_not_dropped(conn):
    """Delivery 4's actual_arrival is unparseable -> unmeasured, PRD 5.3."""
    basis = otif.compute(conn, _request()).basis
    assert basis.unmeasured_count == 1
    assert basis.source_row_count == 3


def test_tolerance_boundary_is_inclusive(conn):
    """Delivery 1 is exactly 30 min late."""
    at_boundary = otif.compute(conn, _request(tolerance_minutes=30))
    assert at_boundary.headline.on_time_count == 1

    below_boundary = otif.compute(conn, _request(tolerance_minutes=29))
    assert below_boundary.headline.on_time_count == 0


def test_source_delay_minutes_column_is_ignored(conn):
    """Delivery 1's source delay_minutes says 0 (would be on time at any
    tolerance); the real, computed delay is 30. Confirms the metric reads
    the transform's computed value, not the untrustworthy source column."""
    result = otif.compute(conn, _request(tolerance_minutes=1))
    assert result.headline.on_time_count == 0


def test_outlet_grain_breaks_down_by_outlet(conn):
    result = otif.compute(conn, _request())
    by_key = {row.key: row for row in result.rows}
    assert by_key["1"].due_count == 2  # deliveries 1 and 4
    assert by_key["1"].on_time_count == 1
    assert by_key["1"].in_full_count == 1
    assert by_key["2"].due_count == 1  # delivery 2
    assert by_key["2"].on_time_count == 0


def test_include_excluded_surfaces_the_soft_deleted_outlet(conn):
    default = otif.compute(conn, _request())
    assert "4" not in {row.key for row in default.rows}

    lifted = otif.compute(conn, _request(include_excluded=True))
    row = next(r for r in lifted.rows if r.key == "4")
    assert row.due_count == 1
    assert row.otif == pytest.approx(1.0)
    assert lifted.basis.exclusions_applied == []


def test_national_scope_is_the_default(conn):
    assert otif.compute(conn, _request()).basis.scope == "National"


def test_region_scope_narrows_the_result(conn):
    result = otif.compute(conn, _request(region_id=2))
    assert result.basis.scope == "South"
    assert result.rows == []
    assert result.headline.due_count == 0
    assert result.headline.otif is None


def test_basis_states_the_tolerance_used(conn):
    basis = otif.compute(conn, _request(tolerance_minutes=45)).basis
    assert basis.tolerance_minutes == 45
    assert basis.metric == "otif"
