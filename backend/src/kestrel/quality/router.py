"""GET /api/service/quality and /api/service/quality/ledger. PRD 6.4.

The first states what every other screen excludes for the selected scope;
the second lists the ledger entries behind a rule, so a count can be traced
back to the records it counts.
"""

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from kestrel.dependencies import get_curated_db, resolve_period
from kestrel.fiscal import Period
from kestrel.quality import exclusions, rules
from kestrel.quality.types import LedgerPage, QualityResponse

router = APIRouter(prefix="/api/service/quality", tags=["quality"])


def _built_at(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT finished_at FROM build_runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


@router.get("", response_model=QualityResponse)
def get_quality(
    period: Annotated[Period, Depends(resolve_period)],
    conn: Annotated[sqlite3.Connection, Depends(get_curated_db)],
    region_id: int | None = None,
) -> QualityResponse:
    result = exclusions.compute(conn, period, region_id)
    return QualityResponse(
        **result.model_dump(),
        rules=rules.catalogue(conn),
        built_at=_built_at(conn),
    )


@router.get("/ledger", response_model=LedgerPage)
def get_ledger(
    conn: Annotated[sqlite3.Connection, Depends(get_curated_db)],
    rule: str = Query(max_length=8),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> LedgerPage:
    return rules.ledger_entries(conn, rule, limit=limit, offset=offset)
