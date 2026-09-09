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
    # PRD A1. Read only by otif.compute; other metrics ignore it. None means
    # "use the configured default" and is resolved by the router, not here,
    # so the basis can state the tolerance that actually produced a figure.
    tolerance_minutes: int | None = None


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
    # PRD A1. Set only by otif.compute; other metrics leave it None.
    tolerance_minutes: int | None = None
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


class OtifRow(BaseModel):
    """On-time and in-full are reported separately as well as combined
    (PRD C2.4) -- a delivery can fail on either axis independently."""

    key: str
    label: str
    due_count: int
    on_time_count: int
    in_full_count: int
    otif_count: int
    on_time_rate: float | None
    in_full_rate: float | None
    otif: float | None


class OtifResult(BaseModel):
    headline: OtifRow
    rows: list[OtifRow]
    basis: MetricBasis
