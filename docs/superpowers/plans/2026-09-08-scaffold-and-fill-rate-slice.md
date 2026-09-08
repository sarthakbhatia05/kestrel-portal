# Kestrel Portal — Scaffold and Fill-Rate Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the backend and frontend project structure, the curated data layer with its quality ledger, and fill rate working end to end from source database to a rendered figure with its basis.

**Architecture:** A transform CLI reads the source SQLite database read-only and materialises a separate curated SQLite database, writing a row to a quality ledger for every record it excludes or repairs. A metric layer computes figures from the curated database only, returning each figure together with the basis on which it was derived. FastAPI domain packages serve those results without performing arithmetic. A Vite/React frontend renders the landing view from the generated API contract.

**Tech Stack:** Python 3.11+, FastAPI, pydantic-settings, `sqlite3` (stdlib, raw SQL, no ORM), pytest, httpx, Ruff. Vite, React 18, TypeScript, TanStack Query.

**Spec:** [docs/superpowers/specs/2026-09-08-kestrel-portal-design.md](../specs/2026-09-08-kestrel-portal-design.md)

## Global Constraints

- **Source data is never mutated (NF6).** The source database is opened only as `sqlite3.connect("file:<path>?mode=ro", uri=True)`, and only from within `kestrel/transform/`. No other package may open it.
- **No HTTP-facing code reads the source database (PRD §6.1).** Routers and domain services read the curated database only.
- **No router or domain service computes a figure (G1, C4.3).** Every number originates in `kestrel/metrics/`.
- **`kestrel/metrics/` must not import from any domain package** (`service`, `coldchain`, `quality`, `ask`, `reference`), so it stays unit-testable without the app (NF8).
- **The transform stage is idempotent (NF5).** It builds to a `.tmp` file and atomically renames on success.
- **Exclusions are flags, never deletions (PRD §6.3).** Excluded rows stay in the curated tables carrying `is_excluded` and `exclusion_rules`; the default query filter hides them and `include_excluded=true` lifts it.
- **Every metric result carries its basis (C4.2).** There is no code path returning a figure without period, scope, unit, exclusions and unmeasured count.
- **Fiscal year starts in April.** Q1 is April–June (PRD §5.7). No calendar-year quarter logic anywhere.
- **Default unit is eaches** (PRD §5.2, Rakesh Menon's note). Cases are a toggle, and are always derived from the eaches figure, never computed independently.
- **Assumption thresholds are configuration, not literals:** on-time tolerance 30 minutes (A1), near-expiry 30 days (A2).
- **No user input is ever interpolated into SQL.** Grain and scope resolve through a validated allowlist; all values are bound parameters.
- Python 3.11 minimum. Ruff for lint and format. `pytest` is the single backend test command.

---

### Task 1: Backend skeleton, settings and health endpoint

Establishes the package layout, configuration and test harness. Everything later depends on this, so it is deliberately the only task that touches project-level files.

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/src/kestrel/__init__.py`
- Create: `backend/src/kestrel/config.py`
- Create: `backend/src/kestrel/exceptions.py`
- Create: `backend/src/kestrel/main.py`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/test_health.py`
- Create: `.env.example`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `kestrel.config.Settings` with fields `source_db_path: Path`, `curated_db_path: Path`, `on_time_tolerance_minutes: int`, `near_expiry_days: int`, `fiscal_year_start_month: int`, `anthropic_api_key: str | None`, `cors_origins: list[str]`.
  - `kestrel.config.get_settings() -> Settings` (cached).
  - `kestrel.exceptions.AppError(code: str, message: str, status: int = 400)`.
  - `kestrel.main.create_app() -> FastAPI` and module-level `app`.

- [ ] **Step 1: Create the package directories**

```bash
cd backend
mkdir -p src/kestrel/{transform/steps,metrics,service,coldchain,quality,ask,reference} tests
touch src/kestrel/__init__.py src/kestrel/transform/__init__.py \
      src/kestrel/transform/steps/__init__.py src/kestrel/metrics/__init__.py \
      src/kestrel/service/__init__.py src/kestrel/coldchain/__init__.py \
      src/kestrel/quality/__init__.py src/kestrel/ask/__init__.py \
      src/kestrel/reference/__init__.py tests/__init__.py
```

`coldchain`, `quality`, `ask` and `reference` stay empty in this plan. They exist so the structure the spec describes is visible; later plans fill them.

- [ ] **Step 2: Write `backend/pyproject.toml`**

```toml
[project]
name = "kestrel"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "pydantic>=2.9",
    "pydantic-settings>=2.6",
]

[project.optional-dependencies]
dev = ["pytest>=8.3", "httpx>=0.27", "ruff>=0.7"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/kestrel"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]
```

- [ ] **Step 3: Write `backend/src/kestrel/config.py`**

```python
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Application settings.

    The three metric thresholds are deliberately root-level rather than
    per-domain: they are assumptions recorded in PRD section 9, and a
    reviewer must be able to find and change them in one place.
    """

    model_config = SettingsConfigDict(
        env_prefix="KESTREL_",
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    source_db_path: Path
    curated_db_path: Path = REPO_ROOT / "data" / "curated" / "kestrel_curated.db"

    # PRD A1. No documented SLA exists; exposed as configuration, not hard-coded.
    on_time_tolerance_minutes: int = 30
    # PRD A2. Applied uniformly across categories.
    near_expiry_days: int = 30
    # PRD 5.7. Financial year runs April to March.
    fiscal_year_start_month: int = 4

    anthropic_api_key: str | None = None
    cors_origins: list[str] = ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Write `backend/src/kestrel/exceptions.py`**

```python
from typing import Any


class AppError(Exception):
    """Base for errors that are safe to render to the client."""

    def __init__(
        self,
        code: str,
        message: str,
        status: int = 400,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.detail = detail or {}
```

- [ ] **Step 5: Write the failing test**

`backend/tests/test_health.py`:

```python
from fastapi.testclient import TestClient

from kestrel.main import create_app


def test_health_reports_ok():
    client = TestClient(create_app())
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
```

- [ ] **Step 6: Run the test to verify it fails**

```bash
cd backend && python -m pytest tests/test_health.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'kestrel.main'`.

- [ ] **Step 7: Write `backend/src/kestrel/main.py`**

```python
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from kestrel.config import get_settings
from kestrel.exceptions import AppError


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Kestrel Control Tower", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={
                "error": {"code": exc.code, "message": exc.message, "detail": exc.detail}
            },
        )

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
```

- [ ] **Step 8: Write `.env.example` at the repository root**

```bash
# Path to the assignment pack's source database. Required.
# Never modified by this application; opened read-only.
KESTREL_SOURCE_DB_PATH=../FDE_Assignment_Pack_Kestrel_v1.1/data/kestrel_ops.db

# Build output of the transform stage. Safe to delete and rebuild.
# KESTREL_CURATED_DB_PATH=data/curated/kestrel_curated.db

# PRD A1: on-time tolerance in minutes. No documented SLA; this is an assumption.
# KESTREL_ON_TIME_TOLERANCE_MINUTES=30

# PRD A2: near-expiry threshold in days of remaining shelf life.
# KESTREL_NEAR_EXPIRY_DAYS=30

# Optional. Enables natural-language intent resolution for ask-anything.
# Absent, the deterministic parser is used and nothing else changes.
# KESTREL_ANTHROPIC_API_KEY=
```

- [ ] **Step 9: Fix `.gitignore`**

The existing file ignores `*.sqlite` and `*.sqlite3` but not `*.db`, so the curated build output and any copy of the source database would be committed. Append:

```bash
cat >> ../.gitignore <<'EOF'

# SQLite databases: source data is supplied, curated data is built
*.db
*.db-wal
*.db-shm
*.db.tmp
data/curated/
EOF
```

Run from `backend/`, so the target is the repository-root `.gitignore`.

- [ ] **Step 10: Run the test to verify it passes**

```bash
cd backend && python -m pytest tests/test_health.py -v
```

Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add backend .gitignore .env.example
git commit -m "feat: backend skeleton with settings, error handling and health endpoint"
```

---

### Task 2: Database connections

Two connections with different rights. The read-only mode on the source is how NF6 stops being a matter of discipline.

**Files:**
- Create: `backend/src/kestrel/database.py`
- Create: `backend/tests/test_database.py`

**Interfaces:**
- Consumes: `kestrel.config.Settings`.
- Produces:
  - `kestrel.database.source_connection(path: Path) -> Iterator[Connection]` — context manager, read-only.
  - `kestrel.database.curated_connection(path: Path) -> Iterator[Connection]` — context manager, read-write, creates parent directories.
  - `kestrel.database.open_curated_readonly(path: Path) -> Connection` — used by request dependencies.
  - All connections set `row_factory = sqlite3.Row`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_database.py`:

```python
import sqlite3

import pytest

from kestrel.database import curated_connection, source_connection


def test_curated_connection_can_write(tmp_path):
    db = tmp_path / "nested" / "curated.db"
    with curated_connection(db) as conn:
        conn.execute("CREATE TABLE t (a INTEGER)")
        conn.execute("INSERT INTO t VALUES (1)")
        conn.commit()
    assert db.exists()


def test_source_connection_rejects_writes(tmp_path):
    db = tmp_path / "source.db"
    with curated_connection(db) as conn:
        conn.execute("CREATE TABLE t (a INTEGER)")
        conn.commit()

    with source_connection(db) as conn:
        assert conn.execute("SELECT count(*) FROM t").fetchone()[0] == 0
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO t VALUES (1)")


def test_rows_are_mappings(tmp_path):
    db = tmp_path / "curated.db"
    with curated_connection(db) as conn:
        conn.execute("CREATE TABLE t (a INTEGER)")
        conn.execute("INSERT INTO t VALUES (7)")
        row = conn.execute("SELECT a FROM t").fetchone()
        assert row["a"] == 7
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && python -m pytest tests/test_database.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'kestrel.database'`.

- [ ] **Step 3: Write `backend/src/kestrel/database.py`**

```python
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def _configure(conn: sqlite3.Connection) -> sqlite3.Connection:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def source_connection(path: Path) -> Iterator[sqlite3.Connection]:
    """Open the source database read-only.

    NF6 requires that source data is never mutated. Read-only mode is
    enforced by SQLite rather than by convention, so a write attempt raises
    instead of succeeding quietly. Only kestrel.transform may call this.
    """
    if not path.exists():
        raise FileNotFoundError(f"Source database not found: {path}")
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        yield _configure(conn)
    finally:
        conn.close()


