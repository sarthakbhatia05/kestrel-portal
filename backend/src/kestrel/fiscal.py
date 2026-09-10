from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

DEFAULT_START_MONTH = 4  # PRD 5.7: financial year runs April to March.


class PeriodKind(StrEnum):
    """What sort of span a period is.

    Carried on the period itself because the comparison baseline depends on
    it: the period before FY27 Q1 is a quarter, and the period before a week
    is a week. Without the kind, `previous_period` would have to infer it
    from the dates, and a 31-day month would be indistinguishable from an
    arbitrary 31-day range.
    """

    QUARTER = "quarter"
    MONTH = "month"
    WEEK = "week"
    RANGE = "range"


@dataclass(frozen=True)
class Period:
    start: date
    end: date
    label: str
    kind: PeriodKind = PeriodKind.QUARTER


def fiscal_year_and_quarter(
    day: date, start_month: int = DEFAULT_START_MONTH
) -> tuple[int, int]:
    """Return (fiscal_year, quarter) for a date.

    The fiscal year is named for the calendar year in which it ends, which
    is how Kestrel's board refers to it: April 2026 falls in FY27 Q1.
    """
    offset = (day.month - start_month) % 12
    quarter = offset // 3 + 1
    fiscal_year = day.year + 1 if day.month >= start_month else day.year
    return fiscal_year, quarter


def quarter_period(
    fiscal_year: int, quarter: int, start_month: int = DEFAULT_START_MONTH
) -> Period:
    if not 1 <= quarter <= 4:
        raise ValueError(f"Quarter must be 1-4, got {quarter}")

    month_index = start_month + (quarter - 1) * 3
    start_year = fiscal_year - 1 + (month_index - 1) // 12
    start_month_no = (month_index - 1) % 12 + 1

    end_index = month_index + 2
    end_year = fiscal_year - 1 + (end_index - 1) // 12
    end_month_no = (end_index - 1) % 12 + 1

    return Period(
        start=date(start_year, start_month_no, 1),
        end=date(end_year, end_month_no, monthrange(end_year, end_month_no)[1]),
        label=f"FY{fiscal_year % 100:02d} Q{quarter}",
        kind=PeriodKind.QUARTER,
    )


def latest_complete_quarter(
    today: date, start_month: int = DEFAULT_START_MONTH
) -> Period:
    """The most recent quarter that has finished. The current one is excluded."""
    fiscal_year, quarter = fiscal_year_and_quarter(today, start_month)
    if quarter == 1:
        return quarter_period(fiscal_year - 1, 4, start_month)
    return quarter_period(fiscal_year, quarter - 1, start_month)


def latest_reportable_quarter(
    today: date, data_end: date | None, start_month: int = DEFAULT_START_MONTH
) -> Period:
    """The most recent quarter that has both finished and has data in it.

    The calendar alone is not enough: the extract ends on 30 June 2026, so
    from 1 October `latest_complete_quarter` names FY27 Q2, which holds no
    rows, and every card on the landing page opens empty. Capping it at the
    quarter the data ends in keeps the default on a real figure, and still
    never offers a quarter that is in progress.
    """
    complete = latest_complete_quarter(today, start_month)
    if data_end is None or data_end >= complete.start:
        return complete
    fiscal_year, quarter = fiscal_year_and_quarter(data_end, start_month)
    return quarter_period(fiscal_year, quarter, start_month)


def month_period(year: int, month: int) -> Period:
    """A calendar month. Months are calendar, not fiscal: nobody asks for
    "the first month of Q1", they ask for June."""
    if not 1 <= month <= 12:
        raise ValueError(f"Month must be 1-12, got {month}")
    start = date(year, month, 1)
    return Period(
        start=start,
        end=date(year, month, monthrange(year, month)[1]),
        label=f"{start:%B} {year}",
        kind=PeriodKind.MONTH,
    )


def week_period(iso_year: int, iso_week: int) -> Period:
    """An ISO week, Monday to Sunday.

    ISO rather than a rolling seven days, so that "last week" means the same
    span to two people who ask on different days.
    """
    start = date.fromisocalendar(iso_year, iso_week, 1)
    return Period(
        start=start,
        end=start + timedelta(days=6),
        label=f"Week of {start.day} {start:%b} {start.year}",
        kind=PeriodKind.WEEK,
    )


def custom_period(start: date, end: date) -> Period:
    """An explicit span, inclusive of both ends."""
    if end < start:
        raise ValueError(f"Period end {end} falls before its start {start}")
    left = f"{start.day} {start:%b}"
    if start.year != end.year:
        left = f"{left} {start.year}"
    return Period(
        start=start,
        end=end,
        label=f"{left} – {end.day} {end:%b} {end.year}",
        kind=PeriodKind.RANGE,
    )


def previous_period(period: Period, start_month: int = DEFAULT_START_MONTH) -> Period:
    """The period immediately before this one, of the same kind.

    The baseline for every period-over-period comparison. Same kind
    deliberately: a question about a week is answered against the previous
    week, never against a quarter that happens to contain it.
    """
    if period.kind is PeriodKind.QUARTER:
        fiscal_year, quarter = fiscal_year_and_quarter(period.start, start_month)
        if quarter == 1:
            return quarter_period(fiscal_year - 1, 4, start_month)
        return quarter_period(fiscal_year, quarter - 1, start_month)

    if period.kind is PeriodKind.MONTH:
        last_day_before = period.start - timedelta(days=1)
        return month_period(last_day_before.year, last_day_before.month)

    if period.kind is PeriodKind.WEEK:
        start = period.start - timedelta(days=7)
        iso_year, iso_week, _ = start.isocalendar()
        return week_period(iso_year, iso_week)

    length = (period.end - period.start).days
    end = period.start - timedelta(days=1)
    return custom_period(end - timedelta(days=length), end)
