"""The investigation loop.

The model chooses each query having seen the result of the last one, which
is what makes "the drop concentrates in three outlets -- now show me those
outlets' OTIF" possible. Every figure still comes from the same metric
implementations the dashboard uses; the model picks which of them to run.
"""

import sqlite3

import pytest

from kestrel.ask import investigate
from kestrel.ask.catalogue import Catalogue, RegionEntry
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


@pytest.fixture
def catalogue():
    return Catalogue(
        regions=[RegionEntry(region_id=1, region_name="West")],
        warehouses=["West Hub"],
        categories=["Snacks"],
        return_reasons=["RT05_OVERSUPPLY"],
    )


class ScriptedModel:
    """Returns the next scripted step each time it is asked for one."""

    def __init__(self, steps, text="Fill rate fell."):
        self.steps = list(steps)
        self.text = text
        self.prompts = []
        self.systems = []

    def generate_json(self, *, system, prompt, schema):
        self.prompts.append(prompt)
        self.systems.append(system)
        if not self.steps:
            return {"done": True, "reasoning": "out of script"}
        return self.steps.pop(0)

    def generate_text(self, *, system, prompt):
        self.prompts.append(prompt)
        return self.text


FILL_RATE_Q1 = {
    "reasoning": "Measure fill rate for the quarter asked about.",
    "intent": {"metric": "fill_rate", "grain": "outlet", "period": "FY27Q1", "region_id": 1},
}
FILL_RATE_Q4 = {
    "reasoning": "Compare against the preceding quarter.",
    "intent": {"metric": "fill_rate", "grain": "outlet", "period": "FY26Q4", "region_id": 1},
}
DONE = {"reasoning": "Enough to answer.", "done": True}


def headline_pct(result):
    return f"{investigate.headline_rate(result) * 100:.1f}"


def test_runs_the_query_the_model_asks_for(curated, catalogue):
    model = ScriptedModel([FILL_RATE_Q1, DONE])
    records = list(investigate.investigate(model, curated, "how is fill rate?", catalogue))
    assert len(records) == 1
    assert records[0].result.basis.metric == "fill_rate"
    assert records[0].result.basis.period_label == "FY27 Q1"


def test_carries_the_models_reasoning_so_the_trail_is_readable(curated, catalogue):
    model = ScriptedModel([FILL_RATE_Q1, DONE])
    records = list(investigate.investigate(model, curated, "how is fill rate?", catalogue))
    assert records[0].reasoning == "Measure fill rate for the quarter asked about."


def test_stops_when_the_model_says_it_is_done(curated, catalogue):
    model = ScriptedModel([FILL_RATE_Q1, DONE, FILL_RATE_Q4])
    records = list(investigate.investigate(model, curated, "q", catalogue))
    assert len(records) == 1


def test_stops_at_the_cap_when_the_model_never_says_done(curated, catalogue):
    """A model that keeps asking for one more query must not run forever."""
    distinct = [
        {"reasoning": f"Measurement {n}.",
         "intent": {"metric": "fill_rate", "grain": "outlet", "period": "FY27Q1",
                    "limit": n}}
        for n in range(1, 21)
    ]
    records = list(
        investigate.investigate(ScriptedModel(distinct), curated, "q", catalogue, max_steps=3)
    )
    assert len(records) == 3


def test_an_impossible_step_is_recorded_and_the_loop_continues(curated, catalogue):
    """returns has no outlet grain. The model is told, and gets another go."""
    bad = {
        "reasoning": "Break returns down by outlet.",
        "intent": {"metric": "returns", "grain": "outlet", "period": "FY27Q1"},
    }
    model = ScriptedModel([bad, FILL_RATE_Q1, DONE])
    records = list(investigate.investigate(model, curated, "q", catalogue))
    assert records[0].error is not None
    assert records[0].result is None
    assert records[1].result is not None


