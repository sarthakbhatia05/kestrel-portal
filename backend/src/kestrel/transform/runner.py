import json
import sqlite3
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from kestrel.database import curated_connection, source_connection
from kestrel.transform.ledger import QualityLedger
from kestrel.transform.schema import CURATED_SCHEMA


class Step(Protocol):
    name: str

    def run(
        self, src: sqlite3.Connection, dst: sqlite3.Connection, ledger: QualityLedger
    ) -> None: ...


class BuildResult:
    def __init__(
        self,
        run_id: str,
        table_counts: dict[str, int],
        ledger_counts: dict[str, int],
        duration_seconds: float,
    ) -> None:
        self.run_id = run_id
        self.table_counts = table_counts
        self.ledger_counts = ledger_counts
        self.duration_seconds = duration_seconds


def _steps() -> list[Step]:
    """Imported lazily so the runner can be tested with no steps registered."""
    from kestrel.transform.steps import (
        s00_reference,
        s20_orders,
        s30_deliveries,
        s40_returns,
        s50_inventory,
    )

    return [s00_reference, s20_orders, s30_deliveries, s40_returns, s50_inventory]


COUNTED_TABLES = (
    "dim_region", "dim_outlet", "dim_product", "dim_warehouse", "fact_order_line",
    "fact_delivery", "fact_return", "fact_inventory_snapshot", "quality_ledger",
)


def build(source: Path, curated: Path, steps: list[Step] | None = None) -> BuildResult:
    """Build the curated database from source. Idempotent and re-runnable.

    Writes to a temporary file and renames atomically on success (NF5), so a
    failed run leaves the previous curated database intact and serving.
    """
    steps = _steps() if steps is None else steps
    run_id = str(uuid.uuid4())
    started = time.perf_counter()
    tmp = curated.with_suffix(curated.suffix + ".tmp")
    tmp.unlink(missing_ok=True)

    ledger = QualityLedger()
    table_counts: dict[str, int] = {}

    with source_connection(source) as src, curated_connection(tmp) as dst:
        dst.executescript(CURATED_SCHEMA)
        dst.execute(
            "INSERT INTO build_runs (run_id, started_at, source_db_path) VALUES (?, ?, ?)",
            (run_id, datetime.now(UTC).isoformat(timespec="seconds"), str(source)),
        )
        for step in steps:
            step.run(src, dst, ledger)

        ledger.flush(dst, run_id)

        for table in COUNTED_TABLES:
            table_counts[table] = dst.execute(
                f"SELECT count(*) FROM {table}"  # noqa: S608 - fixed allowlist
            ).fetchone()[0]

        dst.execute(
            "UPDATE build_runs SET finished_at = ?, table_counts = ? WHERE run_id = ?",
            (
                datetime.now(UTC).isoformat(timespec="seconds"),
                json.dumps(table_counts),
                run_id,
            ),
        )
        dst.commit()

    curated.parent.mkdir(parents=True, exist_ok=True)
    tmp.replace(curated)

    return BuildResult(
        run_id=run_id,
        table_counts=table_counts,
        ledger_counts=ledger.counts(),
        duration_seconds=time.perf_counter() - started,
    )
