from calendar import monthrange
from dataclasses import dataclass
from datetime import date

DEFAULT_START_MONTH = 4  # PRD 5.7: financial year runs April to March.


@dataclass(frozen=True)
class Period:
    start: date
    end: date
    label: str


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
    )


def latest_complete_quarter(
    today: date, start_month: int = DEFAULT_START_MONTH
) -> Period:
    """The most recent quarter that has finished. The current one is excluded."""
    fiscal_year, quarter = fiscal_year_and_quarter(today, start_month)
    if quarter == 1:
        return quarter_period(fiscal_year - 1, 4, start_month)
    return quarter_period(fiscal_year, quarter - 1, start_month)
