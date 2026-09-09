import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from kestrel.config import get_settings
from kestrel.dependencies import get_curated_db, resolve_period
from kestrel.fiscal import Period
from kestrel.metrics import fill_rate, otif
from kestrel.metrics.types import Grain, MetricRequest, MetricResult, OtifResult, Unit

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