@contextmanager
def curated_connection(path: Path) -> Iterator[sqlite3.Connection]:
    """Open the curated database read-write, creating its directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        yield _configure(conn)
    finally:
        conn.close()


def open_curated_readonly(path: Path) -> sqlite3.Connection:
    """Open the curated database read-only for serving requests.

    Caller closes. Used by FastAPI dependencies, which cannot use a
    context manager across the request boundary.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Curated database not found: {path}. "
            "Run `python -m kestrel.transform build` first."
        )
    return _configure(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True))
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd backend && python -m pytest tests/test_database.py -v
```

Expected: PASS, 3 tests.

- [ ] **Step 5: Commit**

```bash
git add backend/src/kestrel/database.py backend/tests/test_database.py
git commit -m "feat: read-only source and read-write curated connections"
```

---

### Task 3: Fiscal calendar

Split out because every period selector, quarter label and the landing view's headline depend on it, and getting April–March wrong would be invisible in a metric test.

**Files:**
- Create: `backend/src/kestrel/fiscal.py`
- Create: `backend/tests/test_fiscal.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `kestrel.fiscal.Period` — frozen dataclass with `start: date`, `end: date`, `label: str`.
  - `kestrel.fiscal.fiscal_year_and_quarter(day: date, start_month: int = 4) -> tuple[int, int]` — returns `(fiscal_year, quarter)` where fiscal year is the calendar year in which the year *ends* (April 2026 is FY27 Q1).
  - `kestrel.fiscal.quarter_period(fiscal_year: int, quarter: int, start_month: int = 4) -> Period`
  - `kestrel.fiscal.latest_complete_quarter(today: date, start_month: int = 4) -> Period`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_fiscal.py`:

```python
from datetime import date

from kestrel.fiscal import (
    fiscal_year_and_quarter,
    latest_complete_quarter,
    quarter_period,
)


def test_april_starts_q1_of_the_next_fiscal_year():
    assert fiscal_year_and_quarter(date(2026, 4, 1)) == (2027, 1)
    assert fiscal_year_and_quarter(date(2026, 6, 30)) == (2027, 1)


def test_march_is_q4_of_the_fiscal_year_that_ends_that_month():
    assert fiscal_year_and_quarter(date(2026, 3, 31)) == (2026, 4)


def test_january_is_q4_not_q1():
    """The trap this module exists to avoid: calendar Q1 is fiscal Q4."""
    assert fiscal_year_and_quarter(date(2026, 1, 15)) == (2026, 4)


def test_quarter_period_spans_april_to_june_and_is_labelled():
    period = quarter_period(2027, 1)
    assert period.start == date(2026, 4, 1)
    assert period.end == date(2026, 6, 30)
    assert period.label == "FY27 Q1"


def test_latest_complete_quarter_excludes_the_quarter_in_progress():
    # 15 August 2026 sits in FY27 Q2, so the last complete quarter is FY27 Q1.
    period = latest_complete_quarter(date(2026, 8, 15))
    assert period.label == "FY27 Q1"
    assert (period.start, period.end) == (date(2026, 4, 1), date(2026, 6, 30))


def test_latest_complete_quarter_wraps_back_across_the_fiscal_year():
    # 10 May 2026 is FY27 Q1, so the last complete quarter is FY26 Q4.
    period = latest_complete_quarter(date(2026, 5, 10))
    assert period.label == "FY26 Q4"
    assert (period.start, period.end) == (date(2026, 1, 1), date(2026, 3, 31))
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && python -m pytest tests/test_fiscal.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'kestrel.fiscal'`.

- [ ] **Step 3: Write `backend/src/kestrel/fiscal.py`**

```python
from calendar import monthrange
from dataclasses import dataclass
from datetime import date

DEFAULT_START_MONTH = 4  # PRD 5.7: financial year runs April to March.


@dataclass(frozen=True)
class Period:
    start: date
    end: date
    label: str


def fiscal_year_and_quarter(
    day: date, start_month: int = DEFAULT_START_MONTH
) -> tuple[int, int]:
    """Return (fiscal_year, quarter) for a date.

    The fiscal year is named for the calendar year in which it ends, which
    is how Kestrel's board refers to it: April 2026 falls in FY27 Q1.
    """
    offset = (day.month - start_month) % 12
    quarter = offset // 3 + 1
    fiscal_year = day.year + 1 if day.month >= start_month else day.year
    return fiscal_year, quarter


def quarter_period(
    fiscal_year: int, quarter: int, start_month: int = DEFAULT_START_MONTH
) -> Period:
    if not 1 <= quarter <= 4:
        raise ValueError(f"Quarter must be 1-4, got {quarter}")

    month_index = start_month + (quarter - 1) * 3
    start_year = fiscal_year - 1 + (month_index - 1) // 12
    start_month_no = (month_index - 1) % 12 + 1

    end_index = month_index + 2
    end_year = fiscal_year - 1 + (end_index - 1) // 12
    end_month_no = (end_index - 1) % 12 + 1

    return Period(
        start=date(start_year, start_month_no, 1),
        end=date(end_year, end_month_no, monthrange(end_year, end_month_no)[1]),
        label=f"FY{fiscal_year % 100:02d} Q{quarter}",
    )


def latest_complete_quarter(
    today: date, start_month: int = DEFAULT_START_MONTH
) -> Period:
    """The most recent quarter that has finished. The current one is excluded."""
    fiscal_year, quarter = fiscal_year_and_quarter(today, start_month)
    if quarter == 1:
        return quarter_period(fiscal_year - 1, 4, start_month)
    return quarter_period(fiscal_year, quarter - 1, start_month)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd backend && python -m pytest tests/test_fiscal.py -v
```

Expected: PASS, 6 tests.

- [ ] **Step 5: Commit**

```bash
git add backend/src/kestrel/fiscal.py backend/tests/test_fiscal.py
git commit -m "feat: April-March fiscal calendar with quarter periods"
```

---

### Task 4: Transform framework — schema, quality ledger and atomic build

The harness the transform steps plug into. No business rules yet; those arrive in Tasks 5 and 6.

**Files:**
- Create: `backend/src/kestrel/transform/schema.py`
- Create: `backend/src/kestrel/transform/ledger.py`
- Create: `backend/src/kestrel/transform/runner.py`
- Create: `backend/src/kestrel/transform/__main__.py`
- Create: `backend/tests/test_transform_runner.py`

**Interfaces:**
- Consumes: `kestrel.database.source_connection`, `curated_connection`; `kestrel.config.get_settings`.
- Produces:
  - `kestrel.transform.schema.CURATED_SCHEMA: str` — the full DDL.
  - `kestrel.transform.ledger.QualityLedger` with `record(rule_ref, rule_name, entity_type, entity_id, action, reason, source_system=None) -> None`, `counts() -> dict[str, int]`, `flush(conn, run_id) -> None`.
  - `kestrel.transform.ledger.Action` — string enum `EXCLUDED`, `REPAIRED`, `REJECTED`.
  - `kestrel.transform.runner.STEPS: list[Step]` where `Step` is a protocol with `name: str` and `run(src, dst, ledger) -> None`.
  - `kestrel.transform.runner.build(source: Path, curated: Path) -> BuildResult` with `BuildResult(run_id: str, table_counts: dict[str, int], ledger_counts: dict[str, int], duration_seconds: float)`.

- [ ] **Step 1: Write `backend/src/kestrel/transform/schema.py`**

```python
"""DDL for the curated database.

Exclusions are flags, not deletions (PRD 6.3). Excluded rows are retained
with the rule references that excluded them, so the default filter can be
lifted on request and the quality ledger can be reconciled against the
tables it describes.
"""

CURATED_SCHEMA = """
CREATE TABLE build_runs (
    run_id           TEXT PRIMARY KEY,
    started_at       TEXT NOT NULL,
    finished_at      TEXT,
    source_db_path   TEXT NOT NULL,
    table_counts     TEXT
);

CREATE TABLE quality_ledger (
    ledger_id        INTEGER PRIMARY KEY,
    run_id           TEXT NOT NULL,
    rule_ref         TEXT NOT NULL,
    rule_name        TEXT NOT NULL,
    entity_type      TEXT NOT NULL,
    entity_id        TEXT,
    action           TEXT NOT NULL CHECK (action IN ('EXCLUDED','REPAIRED','REJECTED')),
    reason           TEXT NOT NULL,
    source_system    TEXT,
    created_at       TEXT NOT NULL
);
CREATE INDEX ix_ledger_rule ON quality_ledger (rule_ref);

CREATE TABLE dim_region (
    region_id        INTEGER PRIMARY KEY,
    region_code      TEXT NOT NULL,
    region_name      TEXT NOT NULL
);

CREATE TABLE dim_outlet (
    outlet_id        INTEGER PRIMARY KEY,
    outlet_code      TEXT NOT NULL,
    outlet_name      TEXT NOT NULL,
    channel          TEXT,
    city_raw         TEXT,
    city             TEXT,
    region_id        INTEGER,
    route_id         INTEGER,
    salesperson_id   INTEGER,
    status           TEXT,
    closed_date      TEXT,
    is_excluded      INTEGER NOT NULL DEFAULT 0,
    exclusion_rules  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX ix_outlet_region ON dim_outlet (region_id);

CREATE TABLE fact_order_line (
    order_line_id        INTEGER PRIMARY KEY,
    order_id             INTEGER NOT NULL,
    order_date           TEXT NOT NULL,
    outlet_id            INTEGER NOT NULL,
    region_id            INTEGER,
    warehouse_id         INTEGER,
    route_id             INTEGER,
    product_id           INTEGER NOT NULL,
    order_status         TEXT,
    source_system        TEXT,
    qty_uom              TEXT,
    case_pack            INTEGER NOT NULL,
    ordered_qty_eaches   REAL NOT NULL,
    delivered_qty_eaches REAL NOT NULL,
    short_reason_code    TEXT,
    is_excluded          INTEGER NOT NULL DEFAULT 0,
    exclusion_rules      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX ix_fol_date ON fact_order_line (order_date);
CREATE INDEX ix_fol_outlet ON fact_order_line (outlet_id);
CREATE INDEX ix_fol_region ON fact_order_line (region_id);
"""
```

- [ ] **Step 2: Write `backend/src/kestrel/transform/ledger.py`**

```python
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from enum import StrEnum