def test_each_step_sees_what_the_earlier_steps_found(curated, catalogue):
    """The whole point of a loop rather than a plan: step 2 can react."""
    model = ScriptedModel([FILL_RATE_Q1, FILL_RATE_Q4, DONE])
    list(investigate.investigate(model, curated, "why did fill rate drop?", catalogue))
    assert "Fill rate was" in model.prompts[1]


def test_the_scope_period_fills_a_gap_the_question_leaves(curated, catalogue):
    """C5.3: the dashboard's selected period reaches ask-anything too."""
    no_period = {
        "reasoning": "Measure fill rate.",
        "intent": {"metric": "fill_rate", "grain": "outlet", "period": "latest"},
    }
    model = ScriptedModel([no_period, DONE])
    records = list(
        investigate.investigate(
            model, curated, "how is fill rate?", catalogue, scope_period="FY26Q4"
        )
    )
    assert records[0].result.basis.period_label == "FY26 Q4"


def test_a_period_named_in_the_question_beats_the_dashboard_scope(curated, catalogue):
    model = ScriptedModel([FILL_RATE_Q1, DONE])
    records = list(
        investigate.investigate(
            model, curated, "fill rate in FY27 Q1?", catalogue, scope_period="FY26Q4"
        )
    )
    assert records[0].result.basis.period_label == "FY27 Q1"


def test_comparing_the_same_metric_across_periods_computes_the_delta(curated, catalogue):
    """We compute the change, not the model.

    Without this the model has no legitimate way to say "fell 2.3 points":
    the number is in neither result, so the guard would drop the sentence.
    """
    model = ScriptedModel([FILL_RATE_Q1, FILL_RATE_Q4, DONE])
    records = list(investigate.investigate(model, curated, "why the drop?", catalogue))
    q1, q4 = records
    assert q1.delta is None
    # Measured FY27 Q1 first, FY26 Q4 second -- but the change runs
    # forwards in time, from Q4 to Q1, whichever order they were taken in.
    assert q4.delta == pytest.approx(
        investigate.headline_rate(q1.result) - investigate.headline_rate(q4.result)
    )


def test_no_delta_across_different_metrics(curated, catalogue):
    """OTIF minus fill rate is not a number that means anything."""
    otif = {
        "reasoning": "Check OTIF.",
        "intent": {"metric": "otif", "grain": "outlet", "period": "FY27Q1"},
    }
    model = ScriptedModel([FILL_RATE_Q1, otif, DONE])
    records = list(investigate.investigate(model, curated, "q", catalogue))
    assert records[1].delta is None


def test_the_answer_of_record_states_every_step(curated, catalogue):
    model = ScriptedModel([FILL_RATE_Q1, FILL_RATE_Q4, DONE])
    result = investigate.run(model, curated, "why did fill rate drop?", catalogue)
    assert "FY27 Q1" in result.answer
    assert "FY26 Q4" in result.answer


def test_prose_may_quote_a_figure_from_any_step(curated, catalogue):
    """The guard's allowed set is everything the model was actually shown."""
    model = ScriptedModel([FILL_RATE_Q1, DONE])
    records = list(investigate.investigate(model, curated, "q", catalogue))
    model.text = f"Fill rate was {headline_pct(records[0].result)}% for the quarter."
    assert investigate.conclude(model, "q", records) is not None


def test_prose_inventing_a_figure_is_dropped(curated, catalogue):
    model = ScriptedModel([FILL_RATE_Q1, DONE])
    records = list(investigate.investigate(model, curated, "q", catalogue))
    model.text = "Fill rate collapsed to 3.7% because the depot flooded."
    assert investigate.conclude(model, "q", records) is None


def test_an_investigation_with_no_usable_step_declines(curated, catalogue):
    """Nothing was measured, so there is nothing to explain."""
    bad = {
        "reasoning": "Break returns down by outlet.",
        "intent": {"metric": "returns", "grain": "outlet", "period": "FY27Q1"},
    }
    model = ScriptedModel([bad, DONE])
    result = investigate.run(model, curated, "q", catalogue)
    assert result.explanation is None
    assert result.declined is True


