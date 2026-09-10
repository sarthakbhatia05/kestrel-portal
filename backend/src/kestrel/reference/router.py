"""GET /api/service/reference/scope.

The selectors need to know which regions exist and which periods have
data. Serving that from the same curated database the figures come from
means the dropdown and the dashboard cannot drift apart.
"""

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends

from kestrel.dependencies import get_curated_db
from kestrel.reference import scope
from kestrel.reference.scope import ScopeOptions

router = APIRouter(prefix="/api/service/reference", tags=["reference"])


@router.get("/scope", response_model=ScopeOptions)
def get_scope(conn: Annotated[sqlite3.Connection, Depends(get_curated_db)]) -> ScopeOptions:
    return scope.build(conn)
