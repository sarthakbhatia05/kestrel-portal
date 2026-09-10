from datetime import date

from kestrel.ask import guard
from kestrel.metrics.types import (
    MetricBasis,
    MetricResult,
    MetricRow,
    Unit,
)


def _result() -> MetricResult:
    return MetricResult(
        headline=0.9234,
        numerator=1108.0,
        denominator=1200.0,
        rows=[
            MetricRow(key="1", label="Good Mart", numerator=108.0,
                      denominator=120.0, value=0.9),
        ],
        basis=MetricBasis(
            metric="fill_rate",
            period_start=date(2026, 4, 1),
            period_end=date(2026, 6, 30),
            period_label="FY27 Q1",
            unit=Unit.EACHES,
            scope="National",
            exclusions_applied=["X1"],
            source_row_count=7,
        ),
    )


def test_prose_with_no_numbers_passes():
    assert guard.check("Fill rate held broadly steady across outlets.", _result())


def test_headline_as_a_percentage_passes():
    assert guard.check("Fill rate was 92.3% for the quarter.", _result())


def test_raw_totals_pass():
    assert guard.check("1108 of 1200 eaches were delivered.", _result())


def test_thousands_separator_passes():
    assert guard.check("1,200 eaches were ordered.", _result())


def test_row_figures_pass():
    assert guard.check("Good Mart came in at 90%.", _result())


def test_period_label_digits_pass():
    assert guard.check("FY27 Q1 fill rate was 92.34%.", _result())


def test_an_invented_figure_fails():
    assert not guard.check("Fill rate was 87.5% for the quarter.", _result())


def test_an_invented_count_fails():
    assert not guard.check("Some 42 outlets missed target.", _result())


def test_precision_beyond_the_result_fails():
    # 92.3416% was never computed; the headline rounds to 92.34%.
    assert not guard.check("Fill rate was 92.3416%.", _result())


def test_apply_returns_prose_when_it_passes():
    assert guard.apply("Fill rate was 92.3%.", _result()) == "Fill rate was 92.3%."


def test_apply_drops_prose_when_it_fails():
    assert guard.apply("Fill rate was 87.5%.", _result()) is None


def test_the_magnitude_of_a_negative_figure_is_quotable():
    """A drop is stored as a negative delta, and English states its size:
    "fell 0.41 points", not "changed by -0.41 points". Rejecting that would
    drop the explanation of every decline -- the case the loop exists for."""
    assert guard.check("Fill rate fell 0.41 percentage points.", {"delta": -0.0041})


def test_a_magnitude_that_matches_nothing_is_still_rejected():
    assert not guard.check("Fill rate fell 9.90 percentage points.", {"delta": -0.0041})
