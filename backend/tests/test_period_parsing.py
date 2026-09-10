"""The period grammar every surface shares.

Periods are parsed in exactly one place so the dashboard, the API and
ask-anything cannot disagree about what "June 2026" or "FY27 Q1" means.
The dropdown offers quarters and months; weeks and explicit ranges exist
for questions people type rather than scroll to.
"""

import sqlite3
from datetime import date

import pytest

from kestrel import dependencies
from kestrel.dependencies import parse_period
from kestrel.exceptions import AppError
from kestrel.fiscal import PeriodKind
from kestrel.transform.runner import build
from kestrel.transform.steps import s00_reference, s20_orders


def test_fiscal_quarter_still_parses():
    period = parse_period("FY27Q1")
    assert (period.start, period.end) == (date(2026, 4, 1), date(2026, 6, 30))
    assert period.kind is PeriodKind.QUARTER


def test_latest_still_resolves_to_a_complete_quarter():
    assert parse_period("latest").kind is PeriodKind.QUARTER


def test_latest_is_anchored_to_the_data_not_the_calendar(tmp_path, source_db, monkeypatch):
    """The fixture's orders end in May 2026 (FY27 Q1). Read in January 2027,
    the calendar's last complete quarter is FY27 Q3, which has no rows."""
    path = tmp_path / "curated.db"
    build(source_db, path, steps=[s00_reference, s20_orders])
    conn = sqlite3.connect(path)
    monkeypatch.setattr(dependencies, "_today", lambda: date(2027, 1, 15))
    try:
        assert parse_period("latest", conn).label == "FY27 Q1"
    finally:
        conn.close()


def test_calendar_month_parses():
    period = parse_period("2026-06")
    assert (period.start, period.end) == (date(2026, 6, 1), date(2026, 6, 30))
    assert period.label == "June 2026"


def test_iso_week_parses():
    period = parse_period("2026-W24")
    assert (period.start, period.end) == (date(2026, 6, 8), date(2026, 6, 14))


def test_iso_week_is_case_insensitive():
    assert parse_period("2026-w24") == parse_period("2026-W24")


def test_explicit_range_parses():
    period = parse_period("2026-04-01..2026-06-30")
    assert (period.start, period.end) == (date(2026, 4, 1), date(2026, 6, 30))
    assert period.kind is PeriodKind.RANGE


def test_a_month_outside_1_to_12_is_rejected():
    with pytest.raises(AppError) as exc:
        parse_period("2026-13")
    assert exc.value.code == "INVALID_PERIOD"


def test_a_week_outside_the_year_is_rejected():
    with pytest.raises(AppError) as exc:
        parse_period("2026-W99")
    assert exc.value.code == "INVALID_PERIOD"


def test_a_range_that_ends_before_it_starts_is_rejected_as_a_period_error():
    """Not a ValueError escaping to a 500: the user typed it, so it is a 4xx."""
    with pytest.raises(AppError) as exc:
        parse_period("2026-06-30..2026-04-01")
    assert exc.value.code == "INVALID_PERIOD"


def test_nonsense_is_rejected_and_says_what_is_supported():
    with pytest.raises(AppError) as exc:
        parse_period("last tuesday")
    assert exc.value.code == "INVALID_PERIOD"
    assert exc.value.detail is not None
