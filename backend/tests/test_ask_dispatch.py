import sqlite3
from datetime import date

import pytest

from kestrel import dependencies
from kestrel.ask import dispatch
from kestrel.ask.types import AskGrain, AskIntent, AskMetric
from kestrel.transform.runner import build
from kestrel.transform.steps import (
    s00_reference,
    s20_orders,
    s30_deliveries,
    s40_returns,
    s50_inventory,
)


@pytest.fixture
def curated(tmp_path, source_db):
    path = tmp_path / "curated.db"
    build(
        source_db, path,
        steps=[s00_reference, s20_orders, s30_deliveries, s40_returns, s50_inventory],
    )
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def test_fill_rate_intent_reaches_the_canonical_metric(curated):
    result = dispatch.run(
        curated,
        AskIntent(metric=AskMetric.FILL_RATE, grain=AskGrain.OUTLET, period="FY27Q1"),
    )
    assert result.basis.metric == "fill_rate"
    assert result.basis.period_label == "FY27 Q1"
    assert 0 < result.headline < 1


def test_latest_in_a_question_resolves_against_the_data(curated, monkeypatch):
    """Ask-anything and the dashboard must agree on what 'latest' means."""
    monkeypatch.setattr(dependencies, "_today", lambda: date(2027, 1, 15))
    result = dispatch.run(
        curated,
        AskIntent(metric=AskMetric.FILL_RATE, grain=AskGrain.OUTLET, period="latest"),
    )
    assert result.basis.period_label == "FY27 Q1"


def test_a_missing_grain_falls_back_to_the_metrics_default(curated):
    result = dispatch.run(curated, AskIntent(metric=AskMetric.RETURNS, period="FY27Q1"))
    assert result.basis.metric == "returns"


def test_near_expiry_uses_the_latest_snapshot_not_a_period(curated):
    result = dispatch.run(
        curated, AskIntent(metric=AskMetric.NEAR_EXPIRY, grain=AskGrain.WAREHOUSE)
    )
    assert str(result.basis.snapshot_date) == "2026-06-29"


def test_otif_states_the_tolerance_that_produced_it(curated):
    result = dispatch.run(
        curated, AskIntent(metric=AskMetric.OTIF, grain=AskGrain.REGION, period="FY27Q1")
    )
    assert result.basis.tolerance_minutes == 30


def test_excursions_defaults_to_a_monthly_breakdown(curated):
    result = dispatch.run(
        curated, AskIntent(metric=AskMetric.EXCURSIONS, period="FY27Q1")
    )
    assert result.basis.metric == "excursions"


def test_a_grain_the_metric_does_not_support_is_unanswerable(curated):
    with pytest.raises(dispatch.Unanswerable):
        dispatch.run(
            curated, AskIntent(metric=AskMetric.RETURNS, grain=AskGrain.OUTLET)
        )


def test_an_unsupported_intent_never_reaches_a_metric(curated):
    with pytest.raises(dispatch.Unanswerable):
        dispatch.run(curated, AskIntent(metric=AskMetric.UNSUPPORTED))


def test_the_region_filter_is_carried_into_the_basis(curated):
    result = dispatch.run(
        curated,
        AskIntent(metric=AskMetric.FILL_RATE, grain=AskGrain.OUTLET,
                  period="FY27Q1", region_id=1),
    )
    assert result.basis.scope != "National"
