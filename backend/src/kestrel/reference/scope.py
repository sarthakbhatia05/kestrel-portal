"""The scope options a client can choose between.

Regions and periods are read out of the curated database rather than
hard-coded, for the same reason ask-anything's catalogue is: an option
list that disagrees with the data produces a view with nothing in it and
a reader who concludes the build is broken.
"""

import sqlite3

from pydantic import BaseModel

from kestrel.fiscal import fiscal_year_and_quarter, month_period, quarter_period


class RegionOption(BaseModel):
    region_id: int
    region_name: str


class PeriodOption(BaseModel):
    # What to send back as `period`; parsed by dependencies.parse_period.
    value: str
    label: str
    # quarter | month | relative. The client groups the dropdown by this.
    kind: str


class ScopeOptions(BaseModel):
    regions: list[RegionOption]
    periods: list[PeriodOption]


# Always offered, always first: the default scope should be a real option
# in the list the API returns, not a special case the client adds on.
LATEST = PeriodOption(value="latest", label="Latest complete quarter", kind="relative")


def list_regions(conn: sqlite3.Connection) -> list[RegionOption]:
    return [
        RegionOption(region_id=row[0], region_name=row[1])
        for row in conn.execute(
            "SELECT region_id, region_name FROM dim_region ORDER BY region_id"
        )
    ]


def available_periods(conn: sqlite3.Connection) -> list[PeriodOption]:
    """Every month with orders in it, and the quarters those months fall in.

    Order dates are the spine of the dataset: fill rate, OTIF, returns and
    excursions all key off them. (Near-expiry is as-at a weekly snapshot
    and has no period at all, so it contributes nothing here.)
    """
    months = [
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT strftime('%Y-%m', order_date) AS month "
            "FROM fact_order_line WHERE order_date IS NOT NULL "
            "ORDER BY month DESC"
        )
    ]

    quarters: dict[tuple[int, int], None] = {}
    for month in months:
        year, month_no = int(month[:4]), int(month[5:7])
        quarters.setdefault(fiscal_year_and_quarter(month_period(year, month_no).start), None)

    return [
        LATEST,
        *[
            PeriodOption(
                value=f"FY{fy % 100:02d}Q{q}", label=quarter_period(fy, q).label, kind="quarter"
            )
            for fy, q in sorted(quarters, reverse=True)
        ],
        *[
            PeriodOption(
                value=month,
                label=month_period(int(month[:4]), int(month[5:7])).label,
                kind="month",
            )
            for month in months
        ],
    ]


def build(conn: sqlite3.Connection) -> ScopeOptions:
    return ScopeOptions(regions=list_regions(conn), periods=available_periods(conn))


def data_range(conn: sqlite3.Connection) -> tuple[str, str] | None:
    """The first and last order date present, or None when there are none."""
    row = conn.execute(
        "SELECT MIN(order_date), MAX(order_date) FROM fact_order_line "
        "WHERE order_date IS NOT NULL"
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return row[0], row[1]
