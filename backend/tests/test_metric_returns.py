import sqlite3

import pytest

from kestrel.metrics import returns
from kestrel.metrics.types import ReturnsGrain, ReturnsRequest
from kestrel.transform.runner import build
from kestrel.transform.steps import s00_reference, s20_orders, s40_returns


@pytest.fixture
def conn(tmp_path, source_db):
    path = tmp_path / "curated.db"
    build(source_db, path, steps=[s00_reference, s20_orders, s40_returns])
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def _request(**overrides):
    defaults = dict(
        grain=ReturnsGrain.CATEGORY,
        period_start="2026-04-01",
        period_end="2026-06-30",
        period_label="FY27 Q1",
    )
    return ReturnsRequest(**{**defaults, **overrides})


def test_headline_rate_uses_approved_credit_over_dispatch_value(conn):
    # Approved & included: CN001 (200) + CN002 (50) = 250.
    # Dispatch (not excluded, in period): 900+500+500+100 = 2000.
    result = returns.compute(conn, _request())
    assert result.headline.credit_note_value_inr == pytest.approx(250)
    assert result.headline.dispatch_value_inr == pytest.approx(2000)
    assert result.headline.returns_rate == pytest.approx(250 / 2000)


def test_rejected_and_pending_credit_notes_are_excluded_from_the_rate(conn):
    """CN003 is PENDING and CN005 is REJECTED -- neither resulted in an
    actual credit, so neither counts as leakage."""
    basis = returns.compute(conn, _request()).basis
    assert basis.pending_count == 1
    assert basis.pending_value_inr == pytest.approx(75)
    assert basis.rejected_count == 1
    assert basis.rejected_value_inr == pytest.approx(100)


def test_cold_chain_attributable_returns_are_isolated(conn):
    """Only CN002 (RT01, APPROVED) counts -- CN003 (RT06) is PENDING."""
    headline = returns.compute(conn, _request()).headline
    assert headline.cold_chain_value_inr == pytest.approx(50)
    assert headline.cold_chain_rate == pytest.approx(50 / 2000)


def test_excluded_outlet_return_is_left_out_by_default(conn):
    """CN004 is against outlet 4 (soft-deleted, X1)."""
    default = returns.compute(conn, _request())
    assert default.headline.credit_note_value_inr == pytest.approx(250)

    lifted = returns.compute(conn, _request(include_excluded=True))
    assert lifted.headline.credit_note_value_inr == pytest.approx(350)
    assert lifted.headline.dispatch_value_inr == pytest.approx(2500)
    assert lifted.basis.exclusions_applied == []


def test_category_grain_breaks_down_correctly(conn):
    result = returns.compute(conn, _request(grain=ReturnsGrain.CATEGORY))
    by_key = {row.key: row for row in result.rows}
    assert by_key["Snacks"].credit_note_value_inr == pytest.approx(200)
    assert by_key["Snacks"].dispatch_value_inr == pytest.approx(1000)  # lines 1, 7
    assert by_key["Snacks"].returns_rate == pytest.approx(0.2)
    assert by_key["Beverages"].credit_note_value_inr == pytest.approx(50)
    assert by_key["Beverages"].dispatch_value_inr == pytest.approx(1000)  # lines 2, 3
    assert by_key["Beverages"].returns_rate == pytest.approx(0.05)


def test_q_filters_rows_by_case_insensitive_label_substring(conn):
    result = returns.compute(conn, _request(grain=ReturnsGrain.CATEGORY, q="snack"))
    assert {row.key for row in result.rows} == {"Snacks"}


def test_reason_grain_divides_by_the_scope_total_dispatch_value(conn):
    """Reason has no dispatch-side equivalent, so every reason row divides
    by the whole scope's dispatch value (2000), not a per-reason slice."""
    result = returns.compute(conn, _request(grain=ReturnsGrain.REASON))
    by_key = {row.key: row for row in result.rows}
    assert by_key["RT05_OVERSUPPLY"].dispatch_value_inr == pytest.approx(2000)
    assert by_key["RT05_OVERSUPPLY"].returns_rate == pytest.approx(200 / 2000)
    assert by_key["RT01_NEAR_EXPIRY"].returns_rate == pytest.approx(50 / 2000)


def test_national_scope_is_the_default(conn):
    assert returns.compute(conn, _request()).basis.scope == "National"


def test_region_scope_narrows_the_result(conn):
    result = returns.compute(conn, _request(region_id=2))
    assert result.basis.scope == "South"
    assert result.headline.credit_note_value_inr == 0
    assert result.headline.returns_rate is None


def test_worst_category_first_when_descending(conn):
    result = returns.compute(conn, _request(grain=ReturnsGrain.CATEGORY, ascending=False))
    assert result.rows[0].key == "Snacks"  # higher rate (0.2) first


def test_limit_caps_the_breakdown(conn):
    result = returns.compute(conn, _request(grain=ReturnsGrain.CATEGORY, limit=1))
    assert len(result.rows) == 1
