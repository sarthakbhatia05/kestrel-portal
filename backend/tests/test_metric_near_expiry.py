import sqlite3
from datetime import date

import pytest

from kestrel.metrics import near_expiry
from kestrel.metrics.types import NearExpiryGrain, NearExpiryRequest
from kestrel.transform.runner import build
from kestrel.transform.steps import s00_reference, s50_inventory


@pytest.fixture
def conn(tmp_path, source_db):
    path = tmp_path / "curated.db"
    build(source_db, path, steps=[s00_reference, s50_inventory])
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def _request(**overrides):
    defaults = dict(
        grain=NearExpiryGrain.CATEGORY,
        snapshot_date=date(2026, 6, 29),
        threshold_days=30,
    )
    return NearExpiryRequest(**{**defaults, **overrides})


def test_latest_snapshot_date_is_the_most_recent_one_present(conn):
    assert near_expiry.latest_snapshot_date(conn) == "2026-06-29"


def test_headline_rate_is_near_expiry_cases_over_total_available(conn):
    # Near-expiry (<=30 days): snapshot 1 (83, 11 days) + snapshot 3 (44, 6 days) = 127.
    # Total available: 83 + 180 + 44 = 307.
    result = near_expiry.compute(conn, _request())
    assert result.headline.near_expiry_cases == pytest.approx(127)
    assert result.headline.total_available_cases == pytest.approx(307)
    assert result.headline.near_expiry_rate == pytest.approx(127 / 307)


def test_headline_value_is_priced_off_the_product_master(conn):
    # snapshot 1: 83 cases * 12 case_pack * 100 = 99600
    # snapshot 3: 44 cases * 12 case_pack * 100 = 52800
    result = near_expiry.compute(conn, _request())
    assert result.headline.near_expiry_value_inr == pytest.approx(152400)


def test_basis_states_damaged_and_blocked_separately(conn):
    # damaged: snapshot1=5, snapshot3=1 -> 6 cases, value 6*12*100=7200
    # blocked: snapshot1=2 -> 2 cases, value 2*12*100=2400
    basis = near_expiry.compute(conn, _request()).basis
    assert basis.damaged_cases == pytest.approx(6)
    assert basis.damaged_value_inr == pytest.approx(7200)
    assert basis.blocked_cases == pytest.approx(2)
    assert basis.blocked_value_inr == pytest.approx(2400)


def test_prior_snapshot_is_excluded_from_the_latest_query(conn):
    """Snapshot 4 (2026-06-22) is a different week and must not be summed
    into the 2026-06-29 headline."""
    result = near_expiry.compute(conn, _request())
    assert result.basis.source_row_count == 3


def test_explicit_snapshot_date_reaches_the_prior_week(conn):
    result = near_expiry.compute(conn, _request(snapshot_date=date(2026, 6, 22)))
    assert result.basis.source_row_count == 1
    assert result.headline.near_expiry_cases == pytest.approx(85)


def test_threshold_days_is_configurable(conn):
    """At a 10-day threshold, snapshot 1 (11 days remaining) drops out but
    snapshot 3 (6 days remaining) stays -- proving the cutoff is applied at
    query time, not baked into the stored remaining_shelf_life_days."""
    result = near_expiry.compute(conn, _request(threshold_days=10))
    assert result.headline.near_expiry_cases == pytest.approx(44)


def test_category_grain_breaks_down_correctly(conn):
    result = near_expiry.compute(conn, _request(grain=NearExpiryGrain.CATEGORY))
    by_key = {row.key: row for row in result.rows}
    assert by_key["Snacks"].near_expiry_rate == pytest.approx(1.0)  # 127/127
    assert by_key["Beverages"].near_expiry_rate == pytest.approx(0.0)


def test_q_filters_rows_by_case_insensitive_label_substring(conn):
    result = near_expiry.compute(conn, _request(grain=NearExpiryGrain.CATEGORY, q="snack"))
    assert {row.key for row in result.rows} == {"Snacks"}


def test_warehouse_grain_breaks_down_correctly(conn):
    result = near_expiry.compute(conn, _request(grain=NearExpiryGrain.WAREHOUSE))
    by_key = {row.label: row for row in result.rows}
    assert by_key["West Hub"].near_expiry_rate == pytest.approx(83 / 263)
    assert by_key["South Hub"].near_expiry_rate == pytest.approx(1.0)


def test_national_scope_is_the_default(conn):
    assert near_expiry.compute(conn, _request()).basis.scope == "National"


def test_region_scope_narrows_the_result(conn):
    result = near_expiry.compute(conn, _request(region_id=2))
    assert result.basis.scope == "South"
    assert result.headline.near_expiry_cases == pytest.approx(44)
    assert result.headline.total_available_cases == pytest.approx(44)


def test_worst_category_first_when_descending(conn):
    result = near_expiry.compute(conn, _request(grain=NearExpiryGrain.CATEGORY))
    assert result.rows[0].key == "Snacks"  # higher rate (1.0) first


def test_limit_caps_the_breakdown(conn):
    result = near_expiry.compute(conn, _request(grain=NearExpiryGrain.CATEGORY, limit=1))
    assert len(result.rows) == 1