class Action(StrEnum):
    EXCLUDED = "EXCLUDED"
    REPAIRED = "REPAIRED"
    REJECTED = "REJECTED"


class QualityLedger:
    """Accumulates quality events during a build, then writes them in one go.

    The ledger is a product surface, not engineering logging (PRD 6.4): it
    must state in counts what every other screen excludes.
    """

    def __init__(self) -> None:
        self._rows: list[tuple] = []
        self._counts: Counter[str] = Counter()

    def record(
        self,
        rule_ref: str,
        rule_name: str,
        entity_type: str,
        entity_id: str | int | None,
        action: Action,
        reason: str,
        source_system: str | None = None,
    ) -> None:
        self._rows.append(
            (
                rule_ref,
                rule_name,
                entity_type,
                None if entity_id is None else str(entity_id),
                str(action),
                reason,
                source_system,
                datetime.now(UTC).isoformat(timespec="seconds"),
            )
        )
        self._counts[rule_ref] += 1

    def counts(self) -> dict[str, int]:
        return dict(self._counts)

    def flush(self, conn: sqlite3.Connection, run_id: str) -> None:
        conn.executemany(
            """
            INSERT INTO quality_ledger (
                run_id, rule_ref, rule_name, entity_type, entity_id,
                action, reason, source_system, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [(run_id, *row) for row in self._rows],
        )
        self._rows.clear()
```

- [ ] **Step 3: Write `backend/src/kestrel/transform/runner.py`**

```python
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
    from kestrel.transform.steps import s00_reference, s20_orders

    return [s00_reference, s20_orders]


COUNTED_TABLES = ("dim_region", "dim_outlet", "fact_order_line", "quality_ledger")


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
```

- [ ] **Step 4: Write `backend/src/kestrel/transform/__main__.py`**

```python
import argparse
import sys

from kestrel.config import get_settings
from kestrel.transform.runner import build


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m kestrel.transform")
    parser.add_argument("command", choices=["build"])
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.command == "build":
        print(f"Source:  {settings.source_db_path}")
        print(f"Curated: {settings.curated_db_path}")
        result = build(settings.source_db_path, settings.curated_db_path)
        print(f"\nBuilt in {result.duration_seconds:.1f}s (run {result.run_id})")
        for table, count in result.table_counts.items():
            print(f"  {table:<20} {count:>9,}")
        print("\nQuality ledger by rule:")
        for rule, count in sorted(result.ledger_counts.items()):
            print(f"  {rule:<20} {count:>9,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Write the failing test**

`backend/tests/test_transform_runner.py`:

```python
import sqlite3

from kestrel.transform.ledger import Action, QualityLedger
from kestrel.transform.runner import build


class _FakeStep:
    name = "fake"

    def run(self, src, dst, ledger: QualityLedger) -> None:
        dst.execute("INSERT INTO dim_region VALUES (1, 'W', 'West')")
        ledger.record("X9", "fake rule", "region", 99, Action.EXCLUDED, "because")


def _make_source(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE regions (region_id INTEGER)")
    conn.commit()
    conn.close()


def test_build_creates_curated_db_with_ledger_rows(tmp_path):
    source = tmp_path / "source.db"
    curated = tmp_path / "out" / "curated.db"
    _make_source(source)

    result = build(source, curated, steps=[_FakeStep()])

    assert curated.exists()
    assert result.table_counts["dim_region"] == 1
    assert result.ledger_counts == {"X9": 1}

    conn = sqlite3.connect(curated)
    row = conn.execute(
        "SELECT rule_ref, action, reason FROM quality_ledger"
    ).fetchone()
    assert row == ("X9", "EXCLUDED", "because")


def test_build_is_idempotent(tmp_path):
    source = tmp_path / "source.db"
    curated = tmp_path / "curated.db"
    _make_source(source)

    first = build(source, curated, steps=[_FakeStep()])
    second = build(source, curated, steps=[_FakeStep()])

    assert first.table_counts == second.table_counts
    assert first.run_id != second.run_id


def test_failed_build_leaves_previous_curated_db_intact(tmp_path):
    source = tmp_path / "source.db"
    curated = tmp_path / "curated.db"
    _make_source(source)
    build(source, curated, steps=[_FakeStep()])

    class _Exploding:
        name = "boom"

        def run(self, src, dst, ledger):
            raise RuntimeError("step failed")

    try:
        build(source, curated, steps=[_Exploding()])
    except RuntimeError:
        pass

    conn = sqlite3.connect(curated)
    assert conn.execute("SELECT count(*) FROM dim_region").fetchone()[0] == 1
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_transform_runner.py -v
```

Expected: PASS, 3 tests. The steps are injected, so the not-yet-written step modules are not imported.

- [ ] **Step 7: Commit**

```bash
git add backend/src/kestrel/transform backend/tests/test_transform_runner.py
git commit -m "feat: transform runner with atomic build and quality ledger"
```

---

### Task 5: Transform step — reference data (N5, X1, X2, X5)

Builds `dim_region` and `dim_outlet`, applying the city mapping and the outlet exclusions. Every rule writes to the ledger.

Rules verified against the real data before writing this task: 42 outlets are `DELETED` with `is_deleted = 1`; 55 are `CLOSED`; three test outlets carry `outlet_code` beginning `TST`; two `gst_number` values are shared by more than one outlet. Outlet *names* repeat widely and legitimately, so name is not a duplicate key.

**Files:**
- Create: `backend/src/kestrel/transform/steps/s00_reference.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_step_reference.py`

**Interfaces:**
- Consumes: `QualityLedger`, `Action`.
- Produces:
  - Module-level `name = "s00_reference"` and `run(src, dst, ledger) -> None`.
  - `CITY_MAPPING: dict[str, str]` — the explicit, reviewable mapping table N5 requires.
  - Populated `dim_region` and `dim_outlet`.
  - `tests/conftest.py` fixture `source_db(tmp_path)` creating a miniature source database with the tables and columns used by Tasks 5 and 6.

- [ ] **Step 1: Write `backend/tests/conftest.py`**

```python
import sqlite3

import pytest

SOURCE_DDL = """
CREATE TABLE regions (
    region_id INTEGER, region_code TEXT, region_name TEXT
);
CREATE TABLE outlets (
    outlet_id INTEGER, outlet_code TEXT, outlet_name TEXT, channel TEXT,
    city TEXT, region_id INTEGER, route_id INTEGER, salesperson_id INTEGER,
    gst_number TEXT, status TEXT, closed_date TEXT, is_deleted INTEGER
);
CREATE TABLE products (
    product_id INTEGER, sku_code TEXT, case_pack INTEGER
);
CREATE TABLE orders (
    order_id INTEGER, outlet_id INTEGER, order_date TEXT, region_id INTEGER,
    route_id INTEGER, warehouse_id INTEGER, order_status TEXT, source_system TEXT
);
CREATE TABLE order_lines (
    order_line_id INTEGER, order_id INTEGER, product_id INTEGER,
    ordered_qty REAL, qty_uom TEXT, case_pack_at_order INTEGER,
    delivered_qty REAL, short_reason_code TEXT
);
"""


@pytest.fixture
def source_db(tmp_path):
    """A miniature source database mirroring the real column names.

    Deliberately hand-built rather than sampled, so tests never depend on
    the real database being present.
    """
    path = tmp_path / "source.db"
    conn = sqlite3.connect(path)
    conn.executescript(SOURCE_DDL)

    conn.executemany(
        "INSERT INTO regions VALUES (?, ?, ?)",
        [(1, "W", "West"), (2, "S", "South")],
    )
    conn.executemany(
        "INSERT INTO outlets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            # id, code,       name,        channel, city,        region, route, sp, gst,     status,   closed,       deleted
            (1, "OUT00001", "Good Mart", "GT", "Bengaluru", 1, 10, 5, "GST001", "ACTIVE", None, 0),
            (2, "OUT00002", "Fine Store", "MT", "Bangalore", 1, 10, 5, "GST002", "ACTIVE", None, 0),
            (3, "OUT00003", "Old Shop", "GT", "Mumbai", 1, 11, 6, "GST003", "CLOSED", "2025-06-30", 0),
            (4, "OUT00004", "Gone Ltd", "GT", "Mumbai", 1, 11, 6, "GST004", "DELETED", None, 1),
            (5, "TST00001", "ZZ_TEST_OUTLET", "GT", "Mumbai", 1, 11, 6, "GST005", "ACTIVE", None, 0),
            # Shares GST002 with outlet 2: the survivor is the lowest outlet_id.
            (6, "OUT00006", "Fine Store 2", "MT", "New Delhi", 2, 12, 7, "GST002", "ACTIVE", None, 0),
        ],
    )
    conn.executemany(
        "INSERT INTO products VALUES (?, ?, ?)",
        [(100, "SKU100", 12), (200, "SKU200", 6)],
    )
    conn.executemany(
        "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (900, 1, "2026-04-10", 1, 10, 1, "DELIVERED", "ERP_WEB"),
            (901, 2, "2026-04-11", 1, 10, 1, "PARTIAL", "SFA_MOBILE"),
            (902, 3, "2026-04-12", 1, 11, 1, "CANCELLED", "ERP_WEB"),
            (903, 4, "2026-05-01", 1, 11, 1, "DELIVERED", "PARTNER_API"),
            (904, 1, "2026-01-05", 1, 10, 1, "DELIVERED", "ERP_WEB"),
        ],
    )
    conn.executemany(
        "INSERT INTO order_lines VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            # 10 cases of 12 = 120 eaches ordered, 9 cases = 108 delivered
            (1, 900, 100, 10, "CASE", 12, 9, "STOCKOUT"),
            # 50 eaches ordered, 50 delivered
            (2, 900, 200, 50, "EACH", 6, 50, None),
            # 20 cases of 6 = 120 ordered, 60 delivered
            (3, 901, 200, 20, "CASE", 6, 10, "DAMAGE"),
            # cancelled order: must not reach the numerator or denominator
            (4, 902, 100, 100, "CASE", 12, 0, None),
            # deleted outlet
            (5, 903, 100, 5, "CASE", 12, 5, None),
            # out of period
            (6, 904, 100, 5, "CASE", 12, 5, None),
            # implausible case pack: falls back to the product master's 12
            (7, 900, 100, 1, "CASE", 0, 1, None),
        ],
    )
    conn.commit()
    conn.close()
    return path
```

- [ ] **Step 2: Write the failing test**

`backend/tests/test_step_reference.py`:

```python
import sqlite3

import pytest

from kestrel.transform.runner import build
from kestrel.transform.steps import s00_reference


@pytest.fixture
def curated(tmp_path, source_db):
    path = tmp_path / "curated.db"
    build(source_db, path, steps=[s00_reference])
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _outlet(conn, outlet_id):
    return conn.execute(
        "SELECT * FROM dim_outlet WHERE outlet_id = ?", (outlet_id,)
    ).fetchone()


def test_city_variants_are_mapped_to_a_canonical_form(curated):
    assert _outlet(curated, 1)["city"] == "Bengaluru"
    assert _outlet(curated, 2)["city"] == "Bengaluru"
    assert _outlet(curated, 2)["city_raw"] == "Bangalore"
    assert _outlet(curated, 6)["city"] == "Delhi"


def test_deleted_outlet_is_flagged_not_removed(curated):
    row = _outlet(curated, 4)
    assert row is not None, "excluded rows are retained (PRD 6.3)"
    assert row["is_excluded"] == 1
    assert "X1" in row["exclusion_rules"]


def test_test_outlet_is_excluded_by_code_prefix(curated):
    assert _outlet(curated, 5)["is_excluded"] == 1
    assert "X2" in _outlet(curated, 5)["exclusion_rules"]


def test_duplicate_gst_keeps_the_lowest_outlet_id_and_excludes_the_rest(curated):
    assert _outlet(curated, 2)["is_excluded"] == 0
    assert _outlet(curated, 6)["is_excluded"] == 1
    assert "X5" in _outlet(curated, 6)["exclusion_rules"]


def test_closed_outlet_is_retained_and_not_flagged(curated):
    """X3 is period-scoped, so it is applied at query time, not at build time."""
    row = _outlet(curated, 3)
    assert row["is_excluded"] == 0
    assert row["closed_date"] == "2025-06-30"


def test_every_exclusion_is_recorded_in_the_ledger(curated):
    counts = dict(
        curated.execute(
            "SELECT rule_ref, count(*) FROM quality_ledger GROUP BY rule_ref"
        ).fetchall()
    )
    assert counts["X1"] == 1
    assert counts["X2"] == 1
    assert counts["X5"] == 1
    assert counts["N5"] == 2  # Bangalore and New Delhi were repaired
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
cd backend && python -m pytest tests/test_step_reference.py -v
```

Expected: FAIL — `ImportError: cannot import name 's00_reference'`.

- [ ] **Step 4: Write `backend/src/kestrel/transform/steps/s00_reference.py`**

```python
"""Reference dimensions: regions and outlets.

Applies N5 (city canonicalisation), X1 (soft-deleted), X2 (test and
migration) and X5 (duplicate outlets). X3 (closed outlets) is deliberately
not applied here: it is period-scoped, so it belongs at query time.
"""

import sqlite3

from kestrel.transform.ledger import Action, QualityLedger

name = "s00_reference"

# N5: an explicit, reviewable mapping table. Derived from the distinct city
# values present in the source: Bangalore/Bengaluru and Delhi/New Delhi are
# the only genuine variants; every other value is already canonical.
CITY_MAPPING = {
    "Bangalore": "Bengaluru",
    "New Delhi": "Delhi",
}

TEST_OUTLET_CODE_PREFIX = "TST"


def _canonical_city(raw: str | None) -> str | None:
    if raw is None:
        return None
    return CITY_MAPPING.get(raw.strip(), raw.strip())


def run(src: sqlite3.Connection, dst: sqlite3.Connection, ledger: QualityLedger) -> None:
    dst.executemany(
        "INSERT INTO dim_region (region_id, region_code, region_name) VALUES (?, ?, ?)",
        src.execute("SELECT region_id, region_code, region_name FROM regions"),
    )

    outlets = src.execute(
        """
        SELECT outlet_id, outlet_code, outlet_name, channel, city, region_id,
               route_id, salesperson_id, gst_number, status, closed_date, is_deleted
        FROM outlets
        ORDER BY outlet_id
        """
    ).fetchall()

    # X5: a shared GST number identifies the same legal entity captured twice.
    # Outlet names repeat legitimately across the estate and are not a key.
    seen_gst: dict[str, int] = {}
    duplicates: dict[int, int] = {}
    for row in outlets:
        gst = row["gst_number"]
        if not gst:
            continue
        if gst in seen_gst:
            duplicates[row["outlet_id"]] = seen_gst[gst]
        else:
            seen_gst[gst] = row["outlet_id"]

    records = []
    for row in outlets:
        outlet_id = row["outlet_id"]
        rules: list[str] = []

        if row["is_deleted"] == 1 or row["status"] == "DELETED":
            rules.append("X1")
            ledger.record(
                "X1", "Soft-deleted outlet excluded", "outlet", outlet_id,
                Action.EXCLUDED, f"status={row['status']}, is_deleted={row['is_deleted']}",
            )

        if (row["outlet_code"] or "").startswith(TEST_OUTLET_CODE_PREFIX):
            rules.append("X2")
            ledger.record(
                "X2", "Test or migration outlet excluded", "outlet", outlet_id,
                Action.EXCLUDED, f"outlet_code={row['outlet_code']}",
            )

        if outlet_id in duplicates:
            rules.append("X5")
            ledger.record(
                "X5", "Duplicate outlet resolved to surviving entity", "outlet",
                outlet_id, Action.EXCLUDED,
                f"gst_number={row['gst_number']} already held by outlet_id="
                f"{duplicates[outlet_id]}",
            )

        city = _canonical_city(row["city"])
        if city != row["city"]:
            ledger.record(
                "N5", "City name mapped to canonical form", "outlet", outlet_id,
                Action.REPAIRED, f"{row['city']} -> {city}",
            )

        records.append(
            (
                outlet_id, row["outlet_code"], row["outlet_name"], row["channel"],
                row["city"], city, row["region_id"], row["route_id"],
                row["salesperson_id"], row["status"], row["closed_date"],
                1 if rules else 0, ",".join(rules),
            )
        )

    dst.executemany(
        """
        INSERT INTO dim_outlet (
            outlet_id, outlet_code, outlet_name, channel, city_raw, city,
            region_id, route_id, salesperson_id, status, closed_date,
            is_excluded, exclusion_rules
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        records,
    )
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd backend && python -m pytest tests/test_step_reference.py -v
```

Expected: PASS, 6 tests.

- [ ] **Step 6: Commit**

```bash
git add backend/src/kestrel/transform/steps/s00_reference.py \
        backend/tests/conftest.py backend/tests/test_step_reference.py
git commit -m "feat: reference transform step with city mapping and outlet exclusions"
```

---

### Task 6: Transform step — order lines normalised to eaches (N1, X4)

The rule that makes the case view and the each view of the same event unable to disagree (PRD §5.1).

**Files:**
- Create: `backend/src/kestrel/transform/steps/s20_orders.py`
- Create: `backend/tests/test_step_orders.py`

**Interfaces:**
- Consumes: `QualityLedger`, `Action`; `dim_outlet` must already be populated, so this step runs after `s00_reference`.
- Produces:
  - Module-level `name = "s20_orders"` and `run(src, dst, ledger) -> None`.
  - Populated `fact_order_line` with `ordered_qty_eaches`, `delivered_qty_eaches`, `case_pack`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_step_orders.py`:

```python
import sqlite3

import pytest

from kestrel.transform.runner import build
from kestrel.transform.steps import s00_reference, s20_orders


@pytest.fixture
def curated(tmp_path, source_db):
    path = tmp_path / "curated.db"
    build(source_db, path, steps=[s00_reference, s20_orders])
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _line(conn, line_id):
    return conn.execute(
        "SELECT * FROM fact_order_line WHERE order_line_id = ?", (line_id,)
    ).fetchone()


def test_case_lines_are_multiplied_by_case_pack(curated):
    row = _line(curated, 1)
    assert row["ordered_qty_eaches"] == 120  # 10 cases x 12
    assert row["delivered_qty_eaches"] == 108  # 9 cases x 12


def test_each_lines_are_left_alone(curated):
    row = _line(curated, 2)
    assert row["ordered_qty_eaches"] == 50
    assert row["delivered_qty_eaches"] == 50


def test_implausible_case_pack_falls_back_to_product_master(curated):
    row = _line(curated, 7)
    assert row["case_pack"] == 12
    assert row["ordered_qty_eaches"] == 12


def test_case_pack_fallback_is_recorded_as_a_repair(curated):
    rows = curated.execute(
        "SELECT entity_id, reason FROM quality_ledger WHERE rule_ref = 'N1'"
    ).fetchall()
    assert [r["entity_id"] for r in rows] == ["7"]


def test_cancelled_lines_are_flagged_not_removed(curated):
    row = _line(curated, 4)
    assert row is not None
    assert row["is_excluded"] == 1
    assert "X4" in row["exclusion_rules"]


def test_lines_on_excluded_outlets_are_flagged(curated):
    """Outlet 4 is soft-deleted, so its line inherits the exclusion."""
    row = _line(curated, 5)
    assert row["is_excluded"] == 1
    assert "X1" in row["exclusion_rules"]


def test_order_context_is_denormalised_onto_the_line(curated):
    row = _line(curated, 1)
    assert row["order_date"] == "2026-04-10"
    assert row["outlet_id"] == 1
    assert row["region_id"] == 1
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && python -m pytest tests/test_step_orders.py -v
```

Expected: FAIL — `ImportError: cannot import name 's20_orders'`.

- [ ] **Step 3: Write `backend/src/kestrel/transform/steps/s20_orders.py`**

```python
"""Order lines normalised to eaches.

N1: quantities are converted to eaches using the line-level case pack,
falling back to the product master where the line value is absent or
implausible (A5). Case-denominated figures are later derived from the each
figure, never computed independently, which is what guarantees the case
view and the each view of the same event cannot disagree (PRD 5.1).

X4: cancelled orders are flagged. Open orders are also flagged, as not yet
due (PRD 5.2).
"""

import sqlite3

from kestrel.transform.ledger import Action, QualityLedger

name = "s20_orders"

EXCLUDED_ORDER_STATUSES = {"CANCELLED": "X4", "OPEN": "X4"}

SELECT_LINES = """
SELECT l.order_line_id, l.order_id, l.product_id, l.ordered_qty, l.qty_uom,
       l.case_pack_at_order, l.delivered_qty, l.short_reason_code,
       o.order_date, o.outlet_id, o.region_id, o.warehouse_id, o.route_id,
       o.order_status, o.source_system,
       p.case_pack AS master_case_pack
FROM order_lines l
JOIN orders   o ON o.order_id   = l.order_id
JOIN products p ON p.product_id = l.product_id
ORDER BY l.order_line_id
"""


def _resolve_case_pack(row, ledger: QualityLedger) -> int:
    """A5: fall back to the product master where the line value is unusable."""
    line_pack = row["case_pack_at_order"]
    master_pack = row["master_case_pack"]
    if line_pack is not None and line_pack > 0:
        return int(line_pack)

    ledger.record(
        "N1", "Case pack fallback to product master", "order_line",
        row["order_line_id"], Action.REPAIRED,
        f"case_pack_at_order={line_pack} implausible, used product master "
        f"case_pack={master_pack}",
        row["source_system"],
    )
    return int(master_pack or 1)


def run(src: sqlite3.Connection, dst: sqlite3.Connection, ledger: QualityLedger) -> None:
    excluded_outlets = {
        row["outlet_id"]: row["exclusion_rules"]
        for row in dst.execute(
            "SELECT outlet_id, exclusion_rules FROM dim_outlet WHERE is_excluded = 1"
        )
    }

    records = []
    for row in src.execute(SELECT_LINES):
        case_pack = _resolve_case_pack(row, ledger)
        multiplier = case_pack if row["qty_uom"] == "CASE" else 1

        rules: list[str] = []
        status_rule = EXCLUDED_ORDER_STATUSES.get(row["order_status"])
        if status_rule:
            rules.append(status_rule)
            ledger.record(
                status_rule, "Order excluded from service measures", "order_line",
                row["order_line_id"], Action.EXCLUDED,
                f"order_status={row['order_status']}", row["source_system"],
            )

        outlet_rules = excluded_outlets.get(row["outlet_id"])
        if outlet_rules:
            rules.extend(r for r in outlet_rules.split(",") if r)

        records.append(
            (
                row["order_line_id"], row["order_id"], row["order_date"],
                row["outlet_id"], row["region_id"], row["warehouse_id"],
                row["route_id"], row["product_id"], row["order_status"],
                row["source_system"], row["qty_uom"], case_pack,
                (row["ordered_qty"] or 0) * multiplier,
                (row["delivered_qty"] or 0) * multiplier,
                row["short_reason_code"],
                1 if rules else 0, ",".join(dict.fromkeys(rules)),
            )
        )

    dst.executemany(
        """
        INSERT INTO fact_order_line (
            order_line_id, order_id, order_date, outlet_id, region_id,
            warehouse_id, route_id, product_id, order_status, source_system,
            qty_uom, case_pack, ordered_qty_eaches, delivered_qty_eaches,
            short_reason_code, is_excluded, exclusion_rules
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        records,
    )
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd backend && python -m pytest tests/test_step_orders.py -v
```

Expected: PASS, 7 tests.

- [ ] **Step 5: Run the full transform against the real database**

```bash
cd backend && python -m kestrel.transform build
```

Expected: a curated database is written, and the printed ledger summary shows non-zero counts for X1, X2, X4 and N5. **N1 is expected to be zero** — every `case_pack_at_order` in the supplied data matches the product master, so the A5 fallback is a defensive rule that never fires here. Report the count honestly rather than removing the rule; a rule with a zero count is information.

- [ ] **Step 6: Commit**

```bash
git add backend/src/kestrel/transform/steps/s20_orders.py backend/tests/test_step_orders.py
git commit -m "feat: normalise order line quantities to eaches with case pack fallback"
```

---

### Task 7: Fill rate metric

The canonical implementation. Every surface that reports a fill rate calls this and nothing else.

**Files:**
- Create: `backend/src/kestrel/metrics/types.py`
- Create: `backend/src/kestrel/metrics/fill_rate.py`
- Create: `backend/tests/test_metric_fill_rate.py`

**Interfaces:**
- Consumes: curated `fact_order_line` and `dim_outlet`; `kestrel.fiscal.Period`.
- Produces:
  - `kestrel.metrics.types.Unit` — `StrEnum` with `EACHES = "eaches"`, `CASES = "cases"`.
  - `kestrel.metrics.types.Grain` — `StrEnum` with `REGION`, `WAREHOUSE`, `ROUTE`, `OUTLET`.
  - `kestrel.metrics.types.MetricRequest(grain, period_start, period_end, period_label, unit=Unit.EACHES, region_id=None, include_excluded=False, limit=None, ascending=False)`.
  - `kestrel.metrics.types.MetricBasis(metric, period_start, period_end, period_label, unit, scope, exclusions_applied, unmeasured_count, source_row_count)`.
  - `kestrel.metrics.types.MetricRow(key, label, numerator, denominator, value)`.
  - `kestrel.metrics.types.MetricResult(headline, rows, basis)`.
  - `kestrel.metrics.fill_rate.compute(conn, request) -> MetricResult`.

- [ ] **Step 1: Write `backend/src/kestrel/metrics/types.py`**

```python
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
```

- [ ] **Step 2: Write the failing test**

`backend/tests/test_metric_fill_rate.py`:

```python
import sqlite3

import pytest

from kestrel.metrics import fill_rate
from kestrel.metrics.types import Grain, MetricRequest, Unit
from kestrel.transform.runner import build
from kestrel.transform.steps import s00_reference, s20_orders


@pytest.fixture
def conn(tmp_path, source_db):
    path = tmp_path / "curated.db"
    build(source_db, path, steps=[s00_reference, s20_orders])
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def _request(**overrides):
    defaults = dict(
        grain=Grain.OUTLET,
        period_start="2026-04-01",
        period_end="2026-06-30",
        period_label="FY27 Q1",
    )
    return MetricRequest(**{**defaults, **overrides})


def test_headline_is_delivered_over_ordered_in_eaches(conn):
    # Included lines in the period: line 1 (120/108), line 2 (50/50),
    # line 3 (120/60), line 7 (12/12). Lines 4, 5 and 6 are excluded.
    result = fill_rate.compute(conn, _request())
    assert result.basis.unit == Unit.EACHES
    assert result.headline == pytest.approx((108 + 50 + 60 + 12) / (120 + 50 + 120 + 12))


def test_cancelled_and_deleted_and_out_of_period_lines_are_absent(conn):
    result = fill_rate.compute(conn, _request())
    keys = {row.key for row in result.rows}
    assert keys == {"1", "2"}


def test_include_excluded_lifts_the_default_filter(conn):
    """PRD 6.3: exclusions are reversible on request, not a rebuild."""
    default = fill_rate.compute(conn, _request())
    lifted = fill_rate.compute(conn, _request(include_excluded=True))
    assert lifted.basis.source_row_count > default.basis.source_row_count
    assert lifted.basis.exclusions_applied == []


def test_case_unit_is_derived_from_the_each_figure(conn):
    result = fill_rate.compute(conn, _request(unit=Unit.CASES))
    expected = (108 / 12 + 50 / 6 + 60 / 6 + 12 / 12) / (
        120 / 12 + 50 / 6 + 120 / 6 + 12 / 12
    )
    assert result.headline == pytest.approx(expected)
    assert result.basis.unit == Unit.CASES


def test_region_scope_narrows_the_result_and_is_named_in_the_basis(conn):
    result = fill_rate.compute(conn, _request(region_id=2))
    assert result.basis.scope == "South"
    assert result.rows == []


def test_national_scope_is_the_default(conn):
    assert fill_rate.compute(conn, _request()).basis.scope == "National"


def test_basis_names_every_exclusion_rule_applied(conn):
    basis = fill_rate.compute(conn, _request()).basis
    assert basis.exclusions_applied == ["X1", "X2", "X3", "X4", "X5"]
    assert basis.metric == "fill_rate"
    assert basis.period_label == "FY27 Q1"


def test_ascending_limit_returns_the_worst_performers(conn):
    result = fill_rate.compute(conn, _request(ascending=True, limit=1))
    assert len(result.rows) == 1
    # Outlet 2 delivered 60 of 120; outlet 1 delivered 170 of 182.
    assert result.rows[0].key == "2"


def test_headline_is_none_when_nothing_matches(conn):
    result = fill_rate.compute(conn, _request(region_id=2))
    assert result.headline is None


def test_closed_outlet_is_excluded_from_a_period_after_its_closure(conn):
    """X3 is period-scoped: outlet 3 closed on 2025-06-30."""
    result = fill_rate.compute(conn, _request())
    assert "3" not in {row.key for row in result.rows}
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
cd backend && python -m pytest tests/test_metric_fill_rate.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'kestrel.metrics.fill_rate'`.

- [ ] **Step 4: Write `backend/src/kestrel/metrics/fill_rate.py`**

```python
"""Fill rate. PRD 5.2.

    fill_rate_eaches = SUM(delivered_qty_eaches) / SUM(ordered_qty_eaches)
    fill_rate_cases  = SUM(delivered_qty_eaches / case_pack)
                     / SUM(ordered_qty_eaches   / case_pack)

The case figure is derived from the each figure, never computed
independently, so the two views of the same event cannot disagree.

This module is the only implementation of fill rate. The dashboard and
ask-anything both call it, which is what makes G1 enforceable.
"""

import sqlite3

from kestrel.metrics.types import (
    Grain,
    MetricBasis,
    MetricRequest,
    MetricResult,
    MetricRow,
    Unit,
)

METRIC = "fill_rate"

# Grain resolves through this allowlist, never through string interpolation
# of user input. Values are (extra join, key expression, label expression).
#
# dim_outlet is always joined as `d2` regardless of grain, because the X3
# rule is period-scoped and must be applied at every grain. Outlet grain
# therefore needs no extra join and reads its label from d2.
_GRAINS: dict[Grain, tuple[str, str, str]] = {
    Grain.OUTLET: ("", "d2.outlet_id", "d2.outlet_name"),
    Grain.REGION: (
        "JOIN dim_region d ON d.region_id = f.region_id",
        "f.region_id",
        "d.region_name",
    ),
    Grain.WAREHOUSE: ("", "f.warehouse_id", "'Warehouse ' || f.warehouse_id"),
    Grain.ROUTE: ("", "f.route_id", "'Route ' || f.route_id"),
}

DEFAULT_EXCLUSIONS = ["X1", "X2", "X3", "X4", "X5"]


def _scope_name(conn: sqlite3.Connection, region_id: int | None) -> str:
    if region_id is None:
        return "National"
    row = conn.execute(
        "SELECT region_name FROM dim_region WHERE region_id = ?", (region_id,)
    ).fetchone()
    return row["region_name"] if row else f"Region {region_id}"


def compute(conn: sqlite3.Connection, request: MetricRequest) -> MetricResult:
    grain_join, key_source, label_source = _GRAINS[request.grain]

    if request.unit is Unit.CASES:
        numerator = "SUM(f.delivered_qty_eaches / f.case_pack)"
        denominator = "SUM(f.ordered_qty_eaches / f.case_pack)"
    else:
        numerator = "SUM(f.delivered_qty_eaches)"
        denominator = "SUM(f.ordered_qty_eaches)"

    filters = ["f.order_date BETWEEN ? AND ?"]
    params: list[object] = [
        request.period_start.isoformat(),
        request.period_end.isoformat(),
    ]

    if not request.include_excluded:
        filters.append("f.is_excluded = 0")
        # X3: closed outlets are excluded from periods after their closure
        # date, and retained in periods up to it.
        filters.append("(d2.closed_date IS NULL OR d2.closed_date >= ?)")
        params.append(request.period_start.isoformat())

    if request.region_id is not None:
        filters.append("f.region_id = ?")
        params.append(request.region_id)

    # dim_outlet is always joined so the period-scoped X3 rule can be applied
    # at every grain, not only at outlet grain.
    outlet_join = "JOIN dim_outlet d2 ON d2.outlet_id = f.outlet_id"

    order = "ASC" if request.ascending else "DESC"
    limit_sql = "LIMIT ?" if request.limit else ""
    # The filters and their parameters are shared by both queries below; only
    # the breakdown query appends a LIMIT parameter.
    where = " AND ".join(filters)
    breakdown_params = [*params, request.limit] if request.limit else params

    sql = f"""
        SELECT CAST({key_source} AS TEXT) AS key,
               {label_source} AS label,
               {numerator} AS numerator,
               {denominator} AS denominator,
               COUNT(*) AS row_count
        FROM fact_order_line f
        {outlet_join}
        {grain_join}
        WHERE {where}
        GROUP BY {key_source}, {label_source}
        HAVING {denominator} > 0
        ORDER BY (1.0 * {numerator} / {denominator}) {order}
        {limit_sql}
    """  # noqa: S608 - every fragment comes from the allowlist above

    rows = [
        MetricRow(
            key=row["key"],
            label=row["label"],
            numerator=row["numerator"],
            denominator=row["denominator"],
            value=row["numerator"] / row["denominator"],
        )
        for row in conn.execute(sql, breakdown_params)
    ]

    # The headline is recomputed over the whole scope rather than aggregated
    # from `rows`, because `rows` may be limited to the worst performers.
    headline_sql = f"""
        SELECT {numerator} AS numerator, {denominator} AS denominator,
               COUNT(*) AS row_count
        FROM fact_order_line f
        {outlet_join}
        WHERE {where}
    """  # noqa: S608
    totals = conn.execute(headline_sql, params).fetchone()

    denom = totals["denominator"] or 0
    headline = (totals["numerator"] / denom) if denom else None

    return MetricResult(
        headline=headline,
        rows=rows,
        basis=MetricBasis(
            metric=METRIC,
            period_start=request.period_start,
            period_end=request.period_end,
            period_label=request.period_label,
            unit=request.unit,
            scope=_scope_name(conn, request.region_id),
            exclusions_applied=[] if request.include_excluded else DEFAULT_EXCLUSIONS,
            unmeasured_count=0,
            source_row_count=totals["row_count"] or 0,
        ),
    )
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd backend && python -m pytest tests/test_metric_fill_rate.py -v
```

Expected: PASS, 10 tests.

- [ ] **Step 6: Run the whole backend suite**

```bash
cd backend && python -m pytest -v && python -m ruff check src tests
```

Expected: all tests pass, Ruff reports no issues.

- [ ] **Step 7: Commit**

```bash
git add backend/src/kestrel/metrics backend/tests/test_metric_fill_rate.py
git commit -m "feat: canonical fill rate metric returning figure with its basis"
```

---

### Task 8: Service domain — fill rate endpoint

**Files:**
- Create: `backend/src/kestrel/dependencies.py`
- Create: `backend/src/kestrel/service/schemas.py`
- Create: `backend/src/kestrel/service/router.py`
- Modify: `backend/src/kestrel/main.py`
- Create: `backend/tests/test_service_router.py`

**Interfaces:**
- Consumes: `kestrel.metrics.fill_rate.compute`, `kestrel.metrics.types.*`, `kestrel.fiscal.latest_complete_quarter`, `kestrel.database.open_curated_readonly`.
- Produces:
  - `kestrel.dependencies.get_curated_db()` — yields a curated connection, closes it after the request.
  - `kestrel.dependencies.resolve_period(period: str | None) -> Period` — accepts `"latest"` (default) or `"FY27Q1"` form.
  - `GET /api/service/fill-rate` with query parameters `grain`, `unit`, `region_id`, `period`, `include_excluded`, `limit`, `ascending`, returning `MetricResult` as JSON.
  - `kestrel.service.router.router` — an `APIRouter` with prefix `/api/service`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_service_router.py`:

```python
import pytest
from fastapi.testclient import TestClient

from kestrel.dependencies import get_curated_db
from kestrel.main import create_app
from kestrel.transform.runner import build
from kestrel.transform.steps import s00_reference, s20_orders


@pytest.fixture
def client(tmp_path, source_db):
    curated = tmp_path / "curated.db"
    build(source_db, curated, steps=[s00_reference, s20_orders])

    import sqlite3

    def _override():
        conn = sqlite3.connect(curated)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    app = create_app()
    app.dependency_overrides[get_curated_db] = _override
    return TestClient(app)


def test_fill_rate_returns_a_figure_with_its_basis(client):
    response = client.get(
        "/api/service/fill-rate", params={"grain": "outlet", "period": "FY27Q1"}
    )
    assert response.status_code == 200
    body = response.json()
    assert 0 < body["headline"] < 1
    basis = body["basis"]
    assert basis["unit"] == "eaches"
    assert basis["scope"] == "National"
    assert basis["period_label"] == "FY27 Q1"
    assert basis["exclusions_applied"] == ["X1", "X2", "X3", "X4", "X5"]


def test_unit_toggles_to_cases(client):
    response = client.get(
        "/api/service/fill-rate",
        params={"grain": "outlet", "period": "FY27Q1", "unit": "cases"},
    )
    assert response.json()["basis"]["unit"] == "cases"


def test_worst_performers_are_available_without_navigation(client):
    response = client.get(
        "/api/service/fill-rate",
        params={"grain": "outlet", "period": "FY27Q1", "ascending": True, "limit": 1},
    )
    rows = response.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["key"] == "2"


def test_unknown_grain_is_rejected(client):
    response = client.get(
        "/api/service/fill-rate", params={"grain": "salesperson", "period": "FY27Q1"}
    )
    assert response.status_code == 422


def test_malformed_period_returns_a_structured_error(client):
    response = client.get(
        "/api/service/fill-rate", params={"grain": "outlet", "period": "Q1-2026"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_PERIOD"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && python -m pytest tests/test_service_router.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'kestrel.dependencies'`.

- [ ] **Step 3: Write `backend/src/kestrel/dependencies.py`**

```python
import re
import sqlite3
from collections.abc import Iterator
from datetime import date

from fastapi import Query

from kestrel.config import get_settings
from kestrel.database import open_curated_readonly
from kestrel.exceptions import AppError
from kestrel.fiscal import Period, latest_complete_quarter, quarter_period

_PERIOD_PATTERN = re.compile(r"^FY(\d{2})Q([1-4])$", re.IGNORECASE)


def get_curated_db() -> Iterator[sqlite3.Connection]:
    settings = get_settings()
    try:
        conn = open_curated_readonly(settings.curated_db_path)
    except FileNotFoundError as exc:
        raise AppError(
            code="CURATED_DB_MISSING",
            message=str(exc),
            status=503,
        ) from exc
    try:
        yield conn
    finally:
        conn.close()


def resolve_period(
    period: str = Query(
        default="latest",
        description="'latest' for the most recent complete fiscal quarter, or FY27Q1.",
    ),
) -> Period:
    settings = get_settings()
    if period == "latest":
        return latest_complete_quarter(date.today(), settings.fiscal_year_start_month)

    match = _PERIOD_PATTERN.match(period)
    if not match:
        raise AppError(
            code="INVALID_PERIOD",
            message=f"Could not read period '{period}'. Use 'latest' or e.g. 'FY27Q1'.",
            detail={"supported": ["latest", "FY<yy>Q<1-4>"]},
        )
    return quarter_period(
        2000 + int(match.group(1)),
        int(match.group(2)),
        settings.fiscal_year_start_month,
    )
```

- [ ] **Step 4: Write `backend/src/kestrel/service/schemas.py`**

```python
"""Response models for the service domain.

MetricResult is re-exported rather than restated: the API contract is the
metric contract, so the basis cannot be dropped on the way out.
"""

from kestrel.metrics.types import MetricBasis, MetricResult, MetricRow

__all__ = ["MetricBasis", "MetricResult", "MetricRow"]
```

- [ ] **Step 5: Write `backend/src/kestrel/service/router.py`**

```python
import sqlite3

from fastapi import APIRouter, Depends, Query

from kestrel.dependencies import get_curated_db, resolve_period
from kestrel.fiscal import Period
from kestrel.metrics import fill_rate
from kestrel.metrics.types import Grain, MetricRequest, MetricResult, Unit

router = APIRouter(prefix="/api/service", tags=["service"])


@router.get("/fill-rate", response_model=MetricResult)
def get_fill_rate(
    grain: Grain = Grain.OUTLET,
    unit: Unit = Unit.EACHES,
    region_id: int | None = None,
    include_excluded: bool = False,
    ascending: bool = False,
    limit: int | None = Query(default=None, ge=1, le=500),
    period: Period = Depends(resolve_period),
    conn: sqlite3.Connection = Depends(get_curated_db),
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
```

- [ ] **Step 6: Register the router in `backend/src/kestrel/main.py`**

Add the import at the top of the file:

```python
from kestrel.service.router import router as service_router
```

and, immediately before `return app` in `create_app`:

```python
    app.include_router(service_router)
```

- [ ] **Step 7: Run the test to verify it passes**

```bash
cd backend && python -m pytest tests/test_service_router.py -v
```

Expected: PASS, 5 tests.

- [ ] **Step 8: Verify against the real database and check NF3**

```bash
cd backend && python -c "
import time, sqlite3
from datetime import date
from kestrel.config import get_settings
from kestrel.database import open_curated_readonly
from kestrel.fiscal import latest_complete_quarter
from kestrel.metrics import fill_rate
from kestrel.metrics.types import Grain, MetricRequest

conn = open_curated_readonly(get_settings().curated_db_path)
p = latest_complete_quarter(date(2026, 8, 15))
t = time.perf_counter()
r = fill_rate.compute(conn, MetricRequest(grain=Grain.OUTLET, period_start=p.start,
    period_end=p.end, period_label=p.label, ascending=True, limit=5))
print(f'{p.label}: {r.headline:.4f} over {r.basis.source_row_count:,} lines '
      f'in {time.perf_counter()-t:.3f}s')
for row in r.rows: print(f'  {row.label:<30} {row.value:.3f}')
"
```

Expected: a headline fill rate between 0 and 1, five worst outlets listed, and a query time well under NF3's two seconds. If it exceeds two seconds, add the index and re-measure before continuing.

- [ ] **Step 9: Commit**

```bash
git add backend/src/kestrel/dependencies.py backend/src/kestrel/service \
        backend/src/kestrel/main.py backend/tests/test_service_router.py
git commit -m "feat: fill rate endpoint with fiscal period and scope resolution"
```

---

### Task 9: Frontend scaffold and typed API client

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/api/types.ts`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/lib/scope.ts`

**Interfaces:**
- Consumes: `GET /api/service/fill-rate`.
- Produces:
  - `api/types.ts` — `Unit`, `Grain`, `MetricBasis`, `MetricRow`, `MetricResult`.
  - `api/client.ts` — `fetchFillRate(params: FillRateParams): Promise<MetricResult>`.
  - `lib/scope.ts` — `useScope()` returning `{ unit, regionId, period, setUnit, setRegionId }` backed by URL search params.

- [ ] **Step 1: Scaffold the project**

```bash
cd frontend 2>/dev/null || mkdir frontend && cd frontend
npm create vite@latest . -- --template react-ts
npm install
npm install @tanstack/react-query
```

Accept overwriting into the existing directory if prompted.

- [ ] **Step 2: Configure the dev proxy in `frontend/vite.config.ts`**

```typescript
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
});
```

The proxy means the frontend has no API base URL to configure, which removes one thing that can be wrong on a cold start (NF1).

- [ ] **Step 3: Write `frontend/src/api/types.ts`**

```typescript
export type Unit = "eaches" | "cases";
export type Grain = "region" | "warehouse" | "route" | "outlet";

/** What a figure was derived from. Displayed with every figure (C4.2). */
export interface MetricBasis {
  metric: string;
  period_start: string;
  period_end: string;
  period_label: string;
  unit: Unit;
  scope: string;
  exclusions_applied: string[];
  unmeasured_count: number;
  source_row_count: number;
}

export interface MetricRow {
  key: string;
  label: string;
  numerator: number;
  denominator: number;
  value: number | null;
}

export interface MetricResult {
  headline: number | null;
  rows: MetricRow[];
  basis: MetricBasis;
}
```

- [ ] **Step 4: Write `frontend/src/api/client.ts`**

```typescript
import type { Grain, MetricResult, Unit } from "./types";

export interface FillRateParams {
  grain?: Grain;
  unit?: Unit;
  regionId?: number | null;
  period?: string;
  ascending?: boolean;
  limit?: number;
  includeExcluded?: boolean;
}

export class ApiError extends Error {
  constructor(readonly code: string, message: string) {
    super(message);
  }
}

async function get<T>(path: string, params: Record<string, unknown>): Promise<T> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) query.set(key, String(value));
  }

  const response = await fetch(`${path}?${query}`);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(
      body?.error?.code ?? "UNKNOWN",
      body?.error?.message ?? `Request failed with ${response.status}`,
    );
  }
  return response.json() as Promise<T>;
}

export function fetchFillRate(params: FillRateParams = {}): Promise<MetricResult> {
  return get<MetricResult>("/api/service/fill-rate", {
    grain: params.grain ?? "outlet",
    unit: params.unit ?? "eaches",
    region_id: params.regionId,
    period: params.period ?? "latest",
    ascending: params.ascending,
    limit: params.limit,
    include_excluded: params.includeExcluded,
  });
}
```

- [ ] **Step 5: Write `frontend/src/lib/scope.ts`**

```typescript
import { useCallback, useEffect, useState } from "react";

import type { Unit } from "../api/types";

/**
 * Scope, unit and period live in the URL.
 *
 * One source of truth is what makes C5.3 hold — the selected scope applies
 * to every surface, including ask-anything — and it makes any view
 * shareable by pasting the address.
 */
export function useScope() {
  const [params, setParams] = useState(
    () => new URLSearchParams(window.location.search),
  );

  useEffect(() => {
    const onPop = () => setParams(new URLSearchParams(window.location.search));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const update = useCallback((key: string, value: string | null) => {
    const next = new URLSearchParams(window.location.search);
    if (value === null) next.delete(key);
    else next.set(key, value);
    window.history.pushState({}, "", `?${next}`);
    setParams(next);
  }, []);

  const regionParam = params.get("region");

  return {
    unit: (params.get("unit") as Unit) ?? "eaches",
    regionId: regionParam ? Number(regionParam) : null,
    period: params.get("period") ?? "latest",
    setUnit: (unit: Unit) => update("unit", unit),
    setRegionId: (id: number | null) => update("region", id === null ? null : String(id)),
  };
}
```

- [ ] **Step 6: Write `frontend/src/main.tsx`**

```typescript
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, staleTime: 60_000 } },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
);
```

- [ ] **Step 7: Verify the project builds**

```bash
cd frontend && npx tsc --noEmit && npm run build
```

Expected: no type errors and a successful build. `App.tsx` is still Vite's default at this point; Task 10 replaces it.

- [ ] **Step 8: Commit**

```bash
git add frontend
git commit -m "feat: Vite React frontend scaffold with typed API client and URL scope"
```

---

### Task 10: Landing view — fill rate card

The exception surface. What Divya sees on opening the product, with no navigation (G2, C2.3).

**Files:**
- Create: `frontend/src/features/landing/LandingView.tsx`
- Create: `frontend/src/features/service/FillRateCard.tsx`
- Create: `frontend/src/components/BasisLine.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/index.css`

**Interfaces:**
- Consumes: `fetchFillRate`, `useScope`, `MetricResult`.
- Produces: `LandingView`, `FillRateCard`, `BasisLine` React components.

- [ ] **Step 1: Write `frontend/src/components/BasisLine.tsx`**

```typescript
import type { MetricBasis } from "../api/types";

/**
 * Every figure renders the basis it was derived from.
 *
 * This is the whole point of the product: a number without its basis is
 * the contested number the control tower exists to replace.
 */
export function BasisLine({ basis }: { basis: MetricBasis }) {
  return (
    <p className="basis">
      {basis.period_label} ({basis.period_start} to {basis.period_end}) &middot;{" "}
      {basis.scope} &middot; {basis.unit} &middot;{" "}
      {basis.source_row_count.toLocaleString()} order lines
      {basis.exclusions_applied.length > 0 && (
        <> &middot; excludes {basis.exclusions_applied.join(", ")}</>
      )}
      {basis.unmeasured_count > 0 && (
        <> &middot; {basis.unmeasured_count.toLocaleString()} unmeasured</>
      )}
    </p>
  );
}
```

- [ ] **Step 2: Write `frontend/src/features/service/FillRateCard.tsx`**

```typescript
import { useQuery } from "@tanstack/react-query";

import { fetchFillRate } from "../../api/client";
import type { Unit } from "../../api/types";
import { BasisLine } from "../../components/BasisLine";

const percent = (value: number | null) =>
  value === null ? "—" : `${(value * 100).toFixed(1)}%`;

interface Props {
  unit: Unit;
  regionId: number | null;
  period: string;
  onUnitChange: (unit: Unit) => void;
}

export function FillRateCard({ unit, regionId, period, onUnitChange }: Props) {
  const { data, isPending, error } = useQuery({
    queryKey: ["fill-rate", unit, regionId, period],
    queryFn: () =>
      fetchFillRate({
        grain: "outlet",
        unit,
        regionId,
        period,
        ascending: true,
        limit: 5,
      }),
  });

  if (isPending) return <section className="card">Loading fill rate…</section>;
  if (error)
    return (
      <section className="card card--error">
        <h2>Fill rate unavailable</h2>
        <p>{(error as Error).message}</p>
      </section>
    );

  return (
    <section className="card">
      <header className="card__head">
        <h2>Fill rate</h2>
        <div className="toggle" role="group" aria-label="Unit of measure">
          {(["eaches", "cases"] as Unit[]).map((option) => (
            <button
              key={option}
              type="button"
              aria-pressed={unit === option}
              className={unit === option ? "is-active" : ""}
              onClick={() => onUnitChange(option)}
            >
              {option}
            </button>
          ))}
        </div>
      </header>

      <p className="headline">{percent(data.headline)}</p>
      <BasisLine basis={data.basis} />

      <h3>Worst performing outlets</h3>
      <table>
        <thead>
          <tr>
            <th scope="col">Outlet</th>
            <th scope="col">Fill rate</th>
            <th scope="col">Delivered</th>
            <th scope="col">Ordered</th>
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row) => (
            <tr key={row.key}>
              <td>{row.label}</td>
              <td>{percent(row.value)}</td>
              <td>{Math.round(row.numerator).toLocaleString()}</td>
              <td>{Math.round(row.denominator).toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
```

- [ ] **Step 3: Write `frontend/src/features/landing/LandingView.tsx`**

```typescript
import { FillRateCard } from "../service/FillRateCard";
import { useScope } from "../../lib/scope";

/**
 * The landing view is an exception surface, not a canvas (G2, C2.3).
 * Worst performers are visible on entry, with no drill-down required.
 */
export function LandingView() {
  const { unit, regionId, period, setUnit } = useScope();

  return (
    <main className="page">
      <header className="page__head">
        <h1>Kestrel Control Tower</h1>
        <p>Where we are losing service and where we are losing money.</p>
      </header>
      <FillRateCard
        unit={unit}
        regionId={regionId}
        period={period}
        onUnitChange={setUnit}
      />
    </main>
  );
}
```

- [ ] **Step 4: Replace `frontend/src/App.tsx`**

```typescript
import { LandingView } from "./features/landing/LandingView";

export default function App() {
  return <LandingView />;
}
```

- [ ] **Step 5: Replace `frontend/src/index.css`**

```css
:root {
  --ink: #14181d;
  --muted: #667085;
  --line: #e4e7ec;
  --bad: #b42318;
  font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  color: var(--ink);
}

body {
  margin: 0;
  background: #f7f8fa;
}

.page {
  max-width: 60rem;
  margin: 0 auto;
  padding: 2rem 1.5rem;
}

.page__head h1 {
  margin: 0 0 0.25rem;
  font-size: 1.5rem;
}
.page__head p {
  margin: 0 0 1.5rem;
  color: var(--muted);
}

.card {
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 0.5rem;
  padding: 1.25rem 1.5rem;
}
.card--error {
  border-color: var(--bad);
  color: var(--bad);
}
.card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.card h2 {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
}

.headline {
  margin: 0.5rem 0 0.25rem;
  font-size: 3rem;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.basis {
  margin: 0 0 1.5rem;
  color: var(--muted);
  font-size: 0.8125rem;
}

.toggle button {
  border: 1px solid var(--line);
  background: #fff;
  padding: 0.25rem 0.75rem;
  cursor: pointer;
  font: inherit;
  font-size: 0.8125rem;
}
.toggle button:first-child {
  border-radius: 0.25rem 0 0 0.25rem;
}
.toggle button:last-child {
  border-radius: 0 0.25rem 0.25rem 0;
  border-left: none;
}
.toggle button.is-active {
  background: var(--ink);
  color: #fff;
  border-color: var(--ink);
}

h3 {
  font-size: 0.8125rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--muted);
  margin: 0 0 0.5rem;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.875rem;
}
th {
  text-align: left;
  font-weight: 500;
  color: var(--muted);
}
th,
td {
  padding: 0.5rem 0;
  border-bottom: 1px solid var(--line);
}
td:not(:first-child),
th:not(:first-child) {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
```

- [ ] **Step 6: Verify it type-checks and builds**

```bash
cd frontend && npx tsc --noEmit && npm run build
```

Expected: no errors.

- [ ] **Step 7: Verify end to end by hand**

In one terminal:

```bash
cd backend && python -m uvicorn kestrel.main:app --reload
```

In another:

```bash
cd frontend && npm run dev
```

Open `http://localhost:5173`. Confirm: a fill-rate percentage renders; the basis line beneath it names the fiscal period, National scope, eaches, the order-line count and the exclusion rules; five worst outlets are listed without any navigation; and clicking "cases" changes both the figure and the basis line, and puts `?unit=cases` in the address bar.

- [ ] **Step 8: Commit**

```bash
git add frontend
git commit -m "feat: landing view with fill rate headline, basis and worst outlets"
```

---

### Task 11: Cold-start documentation

NF1 and success criterion 6: a person who has never seen the system starts it from the documentation alone.

**Files:**
- Modify: `README.md`
- Create: `DECISIONS.md`

**Interfaces:**
- Consumes: everything above.
- Produces: no code.

- [ ] **Step 1: Rewrite `README.md`**

```markdown
# Kestrel Provisions — Supply Chain Control Tower

Single, documented, reproducible answers for Kestrel Provisions' daily supply
chain operations.

Requirements defined in [PRD.md](PRD.md). Architecture in
[docs/superpowers/specs/2026-09-08-kestrel-portal-design.md](docs/superpowers/specs/2026-09-08-kestrel-portal-design.md).

## Prerequisites

- Python 3.11 or later
- Node.js 20 or later
- The assignment pack's `data/kestrel_ops.db`. It is not committed to this
  repository. The application opens it read-only and never modifies it.

## Cold start

### 1. Configure

```bash
cp .env.example .env
```

Edit `.env` and set `KESTREL_SOURCE_DB_PATH` to the absolute or relative path
of `kestrel_ops.db`.

### 2. Install and build the curated data

```bash
cd backend
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows PowerShell:
# .venv\Scripts\Activate.ps1

pip install -e ".[dev]"
python -m kestrel.transform build
```

The build prints the row counts it produced and the quality ledger counts by
rule. It is idempotent: re-run it as often as you like.

### 3. Run the API

```bash
python -m uvicorn kestrel.main:app --reload
```

API docs at http://127.0.0.1:8000/docs

### 4. Run the interface

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

## Tests

```bash
cd backend && python -m pytest
```

Tests build a miniature source database in a temporary directory, so they do
not need `kestrel_ops.db` to be present.

## How it fits together

```
kestrel_ops.db  ──(read-only)──>  transform  ──>  kestrel_curated.db
                                      │                   │
                                      └──> quality_ledger │
                                                          v
                                                       metrics
                                                          │
                                          FastAPI routers │  (no arithmetic)
                                                          v
                                                    React frontend
```

Reporting surfaces read the curated database only. Every figure is produced by
exactly one metric implementation and is returned with the basis on which it
was derived.
```

- [ ] **Step 2: Write `DECISIONS.md`**

One page maximum, per the assignment brief. Write it from what was actually built, not from intention. It must cover: what was built, what was deliberately not built and why, what was assumed where the brief was unclear or self-contradictory (in particular Divya asking for cases and Rakesh asking for eaches — PRD §5.2 resolves this in favour of eaches with cases as a toggle), what two more weeks would add, and what breaks first in production.

Do not write this section from the plan. Write it after Task 10 passes its manual verification, so the built/not-built line is factual.

- [ ] **Step 3: Verify the cold start on a clean checkout**

```bash
cd /tmp && rm -rf coldstart && git clone <repo-path> coldstart && cd coldstart
```

Then follow the README from step 1 with no other knowledge. Any command that
fails, or any step that requires knowledge not in the README, is an NF1 defect
and must be fixed in the README before committing.

- [ ] **Step 4: Commit**

```bash
git add README.md DECISIONS.md
git commit -m "docs: cold start instructions and decision record"
```

---

## Coverage against the spec

| Spec section | Task |
|---|---|
| §2 Technology decisions | 1, 2, 9 |
| §3 Repository layout | 1, 9 |
| §4 Layering rule | 2 (read-only source), 7 (metrics isolated), 8 (routers do no arithmetic) |
| §5 Configuration | 1 |
| §6.1 Execution model | 4 |
| §6.2 Idempotency | 4 |
| §6.3 Steps | 5, 6 (remaining steps: later plans) |
| §6.4 Exclusions as flags | 5, 6, 7 |
| §6.5 Quality ledger | 4, 5, 6 (ledger *screen*: later plan) |
| §7 Metric layer | 7 |
| §8 Ask-anything | Not in this plan — a later plan, per the spec's slice scope |
| §9 Frontend | 9, 10 |
| §10 Error handling | 1, 8 |
| §11 Testing | 1–8 (performance check in 8, step 8) |
| §12 Slice definition of done | 4–11 |
| §13 `.gitignore` fix | 1, step 9 |

**Deliberately deferred to later plans**, consistent with the spec's slice
scope: transform steps `s10_products`, `s30_deliveries`, `s40_inventory`,
`s50_returns`, `s90_integrity`; the OTIF, excursions, near-expiry and returns
metrics; the `coldchain`, `quality`, `ask` and `reference` domain packages;
and the region selector on the landing view (`useScope` already carries
`regionId`, and the endpoint already accepts it).
