"""The dimension values the model is allowed to name.

Entity resolution here is a closed-set problem, not a search problem:
there are a handful of regions, warehouses, categories and return reasons,
and they all fit in a prompt. Handing the model the real ids means
"Mumbai" resolves to a region_id the metric layer accepts, and a name that
is not in the catalogue cannot be invented into one.

Outlets are the one dimension too large to enumerate. They are reached
through the existing substring filter (`q`) instead.
"""

import sqlite3

from pydantic import BaseModel


class RegionEntry(BaseModel):
    region_id: int
    region_name: str


class Catalogue(BaseModel):
    regions: list[RegionEntry]
    warehouses: list[str]
    categories: list[str]
    return_reasons: list[str]


def build(conn: sqlite3.Connection) -> Catalogue:
    """Read the enumerable dimensions out of the curated database.

    Read from the data rather than hard-coded, so a question about a
    region that was added last month resolves without a code change.
    """
    return Catalogue(
        regions=[
            RegionEntry(region_id=row[0], region_name=row[1])
            for row in conn.execute(
                "SELECT region_id, region_name FROM dim_region ORDER BY region_id"
            )
        ],
        warehouses=[
            row[0]
            for row in conn.execute(
                "SELECT warehouse_name FROM dim_warehouse ORDER BY warehouse_name"
            )
        ],
        categories=[
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT category FROM dim_product "
                "WHERE category IS NOT NULL ORDER BY category"
            )
        ],
        return_reasons=[
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT return_reason_code FROM fact_return "
                "WHERE return_reason_code IS NOT NULL ORDER BY return_reason_code"
            )
        ],
    )
