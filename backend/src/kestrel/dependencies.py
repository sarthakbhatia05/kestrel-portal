import re
import sqlite3
from collections.abc import Iterator
from datetime import date

from fastapi import Query

from kestrel.config import get_settings
from kestrel.database import open_curated_readonly
from kestrel.exceptions import AppError
from kestrel.fiscal import (
    Period,
    custom_period,
    latest_complete_quarter,
    month_period,
    quarter_period,
    week_period,
)

_QUARTER_PATTERN = re.compile(r"^FY(\d{2})Q([1-4])$", re.IGNORECASE)
_MONTH_PATTERN = re.compile(r"^(\d{4})-(\d{2})$")
_WEEK_PATTERN = re.compile(r"^(\d{4})-W(\d{1,2})$", re.IGNORECASE)
_RANGE_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})$")

_SUPPORTED = [
    "latest",
    "FY<yy>Q<1-4>, e.g. FY27Q1",
    "<yyyy>-<mm>, e.g. 2026-06",
    "<yyyy>-W<ww>, e.g. 2026-W24",
    "<yyyy-mm-dd>..<yyyy-mm-dd>, e.g. 2026-04-01..2026-06-30",
]


def get_curated_db() -> Iterator[sqlite3.Connection]:
    settings = get_settings()
    try:
        conn = open_curated_readonly(settings.curated_db_path)
    except FileNotFoundError as exc:
        raise AppError(
            code="CURATED_DB_MISSING",
            message=str(exc),
            status=503,
        ) from exc
    try:
        yield conn
    finally:
        conn.close()


def _invalid(period: str) -> AppError:
    return AppError(
        code="INVALID_PERIOD",
        message=f"Could not read period '{period}'.",
        detail={"supported": _SUPPORTED},
    )


def parse_period(period: str) -> Period:
    """A period specification as a real date range.

    Periods are resolved here for every surface, including ask-anything:
    the fiscal year starts in April, and anything that does its own quarter
    arithmetic will eventually disagree with the dashboard.

    Quarters and months are what the dashboard's selector offers. Weeks and
    explicit ranges exist because they are typed rather than scrolled to --
    "last week" is a question people ask and a dropdown nobody wants.
    """
    settings = get_settings()
    if period == "latest":
        return latest_complete_quarter(date.today(), settings.fiscal_year_start_month)

    if match := _QUARTER_PATTERN.match(period):
        return quarter_period(
            2000 + int(match.group(1)),
            int(match.group(2)),
            settings.fiscal_year_start_month,
        )

    # Every constructor below rejects an out-of-range value with ValueError.
    # The user typed this string, so it becomes a 4xx rather than escaping
    # as a 500.
    try:
        if match := _MONTH_PATTERN.match(period):
            return month_period(int(match.group(1)), int(match.group(2)))
        if match := _WEEK_PATTERN.match(period):
            return week_period(int(match.group(1)), int(match.group(2)))
        if match := _RANGE_PATTERN.match(period):
            return custom_period(
                date.fromisoformat(match.group(1)), date.fromisoformat(match.group(2))
            )
    except ValueError as exc:
        raise _invalid(period) from exc

    raise _invalid(period)


def resolve_period(
    period: str = Query(
        default="latest",
        description="'latest' for the most recent complete fiscal quarter, or FY27Q1.",
    ),
) -> Period:
    return parse_period(period)
