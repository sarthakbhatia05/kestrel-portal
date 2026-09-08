import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from kestrel.dependencies import get_curated_db, resolve_period
from kestrel.fiscal import Period
from kestrel.metrics import fill_rate
from kestrel.metrics.types import Grain, MetricRequest, MetricResult, Unit

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
