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


class ReturnsGrain(StrEnum):
    """PRD 5.6: category, reason and region -- a different set from fill
    rate/OTIF's region/warehouse/route/outlet, so it is its own enum rather
    than an addition to Grain."""

    CATEGORY = "category"
    REASON = "reason"
    REGION = "region"


class ReturnsRequest(BaseModel):
    grain: ReturnsGrain
    period_start: date
    period_end: date
    period_label: str
    region_id: int | None = None
    include_excluded: bool = False
    limit: int | None = Field(default=None, ge=1, le=500)
    ascending: bool = False


class ReturnsRow(BaseModel):
    key: str
    label: str
    credit_note_value_inr: float
    dispatch_value_inr: float
    returns_rate: float | None
    cold_chain_value_inr: float
    cold_chain_rate: float | None


class ReturnsBasis(BaseModel):
    """Mirrors MetricBasis's shape but drops `unit` (returns has no
    eaches/cases toggle) and adds the pending/rejected value PRD 5.6's
    APPROVED-only rate would otherwise make invisible -- the same reasoning
    as OTIF's unmeasured_count."""

    metric: str
    period_start: date
    period_end: date
    period_label: str
    scope: str
    exclusions_applied: list[str]
    pending_count: int
    pending_value_inr: float
    rejected_count: int
    rejected_value_inr: float
    source_row_count: int


class ReturnsResult(BaseModel):
    headline: ReturnsRow
    rows: list[ReturnsRow]
    basis: ReturnsBasis


class NearExpiryGrain(StrEnum):
    """PRD C3.3: warehouse and category."""

    WAREHOUSE = "warehouse"
    CATEGORY = "category"


class NearExpiryRequest(BaseModel):
    """Inventory is a weekly snapshot, not a period range (PRD 5.5) -- there
    is no period_start/period_end here, only the as-at snapshot_date."""

    grain: NearExpiryGrain
    snapshot_date: date
    # PRD A2. Resolved by the router from config, like OTIF's tolerance_minutes,
    # so the basis states the threshold that produced a given figure.
    threshold_days: int
    region_id: int | None = None
    limit: int | None = Field(default=None, ge=1, le=500)
    ascending: bool = False


class NearExpiryRow(BaseModel):
    key: str
    label: str
    near_expiry_cases: float
    total_available_cases: float
    near_expiry_rate: float | None
    near_expiry_value_inr: float


class NearExpiryBasis(BaseModel):
    """No PRD 6.3 exclusion rule is scoped to warehouses or inventory, so
    unlike every other basis this carries no exclusions_applied. Damaged and
    blocked stock are surfaced here instead of folded into the rate (PRD
    5.5: "reported separately"), the same way returns' basis surfaces
    pending/rejected value."""

    metric: str
    snapshot_date: date
    scope: str
    threshold_days: int
    damaged_cases: float
    damaged_value_inr: float
    blocked_cases: float
    blocked_value_inr: float
    source_row_count: int


class NearExpiryResult(BaseModel):
    headline: NearExpiryRow
    rows: list[NearExpiryRow]
    basis: NearExpiryBasis
