import sqlite3

import pytest

from kestrel.ask import answer, dispatch, guard, resolver
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


def _answer(curated, intent):
    result = dispatch.run(curated, intent)
    return answer.compose(result, intent.limit), result


def test_fill_rate_answer_states_period_scope_unit_and_exclusions(curated):
    text, _ = _answer(
        curated,
        AskIntent(metric=AskMetric.FILL_RATE, grain=AskGrain.OUTLET, period="FY27Q1"),
    )
    assert "Fill rate was" in text
    assert "FY27 Q1" in text
    assert "National" in text
    assert "eaches" in text
    assert "Exclusions applied: X1" in text


def test_otif_answer_states_the_tolerance_and_the_unmeasured(curated):
    text, _ = _answer(
        curated,
        AskIntent(metric=AskMetric.OTIF, grain=AskGrain.REGION, period="FY27Q1"),
    )
    assert "30-minute on-time tolerance" in text
    assert "could not be measured" in text


def test_returns_answer_states_pending_and_rejected(curated):
    text, _ = _answer(
        curated, AskIntent(metric=AskMetric.RETURNS, period="FY27Q1")
    )
    assert "pending" in text and "rejected" in text
    assert "INR" in text


def test_near_expiry_answer_states_the_snapshot_and_threshold(curated):
    text, _ = _answer(
        curated, AskIntent(metric=AskMetric.NEAR_EXPIRY, grain=AskGrain.WAREHOUSE)
    )
    assert "2026-06-29 snapshot" in text
    assert "within 30 days of expiry" in text


def test_excursions_answer_states_the_counts(curated):
    text, _ = _answer(
        curated, AskIntent(metric=AskMetric.EXCURSIONS, period="FY27Q1")
    )
    assert "Temperature excursions ran at" in text
    assert "chilled deliveries" in text


def test_a_ranking_question_is_answered_with_the_ranking(curated):
    text, _ = _answer(
        curated,
        AskIntent(metric=AskMetric.FILL_RATE, grain=AskGrain.OUTLET,
                  period="FY27Q1", limit=2, ascending=True),
    )
    assert "Breakdown:" in text


@pytest.mark.parametrize(
    "intent",
    [
        AskIntent(metric=AskMetric.FILL_RATE, grain=AskGrain.OUTLET, period="FY27Q1", limit=2),
        AskIntent(metric=AskMetric.OTIF, grain=AskGrain.REGION, period="FY27Q1", limit=2),
        AskIntent(metric=AskMetric.RETURNS, period="FY27Q1", limit=2),
        AskIntent(metric=AskMetric.NEAR_EXPIRY, grain=AskGrain.WAREHOUSE, limit=2),
        AskIntent(metric=AskMetric.EXCURSIONS, period="FY27Q1", limit=2),
    ],
)
def test_every_figure_in_the_answer_traces_back_to_the_result(curated, intent):
    """The answer of record must itself pass the guard applied to prose.

    If it does not, the answer is quoting a number the result does not
    contain -- which is the failure C4.4 is about, arriving by a different
    door.
    """
    text, result = _answer(curated, intent)
    assert guard.check(text, result)


def test_the_decline_names_what_is_supported():
    text = answer.decline(resolver.SUPPORTED_METRICS)
    assert "cannot answer" in text
    assert "fill rate" in text
    assert "temperature excursions" in text
