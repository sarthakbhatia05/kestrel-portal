import re
import sqlite3
from collections.abc import Iterator
from datetime import date

from fastapi import Query

from kestrel.config import get_settings
from kestrel.database import open_curated_readonly
from kestrel.exceptions import AppError
from kestrel.fiscal import Period, latest_complete_quarter, quarter_period

_PERIOD_PATTERN = re.compile(r"^FY(\d{2})Q([1-4])$", re.IGNORECASE)


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


def parse_period(period: str) -> Period:
    """'latest' or FY<yy>Q<n> as a real date range.

    Periods are resolved here for every surface, including ask-anything:
    the fiscal year starts in April, and anything that does its own quarter
    arithmetic will eventually disagree with the dashboard.
    """
    settings = get_settings()
    if period == "latest":
        return latest_complete_quarter(date.today(), settings.fiscal_year_start_month)

    match = _PERIOD_PATTERN.match(period)
    if not match:
        raise AppError(
            code="INVALID_PERIOD",
            message=f"Could not read period '{period}'. Use 'latest' or e.g. 'FY27Q1'.",
            detail={"supported": ["latest", "FY<yy>Q<1-4>"]},
        )
    return quarter_period(
        2000 + int(match.group(1)),
        int(match.group(2)),
        settings.fiscal_year_start_month,
    )


def resolve_period(
    period: str = Query(
        default="latest",
        description="'latest' for the most recent complete fiscal quarter, or FY27Q1.",
    ),
) -> Period:
    return parse_period(period)
