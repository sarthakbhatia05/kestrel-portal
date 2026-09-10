from datetime import date

import pytest

from kestrel.fiscal import (
    PeriodKind,
    custom_period,
    fiscal_year_and_quarter,
    latest_complete_quarter,
    latest_reportable_quarter,
    month_period,
    previous_period,
    quarter_period,
    week_period,
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


# --- The default quarter -------------------------------------------------
#
# The extract ends on 30 June 2026. Read against the calendar alone, "latest"
# moves to FY27 Q2 on 1 October and every card on the landing page goes
# empty. The default must stop at the quarter the data ends in.


def test_latest_reportable_quarter_is_the_complete_quarter_when_the_data_reaches_it():
    period = latest_reportable_quarter(date(2026, 9, 10), date(2026, 6, 30))
    assert period.label == "FY27 Q1"


def test_latest_reportable_quarter_never_runs_past_the_data():
    # November 2026: the calendar's last complete quarter is FY27 Q2, which
    # holds no rows at all.
    period = latest_reportable_quarter(date(2026, 11, 5), date(2026, 6, 30))
    assert period.label == "FY27 Q1"
    assert (period.start, period.end) == (date(2026, 4, 1), date(2026, 6, 30))


def test_latest_reportable_quarter_still_excludes_the_quarter_in_progress():
    # Data current to yesterday, mid-Q2: Q2 is not finished, so Q1 it is.
    period = latest_reportable_quarter(date(2026, 8, 15), date(2026, 8, 14))
    assert period.label == "FY27 Q1"


def test_latest_reportable_quarter_falls_back_to_the_calendar_without_data():
    period = latest_reportable_quarter(date(2026, 11, 5), None)
    assert period.label == "FY27 Q2"


# --- Sub-quarter periods -------------------------------------------------
#
# The dashboard offers quarters and months; ask-anything additionally
# accepts weeks and explicit ranges, because "last week" is a thing people
# type and not a thing anyone wants to scroll a dropdown for.


def test_month_period_spans_the_calendar_month():
    period = month_period(2026, 6)
    assert (period.start, period.end) == (date(2026, 6, 1), date(2026, 6, 30))
    assert period.label == "June 2026"
    assert period.kind is PeriodKind.MONTH


def test_month_period_handles_february_in_a_leap_year():
    period = month_period(2024, 2)
    assert period.end == date(2024, 2, 29)


def test_week_period_runs_monday_to_sunday():
    # 2026-W24 begins Monday 8 June 2026.
    period = week_period(2026, 24)
    assert (period.start, period.end) == (date(2026, 6, 8), date(2026, 6, 14))
    assert period.start.weekday() == 0
    assert period.label == "Week of 8 Jun 2026"
    assert period.kind is PeriodKind.WEEK


def test_custom_period_spans_the_dates_given():
    period = custom_period(date(2026, 4, 1), date(2026, 6, 30))
    assert (period.start, period.end) == (date(2026, 4, 1), date(2026, 6, 30))
    assert period.label == "1 Apr – 30 Jun 2026"
    assert period.kind is PeriodKind.RANGE


def test_custom_period_rejects_an_end_before_its_start():
    with pytest.raises(ValueError):
        custom_period(date(2026, 6, 30), date(2026, 4, 1))


def test_quarter_period_is_labelled_a_quarter():
    assert quarter_period(2027, 1).kind is PeriodKind.QUARTER


# --- Comparison baselines ------------------------------------------------
#
# "Why did fill rate drop" needs something to have dropped *from*. The
# baseline is always the preceding period of the same kind, so a question
# about a week is answered against a week and never against a quarter.


def test_previous_quarter_steps_back_one_quarter():
    assert previous_period(quarter_period(2027, 1)).label == "FY26 Q4"


def test_previous_quarter_wraps_across_the_fiscal_year_boundary():
    """FY27 Q1 starts in April, so its predecessor is the January–March quarter."""
    previous = previous_period(quarter_period(2027, 1))
    assert (previous.start, previous.end) == (date(2026, 1, 1), date(2026, 3, 31))


def test_previous_month_steps_back_across_january():
    assert previous_period(month_period(2026, 1)).label == "December 2025"


def test_previous_week_steps_back_seven_days():
    previous = previous_period(week_period(2026, 24))
    assert (previous.start, previous.end) == (date(2026, 6, 1), date(2026, 6, 7))


def test_previous_range_is_the_equally_long_span_immediately_before():
    previous = previous_period(custom_period(date(2026, 6, 15), date(2026, 6, 21)))
    assert (previous.start, previous.end) == (date(2026, 6, 8), date(2026, 6, 14))
