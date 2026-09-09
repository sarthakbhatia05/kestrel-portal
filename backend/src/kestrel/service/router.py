import sqlite3
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from kestrel.config import get_settings
from kestrel.dependencies import get_curated_db, resolve_period
from kestrel.exceptions import AppError
from kestrel.fiscal import Period
from kestrel.metrics import fill_rate, near_expiry, otif, returns
from kestrel.metrics.types import (
    Grain,
    MetricRequest,
    MetricResult,
    NearExpiryGrain,
    NearExpiryRequest,
    NearExpiryResult,
    OtifResult,
    ReturnsGrain,
    ReturnsRequest,
    ReturnsResult,
    Unit,
)

router = APIRouter(prefix="/api/service", tags=["service"])


@router.get("/fill-rate", response_model=MetricResult)
def get_fill_rate(
    period: Annotated[Period, Depends(resolve_period)],
    conn: Annotated[sqlite3.Connection, Depends(get_curated_db)],
    grain: Grain = Grain.OUTLET,
    unit: Unit = Unit.EACHES,
    region_id: int | None = None,
    include_excluded: bool = False,
    ascending: bool = False,
    limit: int | None = Query(default=None, ge=1, le=500),
) -> MetricResult:
    """Fill rate for a period. PRD 5.2.

    The router performs no arithmetic: the figure and its basis both come
    from the single canonical metric implementation.
    """
    return fill_rate.compute(
        conn,
        MetricRequest(
            grain=grain,
            period_start=period.start,
            period_end=period.end,
            period_label=period.label,
            unit=unit,
            region_id=region_id,
            include_excluded=include_excluded,
            ascending=ascending,
            limit=limit,
        ),
    )


@router.get("/otif", response_model=OtifResult)
def get_otif(
    period: Annotated[Period, Depends(resolve_period)],
    conn: Annotated[sqlite3.Connection, Depends(get_curated_db)],
    grain: Grain = Grain.OUTLET,
    region_id: int | None = None,
    include_excluded: bool = False,
    ascending: bool = False,
    limit: int | None = Query(default=None, ge=1, le=500),
    tolerance_minutes: int | None = Query(default=None, ge=0, le=1440),
) -> OtifResult:
    """OTIF for a period. PRD 5.3.

    tolerance_minutes defaults to the configured on-time tolerance (PRD A1)
    so the basis always states which tolerance produced a given figure.
    """
    resolved_tolerance = (
        tolerance_minutes if tolerance_minutes is not None
        else get_settings().on_time_tolerance_minutes
    )
    return otif.compute(
        conn,
        MetricRequest(
            grain=grain,
            period_start=period.start,
            period_end=period.end,
            period_label=period.label,
            region_id=region_id,
            include_excluded=include_excluded,
            ascending=ascending,
            limit=limit,
            tolerance_minutes=resolved_tolerance,
        ),
    )


@router.get("/returns", response_model=ReturnsResult)
def get_returns(
    period: Annotated[Period, Depends(resolve_period)],
    conn: Annotated[sqlite3.Connection, Depends(get_curated_db)],
    grain: ReturnsGrain = ReturnsGrain.CATEGORY,
    region_id: int | None = None,
    include_excluded: bool = False,
    ascending: bool = False,
    limit: int | None = Query(default=None, ge=1, le=500),
) -> ReturnsResult:
    """Returns and credit note leakage for a period. PRD 5.6."""
    return returns.compute(
        conn,
        ReturnsRequest(
            grain=grain,
            period_start=period.start,
            period_end=period.end,
            period_label=period.label,
            region_id=region_id,
            include_excluded=include_excluded,
            ascending=ascending,
            limit=limit,
        ),
    )


@router.get("/near-expiry", response_model=NearExpiryResult)
def get_near_expiry(
    conn: Annotated[sqlite3.Connection, Depends(get_curated_db)],
    grain: NearExpiryGrain = NearExpiryGrain.CATEGORY,
    region_id: int | None = None,
    snapshot_date: date | None = None,
    ascending: bool = False,
    limit: int | None = Query(default=None, ge=1, le=500),
    threshold_days: int | None = Query(default=None, ge=1, le=365),
) -> NearExpiryResult:
    """Near-expiry stock as-at the latest inventory snapshot. PRD 5.5.

    snapshot_date defaults to the most recent snapshot present in the
    curated database, not today (PRD 5.5: inventory positions are as-at the
    snapshot, never as-at today). threshold_days defaults to the configured
    near-expiry threshold (PRD A2), the same way OTIF resolves
    tolerance_minutes.
    """
    resolved_snapshot = snapshot_date
    if resolved_snapshot is None:
        latest = near_expiry.latest_snapshot_date(conn)
        if latest is None:
            raise AppError(
                code="NO_INVENTORY_SNAPSHOTS",
                message="No inventory snapshots are present in the curated database.",
                status=503,
            )
        resolved_snapshot = date.fromisoformat(latest)
    resolved_threshold = (
        threshold_days if threshold_days is not None
        else get_settings().near_expiry_days
    )
    return near_expiry.compute(
        conn,
        NearExpiryRequest(
            grain=grain,
            snapshot_date=resolved_snapshot,
            threshold_days=resolved_threshold,
            region_id=region_id,
            ascending=ascending,
            limit=limit,
        ),
    )
