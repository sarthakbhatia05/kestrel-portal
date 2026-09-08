from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field


class Unit(StrEnum):
    EACHES = "eaches"
    CASES = "cases"


class Grain(StrEnum):
    REGION = "region"
    WAREHOUSE = "warehouse"
    ROUTE = "route"
    OUTLET = "outlet"


class MetricRequest(BaseModel):
    grain: Grain
    period_start: date
    period_end: date
    period_label: str
    # PRD 5.2: eaches is the default because modern trade penalties are
    # assessed on units short. Cases remain available as a toggle.
    unit: Unit = Unit.EACHES
    region_id: int | None = None
    include_excluded: bool = False
    limit: int | None = Field(default=None, ge=1, le=500)
    ascending: bool = False


class MetricBasis(BaseModel):
    """What a figure was derived from.

    Returned with every result so that no code path can hand back a number
    without its basis (C4.2, success criterion 1).
    """

    metric: str
    period_start: date
    period_end: date
    period_label: str
    unit: Unit
    scope: str
    exclusions_applied: list[str]
    unmeasured_count: int = 0
    source_row_count: int


class MetricRow(BaseModel):
    key: str
    label: str
    numerator: float
    denominator: float
    value: float | None


class MetricResult(BaseModel):
    headline: float | None
    rows: list[MetricRow]
    basis: MetricBasis
