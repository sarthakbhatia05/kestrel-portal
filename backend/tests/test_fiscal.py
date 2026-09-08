from datetime import date

from kestrel.fiscal import (
    fiscal_year_and_quarter,
    latest_complete_quarter,
    quarter_period,
)


def test_april_starts_q1_of_the_next_fiscal_year():
    assert fiscal_year_and_quarter(date(2026, 4, 1)) == (2027, 1)
    assert fiscal_year_and_quarter(date(2026, 6, 30)) == (2027, 1)


def test_march_is_q4_of_the_fiscal_year_that_ends_that_month():
    assert fiscal_year_and_quarter(date(2026, 3, 31)) == (2026, 4)


def test_january_is_q4_not_q1():
    """The trap this module exists to avoid: calendar Q1 is fiscal Q4."""
    assert fiscal_year_and_quarter(date(2026, 1, 15)) == (2026, 4)


def test_quarter_period_spans_april_to_june_and_is_labelled():
    period = quarter_period(2027, 1)
    assert period.start == date(2026, 4, 1)
    assert period.end == date(2026, 6, 30)
    assert period.label == "FY27 Q1"


def test_latest_complete_quarter_excludes_the_quarter_in_progress():
    # 15 August 2026 sits in FY27 Q2, so the last complete quarter is FY27 Q1.
    period = latest_complete_quarter(date(2026, 8, 15))
    assert period.label == "FY27 Q1"
    assert (period.start, period.end) == (date(2026, 4, 1), date(2026, 6, 30))


def test_latest_complete_quarter_wraps_back_across_the_fiscal_year():
    # 10 May 2026 is FY27 Q1, so the last complete quarter is FY26 Q4.
    period = latest_complete_quarter(date(2026, 5, 10))
    assert period.label == "FY26 Q4"
    assert (period.start, period.end) == (date(2026, 1, 1), date(2026, 3, 31))