def test_a_number_the_model_wrote_in_its_own_reasoning_is_not_quotable(curated, catalogue):
    """The guard's allowed set must be figures we computed, not text the
    model authored. Otherwise it can write a number into its reasoning on
    one step and quote it as a finding on the next."""
    laundering = {
        "reasoning": "Checking whether the 3.7% collapse is real.",
        "intent": {"metric": "fill_rate", "grain": "outlet", "period": "FY27Q1"},
    }
    model = ScriptedModel([laundering, DONE])
    records = list(investigate.investigate(model, curated, "q", catalogue))
    model.text = "Fill rate collapsed to 3.7%."
    assert investigate.conclude(model, "q", records) is None


def test_the_same_measurement_is_never_taken_twice(curated, catalogue):
    """A model that repeats itself burns the step budget.

    Seen live: three identical quarter-wide queries before the model
    worked out it wanted a week, leaving three steps for the actual
    analysis.
    """
    model = ScriptedModel([FILL_RATE_Q1, FILL_RATE_Q1, FILL_RATE_Q1, FILL_RATE_Q4, DONE])
    records = list(investigate.investigate(model, curated, "q", catalogue))
    periods = [record.intent.period for record in records]
    assert periods == ["FY27Q1", "FY26Q4"]


def test_a_repeat_tells_the_model_it_already_has_that_measurement(curated, catalogue):
    model = ScriptedModel([FILL_RATE_Q1, FILL_RATE_Q1, DONE])
    list(investigate.investigate(model, curated, "q", catalogue))
    assert "already" in model.prompts[-1].lower()


def test_the_model_is_told_what_the_data_actually_covers(curated, catalogue):
    """Live, the model read 'last week' as the latest quarter, because
    nothing told it when the data ends."""
    model = ScriptedModel([DONE])
    list(investigate.investigate(model, curated, "why did fill rate drop last week?", catalogue))
    assert "2026-05-01" in model.systems[0]


def test_the_coverage_note_names_the_last_complete_week_not_a_partial_one(curated, catalogue):
    """The fixture's orders end Friday 1 May 2026, so that week (W18) is
    part-covered. Offering it as "last week" invites a comparison of two
    days against seven -- which a live run duly made. The codebase already
    excludes the in-progress quarter for exactly this reason."""
    model = ScriptedModel([DONE])
    list(investigate.investigate(model, curated, "why did fill rate drop last week?", catalogue))
    assert "2026-W17" in model.systems[0]
    assert "2026-W18" not in model.systems[0]


def test_the_coverage_note_keeps_a_month_that_ends_on_its_last_day():
    """April 2026 ends on the 30th, so it is complete and quotable."""
    assert "2026-04" in investigate._coverage(("2025-01-01", "2026-04-30"))


def test_the_coverage_note_steps_back_from_a_part_covered_month():
    assert "2026-03" in investigate._coverage(("2025-01-01", "2026-04-15"))


def test_the_delta_is_oriented_by_time_not_by_step_order(curated, catalogue):
    """A change runs from the earlier period to the later one.

    The model often measures the recent period first and its baseline
    second. Subtracting in step order then reports a rise as a fall --
    seen live, where "86.0% vs 85.9%" was explained as "a drop".
    """
    forwards = ScriptedModel([FILL_RATE_Q4, FILL_RATE_Q1, DONE])
    backwards = ScriptedModel([FILL_RATE_Q1, FILL_RATE_Q4, DONE])
    a = list(investigate.investigate(forwards, curated, "q", catalogue))
    b = list(investigate.investigate(backwards, curated, "q", catalogue))
    assert a[1].delta == pytest.approx(b[1].delta)


def test_the_delta_states_which_period_moved_to_which(curated, catalogue):
    """A bare number cannot say which way round the comparison ran."""
    model = ScriptedModel([FILL_RATE_Q1, FILL_RATE_Q4, DONE])
    records = list(investigate.investigate(model, curated, "q", catalogue))
    assert records[1].delta_basis == "FY26 Q4 to FY27 Q1"
