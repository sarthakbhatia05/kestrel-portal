# OTIF (Slice 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add OTIF as the second live metric end to end — transform step, metric module, API endpoint, frontend card — following the same spine fill rate established in Slice 1.

**Architecture:** A new transform step (`s30_deliveries`) builds `fact_delivery` from the source `deliveries` table joined to the already-built `fact_order_line` (for eaches sums). A new metric module (`metrics/otif.py`) computes on-time/in-full/OTIF rates at query time, with the on-time tolerance as a request parameter (not baked into the curated table). A new router endpoint and frontend card follow the exact shape of fill rate's.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, sqlite3, pytest (backend). TypeScript, React, @tanstack/react-query, Vite (frontend).

**Spec:** [docs/superpowers/specs/2026-09-09-otif-slice-design.md](../specs/2026-09-09-otif-slice-design.md)

## Global Constraints

- PRD wins over this plan or the design doc where they disagree.
- `in_full` is computed exactly as PRD 5.3 states (`delivered_qty_eaches >= ordered_qty_eaches` per delivery) — it reports near-zero honestly in real data; do not add an undocumented tolerance to soften it.
- The source `deliveries.delay_minutes` column is never read. `delay_minutes` is always computed from `actual_arrival − planned_arrival`.
- `on_time_tolerance_minutes` defaults from `Settings` (already exists, `config.py:29`) but must be overridable per-request via `tolerance_minutes`, and the basis must state which tolerance produced a given figure.
- Existing 41 backend tests must stay green throughout; `ruff check src tests` stays clean.
- No arithmetic in routers — only the single metric module computes a figure.

---

### Task 1: Extend the test source fixture with `deliveries`

**Files:**
- Modify: `backend/tests/conftest.py`

**Interfaces:**
- Produces: a `deliveries` table in the `source_db` fixture, with rows keyed to the existing `orders`/`order_lines` fixture rows, for every later task's tests to build on.

- [ ] **Step 1: Add the `deliveries` table DDL and rows**

Add to `SOURCE_DDL` (after the `order_lines` table):

```sql
CREATE TABLE deliveries (
    delivery_id INTEGER, order_id INTEGER, planned_arrival TEXT,
    actual_arrival TEXT, delay_minutes INTEGER, route_id INTEGER,
    warehouse_id INTEGER
);
```

Add after the existing `order_lines` insert, before `conn.commit()`:

```python
    conn.executemany(
        "INSERT INTO deliveries VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            # order 900 (outlet 1): 30 min late, exactly on the default
            # tolerance boundary. Source delay_minutes says 0 -- wrong on
            # purpose, to prove the transform recomputes rather than trusts it.
            (1, 900, "2026-04-15 10:00:00", "2026-04-15 10:30:00", 0, 10, 1),
            # order 901 (outlet 2): 65 min late, in the alternate vendor
            # timestamp format (12-hour, DD-Mon-YYYY).
            (2, 901, "2026-04-16 09:00:00", "16-Apr-2026 10:05 AM", 5, 10, 1),
            # order 903 (outlet 4, soft-deleted / X1): on time. Only visible
            # with include_excluded=True.
            (3, 903, "2026-04-17 09:00:00", "2026-04-17 09:00:00", 999, 11, 1),
            # order 904 (outlet 1): unparseable actual_arrival -> N3, and
            # counted as unmeasured rather than dropped.
            (4, 904, "2026-05-01 12:00:00", "not-a-real-timestamp", None, 10, 1),
        ],
    )
```

- [ ] **Step 2: Run the existing suite to confirm nothing broke**

Run: `cd backend && python -m pytest -q`
Expected: all existing tests still PASS (adding a table and rows to the fixture doesn't touch any table earlier tests read).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/conftest.py
git commit -m "test: add deliveries table to the source fixture for OTIF"
```

---

### Task 2: Add `fact_delivery` to the curated schema

**Files:**
- Modify: `backend/src/kestrel/transform/schema.py`

**Interfaces:**
- Produces: `fact_delivery` table, columns `delivery_id, order_id, planned_arrival, delay_minutes, outlet_id, region_id, warehouse_id, route_id, ordered_qty_eaches, delivered_qty_eaches, is_excluded, exclusion_rules`.

- [ ] **Step 1: Add the table DDL**

Append inside the `CURATED_SCHEMA` string, after `fact_order_line`'s indexes:

```sql

CREATE TABLE fact_delivery (
    delivery_id           INTEGER PRIMARY KEY,
    order_id              INTEGER NOT NULL,
    planned_arrival       TEXT NOT NULL,
    delay_minutes         REAL,
    outlet_id             INTEGER NOT NULL,
    region_id             INTEGER,
    warehouse_id          INTEGER,
    route_id              INTEGER,
    ordered_qty_eaches    REAL NOT NULL,
    delivered_qty_eaches  REAL NOT NULL,
    is_excluded           INTEGER NOT NULL DEFAULT 0,
    exclusion_rules       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX ix_fd_planned ON fact_delivery (planned_arrival);
CREATE INDEX ix_fd_outlet ON fact_delivery (outlet_id);
CREATE INDEX ix_fd_region ON fact_delivery (region_id);
```

`delay_minutes` is nullable — it's `NULL` exactly when N3 fires (unparseable `actual_arrival`), which the metric layer reports as `unmeasured_count` rather than treating as on-time or excluding.

- [ ] **Step 2: Verify the schema executes cleanly**

Run: `cd backend && python -c "import sqlite3; from kestrel.transform.schema import CURATED_SCHEMA; sqlite3.connect(':memory:').executescript(CURATED_SCHEMA); print('ok')"`
Expected: prints `ok` with no errors.

- [ ] **Step 3: Commit**

```bash
git add backend/src/kestrel/transform/schema.py
git commit -m "feat: add fact_delivery table to the curated schema"
```

---

### Task 3: `s30_deliveries` transform step

**Files:**
- Create: `backend/src/kestrel/transform/steps/s30_deliveries.py`
- Test: `backend/tests/test_step_deliveries.py`

**Interfaces:**
- Consumes: `fact_order_line` (from `s20_orders`, already built), `dim_outlet.exclusion_rules` (from `s00_reference`).
- Produces: `run(src: sqlite3.Connection, dst: sqlite3.Connection, ledger: QualityLedger) -> None`, populating `fact_delivery`. Module-level `name = "s30_deliveries"`, matching the `Step` protocol in `transform/runner.py`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_step_deliveries.py`:

```python
import sqlite3

import pytest

from kestrel.transform.runner import build
from kestrel.transform.steps import s00_reference, s20_orders, s30_deliveries


@pytest.fixture
def curated(tmp_path, source_db):
    path = tmp_path / "curated.db"
    build(source_db, path, steps=[s00_reference, s20_orders, s30_deliveries])
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _delivery(conn, delivery_id):
    return conn.execute(
        "SELECT * FROM fact_delivery WHERE delivery_id = ?", (delivery_id,)
    ).fetchone()


def test_delay_is_computed_from_timestamps_not_the_source_column(curated):
    """Delivery 1's source delay_minutes says 0; actual is 30 min after planned."""
    row = _delivery(curated, 1)
    assert row["delay_minutes"] == pytest.approx(30.0)


def test_alternate_vendor_timestamp_format_parses(curated):
    """Delivery 2's actual_arrival is '16-Apr-2026 10:05 AM', not ISO."""
    row = _delivery(curated, 2)
    assert row["delay_minutes"] == pytest.approx(65.0)


def test_unparseable_actual_arrival_is_recorded_as_n3(curated):
    row = _delivery(curated, 4)
    assert row["delay_minutes"] is None

    ledger_rows = curated.execute(
        "SELECT entity_id, action, reason FROM quality_ledger WHERE rule_ref = 'N3'"
    ).fetchall()
    assert [r["entity_id"] for r in ledger_rows] == ["4"]
    assert ledger_rows[0]["action"] == "REJECTED"


def test_eaches_sums_come_from_fact_order_line(curated):
    """Order 900 (delivery 1): lines sum to 182 ordered, 170 delivered."""
    row = _delivery(curated, 1)
    assert row["ordered_qty_eaches"] == pytest.approx(182.0)
    assert row["delivered_qty_eaches"] == pytest.approx(170.0)


def test_excluded_outlet_flag_is_copied_from_dim_outlet(curated):
    """Delivery 3 belongs to outlet 4, which is soft-deleted (X1)."""
    row = _delivery(curated, 3)
    assert row["is_excluded"] == 1
    assert "X1" in row["exclusion_rules"]


def test_non_excluded_outlet_carries_no_rules(curated):
    row = _delivery(curated, 1)
    assert row["is_excluded"] == 0
    assert row["exclusion_rules"] == ""


def test_region_and_grain_fields_are_denormalised(curated):
    row = _delivery(curated, 1)
    assert row["outlet_id"] == 1
    assert row["region_id"] == 1
    assert row["route_id"] == 10
    assert row["warehouse_id"] == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_step_deliveries.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kestrel.transform.steps.s30_deliveries'`.

- [ ] **Step 3: Write the implementation**

Create `backend/src/kestrel/transform/steps/s30_deliveries.py`:

```python
"""Deliveries, evaluated for on-time performance. PRD 5.3.

N3: actual_arrival is supplied in two different timestamp formats (a
"two-vendor" split, per the Slice 1 design doc's step table). A value
matching neither is logged and stored as NULL, which the OTIF metric then
reports as unmeasured rather than silently dropping it from the denominator.

The source `delay_minutes` column is deliberately not read. Verified against
the real data, it disagrees with actual_arrival - planned_arrival on the
large majority of rows, with no discernible pattern. PRD 5.3 defines on-time
from the two timestamps directly, so this step computes delay itself.
"""

import sqlite3
from datetime import datetime

from kestrel.transform.ledger import Action, QualityLedger

name = "s30_deliveries"

# The two vendor formats seen in `actual_arrival`, tried in order. A value
# matching neither is unparseable (N3). `planned_arrival` is always the
# first (ISO) format in the source data.
_ACTUAL_ARRIVAL_FORMATS = ("%Y-%m-%d %H:%M:%S", "%d-%b-%Y %I:%M %p")
_PLANNED_ARRIVAL_FORMAT = "%Y-%m-%d %H:%M:%S"

SELECT_DELIVERIES = """
SELECT d.delivery_id, d.order_id, d.planned_arrival, d.actual_arrival,
       d.route_id, d.warehouse_id, o.outlet_id, o.region_id, o.source_system
FROM deliveries d
JOIN orders o ON o.order_id = d.order_id
ORDER BY d.delivery_id
"""


def _parse_actual(value: str) -> datetime | None:
    for fmt in _ACTUAL_ARRIVAL_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def run(src: sqlite3.Connection, dst: sqlite3.Connection, ledger: QualityLedger) -> None:
    outlet_exclusions = {
        row["outlet_id"]: row["exclusion_rules"]
        for row in dst.execute(
            "SELECT outlet_id, exclusion_rules FROM dim_outlet WHERE is_excluded = 1"
        )
    }
    eaches_by_order = {
        row["order_id"]: (row["ordered_eaches"], row["delivered_eaches"])
        for row in dst.execute(
            """
            SELECT order_id, SUM(ordered_qty_eaches) AS ordered_eaches,
                   SUM(delivered_qty_eaches) AS delivered_eaches
            FROM fact_order_line
            GROUP BY order_id
            """
        )
    }

    records = []
    for row in src.execute(SELECT_DELIVERIES):
        actual_dt = _parse_actual(row["actual_arrival"])
        if actual_dt is None:
            ledger.record(
                "N3", "Arrival timestamp unparseable", "delivery", row["delivery_id"],
                Action.REJECTED,
                f"actual_arrival={row['actual_arrival']!r} matched no known format",
                row["source_system"],
            )
            delay_minutes = None
        else:
            planned_dt = datetime.strptime(row["planned_arrival"], _PLANNED_ARRIVAL_FORMAT)
            delay_minutes = (actual_dt - planned_dt).total_seconds() / 60

        ordered_eaches, delivered_eaches = eaches_by_order.get(row["order_id"], (0.0, 0.0))
        rules = outlet_exclusions.get(row["outlet_id"], "")

        records.append(
            (
                row["delivery_id"], row["order_id"], row["planned_arrival"], delay_minutes,
                row["outlet_id"], row["region_id"], row["warehouse_id"], row["route_id"],
                ordered_eaches, delivered_eaches,
                1 if rules else 0, rules,
            )
        )

    dst.executemany(
        """
        INSERT INTO fact_delivery (
            delivery_id, order_id, planned_arrival, delay_minutes,
            outlet_id, region_id, warehouse_id, route_id,
            ordered_qty_eaches, delivered_qty_eaches, is_excluded, exclusion_rules
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        records,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_step_deliveries.py -v`
Expected: all 7 tests PASS.

- [ ] **Step 5: Lint and run the full suite**

Run: `cd backend && python -m ruff check src tests && python -m pytest -q`
Expected: ruff clean, all tests (old + new) PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/kestrel/transform/steps/s30_deliveries.py backend/tests/test_step_deliveries.py
git commit -m "feat: add s30_deliveries transform step (fact_delivery, N3)"
```

---

### Task 4: Wire `s30_deliveries` into the build runner

**Files:**
- Modify: `backend/src/kestrel/transform/runner.py`

**Interfaces:**
- Consumes: `kestrel.transform.steps.s30_deliveries` (Task 3).
- Produces: `_steps()` now returns `[s00_reference, s20_orders, s30_deliveries]`; `COUNTED_TABLES` includes `"fact_delivery"`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_transform_runner.py`:

```python
def test_default_steps_include_deliveries():
    from kestrel.transform.runner import _steps

    names = [step.name for step in _steps()]
    assert names == ["s00_reference", "s20_orders", "s30_deliveries"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && python -m pytest tests/test_transform_runner.py::test_default_steps_include_deliveries -v`
Expected: FAIL — `AssertionError`, actual list is `['s00_reference', 's20_orders']`.

- [ ] **Step 3: Update the runner**

In `backend/src/kestrel/transform/runner.py`, change:

```python
def _steps() -> list[Step]:
    """Imported lazily so the runner can be tested with no steps registered."""
    from kestrel.transform.steps import s00_reference, s20_orders

    return [s00_reference, s20_orders]
```

to:

```python
def _steps() -> list[Step]:
    """Imported lazily so the runner can be tested with no steps registered."""
    from kestrel.transform.steps import s00_reference, s20_orders, s30_deliveries

    return [s00_reference, s20_orders, s30_deliveries]
```

And change:

```python
COUNTED_TABLES = ("dim_region", "dim_outlet", "fact_order_line", "quality_ledger")
```

to:

```python
COUNTED_TABLES = (
    "dim_region", "dim_outlet", "fact_order_line", "fact_delivery", "quality_ledger",
)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && python -m pytest tests/test_transform_runner.py -v`
Expected: all tests PASS, including the new one.

- [ ] **Step 5: Commit**

```bash
git add backend/src/kestrel/transform/runner.py backend/tests/test_transform_runner.py
git commit -m "feat: register s30_deliveries as a default build step"
```

---

### Task 5: `OtifRow`/`OtifResult` types and `tolerance_minutes` on `MetricRequest`

**Files:**
- Modify: `backend/src/kestrel/metrics/types.py`

**Interfaces:**
- Produces: `OtifRow(key, label, due_count, on_time_count, in_full_count, otif_count, on_time_rate, in_full_rate, otif)`; `OtifResult(headline: OtifRow, rows: list[OtifRow], basis: MetricBasis)`; `MetricRequest.tolerance_minutes: int | None = None`; `MetricBasis.tolerance_minutes: int | None = None`.

- [ ] **Step 1: Add the fields and classes**

In `backend/src/kestrel/metrics/types.py`, add `tolerance_minutes` to `MetricRequest` (after `ascending`):

```python
    ascending: bool = False
    # PRD A1. Read only by otif.compute; other metrics ignore it. None means
    # "use the configured default" and is resolved by the router, not here,
    # so the basis can state the tolerance that actually produced a figure.
    tolerance_minutes: int | None = None
```

Add `tolerance_minutes` to `MetricBasis` (after `unmeasured_count`):

```python
    unmeasured_count: int = 0
    # PRD A1. Set only by otif.compute; other metrics leave it None.
    tolerance_minutes: int | None = None
```

Append at the end of the file, after `MetricResult`:

```python
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
```

- [ ] **Step 2: Verify it imports cleanly**

Run: `cd backend && python -c "from kestrel.metrics.types import OtifRow, OtifResult, MetricRequest, MetricBasis; print(MetricRequest.model_fields['tolerance_minutes'])"`
Expected: prints the field info with no errors.

- [ ] **Step 3: Run the full suite to confirm no regressions**

Run: `cd backend && python -m pytest -q`
Expected: all existing tests PASS (new optional fields with defaults don't change fill rate's behavior or its JSON shape's existing keys).

- [ ] **Step 4: Commit**

```bash
git add backend/src/kestrel/metrics/types.py
git commit -m "feat: add OtifRow/OtifResult and tolerance_minutes to metric types"
```

---

### Task 6: `metrics/otif.py`

**Files:**
- Create: `backend/src/kestrel/metrics/otif.py`
- Test: `backend/tests/test_metric_otif.py`

**Interfaces:**
- Consumes: `fact_delivery` (Task 3), `OtifRow`/`OtifResult`/`MetricRequest.tolerance_minutes` (Task 5).
- Produces: `compute(conn: sqlite3.Connection, request: MetricRequest) -> OtifResult`. `request.tolerance_minutes` must be set by the caller (not `None`) — this module does not resolve the config default; the router does (Task 7).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_metric_otif.py`:

```python
import sqlite3

import pytest

from kestrel.metrics import otif
from kestrel.metrics.types import Grain, MetricRequest
from kestrel.transform.runner import build
from kestrel.transform.steps import s00_reference, s20_orders, s30_deliveries


@pytest.fixture
def conn(tmp_path, source_db):
    path = tmp_path / "curated.db"
    build(source_db, path, steps=[s00_reference, s20_orders, s30_deliveries])
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def _request(**overrides):
    defaults = dict(
        grain=Grain.OUTLET,
        period_start="2026-04-01",
        period_end="2026-06-30",
        period_label="FY27 Q1",
        tolerance_minutes=30,
    )
    return MetricRequest(**{**defaults, **overrides})


def test_headline_counts_due_on_time_in_full_and_otif(conn):
    # Due: deliveries 1 (outlet 1), 2 (outlet 2), 4 (outlet 1). Delivery 3
    # (outlet 4) is excluded by default (X1).
    # On time (<=30 min): delivery 1 only (30 min, exactly on the boundary).
    # In full: delivery 4 only (order 904's line is fully delivered).
    # OTIF (both): none.
    result = otif.compute(conn, _request())
    assert result.headline.due_count == 3
    assert result.headline.on_time_count == 1
    assert result.headline.in_full_count == 1
    assert result.headline.otif_count == 0
    assert result.headline.on_time_rate == pytest.approx(1 / 3)
    assert result.headline.in_full_rate == pytest.approx(1 / 3)
    assert result.headline.otif == pytest.approx(0.0)


def test_unmeasured_deliveries_are_counted_not_dropped(conn):
    """Delivery 4's actual_arrival is unparseable -> unmeasured, PRD 5.3."""
    basis = otif.compute(conn, _request()).basis
    assert basis.unmeasured_count == 1
    assert basis.source_row_count == 3


def test_tolerance_boundary_is_inclusive(conn):
    """Delivery 1 is exactly 30 min late."""
    at_boundary = otif.compute(conn, _request(tolerance_minutes=30))
    assert at_boundary.headline.on_time_count == 1

    below_boundary = otif.compute(conn, _request(tolerance_minutes=29))
    assert below_boundary.headline.on_time_count == 0


def test_source_delay_minutes_column_is_ignored(conn):
    """Delivery 1's source delay_minutes says 0 (would be on time at any
    tolerance); the real, computed delay is 30. Confirms the metric reads
    the transform's computed value, not the untrustworthy source column."""
    result = otif.compute(conn, _request(tolerance_minutes=1))
    assert result.headline.on_time_count == 0


def test_outlet_grain_breaks_down_by_outlet(conn):
    result = otif.compute(conn, _request())
    by_key = {row.key: row for row in result.rows}
    assert by_key["1"].due_count == 2  # deliveries 1 and 4
    assert by_key["1"].on_time_count == 1
    assert by_key["1"].in_full_count == 1
    assert by_key["2"].due_count == 1  # delivery 2
    assert by_key["2"].on_time_count == 0


def test_include_excluded_surfaces_the_soft_deleted_outlet(conn):
    default = otif.compute(conn, _request())
    assert "4" not in {row.key for row in default.rows}

    lifted = otif.compute(conn, _request(include_excluded=True))
    row = next(r for r in lifted.rows if r.key == "4")
    assert row.due_count == 1
    assert row.otif == pytest.approx(1.0)
    assert lifted.basis.exclusions_applied == []


def test_national_scope_is_the_default(conn):
    assert otif.compute(conn, _request()).basis.scope == "National"


def test_region_scope_narrows_the_result(conn):
    result = otif.compute(conn, _request(region_id=2))
    assert result.basis.scope == "South"
    assert result.rows == []
    assert result.headline.due_count == 0
    assert result.headline.otif is None


def test_basis_states_the_tolerance_used(conn):
    basis = otif.compute(conn, _request(tolerance_minutes=45)).basis
    assert basis.tolerance_minutes == 45
    assert basis.metric == "otif"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_metric_otif.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kestrel.metrics.otif'`.

- [ ] **Step 3: Write the implementation**

Create `backend/src/kestrel/metrics/otif.py`:

```python
"""On-time in-full (OTIF). PRD 5.3.

    otif = COUNT(on_time AND in_full) / COUNT(due)

On-time and in-full are reported separately as well as combined (PRD C2.4):
a delivery can fail on either axis independently, and the two need
different fixes on the ground.

`in_full` reuses the eaches sums `s30_deliveries` already computed from
`fact_order_line` -- nothing here redoes case-pack conversion. `delay_minutes`
comes from that same step, computed from actual_arrival - planned_arrival
directly; the source delay_minutes column is not read (see that module's
docstring for why).

request.tolerance_minutes must already be resolved by the caller (the
router substitutes the configured default when the client omits it) so the
basis can state the tolerance that produced a given figure (PRD A1).
"""

import sqlite3

from kestrel.metrics.types import Grain, MetricBasis, MetricRequest, OtifResult, OtifRow

METRIC = "otif"

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

# X4 is structural for deliveries -- cancelled/open orders never produce a
# delivery row, so there is no per-row flag for it -- but it is still a real
# exclusion and is worth stating alongside the others, the way fill rate's
# basis does.
DEFAULT_EXCLUSIONS = ["X1", "X2", "X3", "X4", "X5"]

_ON_TIME = "(f.delay_minutes IS NOT NULL AND f.delay_minutes <= ?)"
_IN_FULL = "f.delivered_qty_eaches >= f.ordered_qty_eaches"


def _scope_name(conn: sqlite3.Connection, region_id: int | None) -> str:
    if region_id is None:
        return "National"
    row = conn.execute(
        "SELECT region_name FROM dim_region WHERE region_id = ?", (region_id,)
    ).fetchone()
    return row["region_name"] if row else f"Region {region_id}"


def _row(key: str, label: str, due: int, on_time: int, in_full: int, hit: int) -> OtifRow:
    return OtifRow(
        key=key,
        label=label,
        due_count=due,
        on_time_count=on_time,
        in_full_count=in_full,
        otif_count=hit,
        on_time_rate=(on_time / due) if due else None,
        in_full_rate=(in_full / due) if due else None,
        otif=(hit / due) if due else None,
    )


def compute(conn: sqlite3.Connection, request: MetricRequest) -> OtifResult:
    grain_join, key_source, label_source = _GRAINS[request.grain]
    tolerance = request.tolerance_minutes

    where_filters = ["date(f.planned_arrival) BETWEEN ? AND ?"]
    where_params: list[object] = [
        request.period_start.isoformat(),
        request.period_end.isoformat(),
    ]

    if not request.include_excluded:
        where_filters.append("f.is_excluded = 0")
        # X3: closed outlets are excluded from periods after their closure
        # date, same period-scoped rule fill rate applies.
        where_filters.append("(d2.closed_date IS NULL OR d2.closed_date >= ?)")
        where_params.append(request.period_start.isoformat())

    if request.region_id is not None:
        where_filters.append("f.region_id = ?")
        where_params.append(request.region_id)

    outlet_join = "JOIN dim_outlet d2 ON d2.outlet_id = f.outlet_id"
    where = " AND ".join(where_filters)

    order = "ASC" if request.ascending else "DESC"
    limit_sql = "LIMIT ?" if request.limit else ""

    # `?` order follows the SQL text left to right: the two tolerance
    # placeholders in SELECT come first, then the WHERE params, then LIMIT.
    select_params = [tolerance, tolerance]
    breakdown_params = [*select_params, *where_params, *([request.limit] if request.limit else [])]
    headline_params = [*select_params, *where_params]

    sql = f"""
        SELECT CAST({key_source} AS TEXT) AS key,
               {label_source} AS label,
               COUNT(*) AS due_count,
               SUM(CASE WHEN {_ON_TIME} THEN 1 ELSE 0 END) AS on_time_count,
               SUM(CASE WHEN {_IN_FULL} THEN 1 ELSE 0 END) AS in_full_count,
               SUM(CASE WHEN {_ON_TIME} AND {_IN_FULL} THEN 1 ELSE 0 END) AS otif_count
        FROM fact_delivery f
        {outlet_join}
        {grain_join}
        WHERE {where}
        GROUP BY {key_source}, {label_source}
        HAVING due_count > 0
        ORDER BY (1.0 * otif_count / due_count) {order}
        {limit_sql}
    """  # noqa: S608 - every fragment comes from the allowlist above; only `?` is parameterised

    rows = [
        _row(r["key"], r["label"], r["due_count"], r["on_time_count"], r["in_full_count"], r["otif_count"])
        for r in conn.execute(sql, breakdown_params)
    ]

    headline_sql = f"""
        SELECT COUNT(*) AS due_count,
               SUM(CASE WHEN {_ON_TIME} THEN 1 ELSE 0 END) AS on_time_count,
               SUM(CASE WHEN {_IN_FULL} THEN 1 ELSE 0 END) AS in_full_count,
               SUM(CASE WHEN {_ON_TIME} AND {_IN_FULL} THEN 1 ELSE 0 END) AS otif_count,
               SUM(CASE WHEN f.delay_minutes IS NULL THEN 1 ELSE 0 END) AS unmeasured_count
        FROM fact_delivery f
        {outlet_join}
        WHERE {where}
    """  # noqa: S608
    totals = conn.execute(headline_sql, headline_params).fetchone()

    headline = _row(
        "total", _scope_name(conn, request.region_id),
        totals["due_count"] or 0, totals["on_time_count"] or 0,
        totals["in_full_count"] or 0, totals["otif_count"] or 0,
    )

    return OtifResult(
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
            unmeasured_count=totals["unmeasured_count"] or 0,
            tolerance_minutes=tolerance,
            source_row_count=totals["due_count"] or 0,
        ),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_metric_otif.py -v`
Expected: all 9 tests PASS.

- [ ] **Step 5: Lint and run the full suite**

Run: `cd backend && python -m ruff check src tests && python -m pytest -q`
Expected: ruff clean, all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/kestrel/metrics/otif.py backend/tests/test_metric_otif.py
git commit -m "feat: add otif metric (on-time, in-full, and combined rates)"
```

---

### Task 7: `GET /api/service/otif` endpoint

**Files:**
- Modify: `backend/src/kestrel/service/router.py`
- Modify: `backend/tests/test_service_router.py`

**Interfaces:**
- Consumes: `otif.compute` (Task 6), `get_settings()` (`kestrel/config.py`, already exists).
- Produces: `GET /api/service/otif`, response model `OtifResult`.

- [ ] **Step 1: Extend the router test fixture and write the failing tests**

In `backend/tests/test_service_router.py`, change the import and fixture to include the deliveries step:

```python
from kestrel.transform.steps import s00_reference, s20_orders, s30_deliveries
```

```python
@pytest.fixture
def client(tmp_path, source_db):
    curated = tmp_path / "curated.db"
    build(source_db, curated, steps=[s00_reference, s20_orders, s30_deliveries])
    ...
```

Append these tests to the same file:

```python
def test_otif_returns_a_figure_with_its_basis(client):
    response = client.get(
        "/api/service/otif", params={"grain": "outlet", "period": "FY27Q1"}
    )
    assert response.status_code == 200
    body = response.json()
    basis = body["basis"]
    assert basis["metric"] == "otif"
    assert basis["scope"] == "National"
    assert basis["tolerance_minutes"] == 30  # config default, kestrel/config.py


def test_otif_tolerance_is_overridable_and_reflected_in_the_basis(client):
    response = client.get(
        "/api/service/otif",
        params={"grain": "outlet", "period": "FY27Q1", "tolerance_minutes": 5},
    )
    assert response.json()["basis"]["tolerance_minutes"] == 5


def test_otif_headline_reports_due_on_time_and_in_full_separately(client):
    response = client.get(
        "/api/service/otif", params={"grain": "outlet", "period": "FY27Q1"}
    )
    headline = response.json()["headline"]
    assert headline["due_count"] == 3
    assert headline["on_time_count"] == 1
    assert headline["in_full_count"] == 1
    assert headline["otif_count"] == 0


def test_otif_unknown_grain_is_rejected(client):
    response = client.get(
        "/api/service/otif", params={"grain": "salesperson", "period": "FY27Q1"}
    )
    assert response.status_code == 422


def test_otif_tolerance_out_of_range_is_rejected(client):
    response = client.get(
        "/api/service/otif",
        params={"grain": "outlet", "period": "FY27Q1", "tolerance_minutes": -1},
    )
    assert response.status_code == 422
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_service_router.py -v -k otif`
Expected: FAIL — `404 Not Found` (route doesn't exist yet).

- [ ] **Step 3: Add the endpoint**

In `backend/src/kestrel/service/router.py`, update the imports:

```python
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from kestrel.config import get_settings
from kestrel.dependencies import get_curated_db, resolve_period
from kestrel.fiscal import Period
from kestrel.metrics import fill_rate, otif
from kestrel.metrics.types import Grain, MetricRequest, MetricResult, OtifResult, Unit
```

Append the new endpoint after `get_fill_rate`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_service_router.py -v`
Expected: all tests (fill rate + OTIF) PASS.

- [ ] **Step 5: Lint and run the full suite**

Run: `cd backend && python -m ruff check src tests && python -m pytest -q`
Expected: ruff clean, all tests PASS (should be 41 + ~21 new = ~62).

- [ ] **Step 6: Commit**

```bash
git add backend/src/kestrel/service/router.py backend/tests/test_service_router.py
git commit -m "feat: add GET /api/service/otif endpoint"
```

---

### Task 8: Build the curated database and smoke-test the live endpoint

**Files:** none (verification only)

**Interfaces:** none

- [ ] **Step 1: Rebuild the curated database with the new step**

Run: `cd backend && python -m kestrel.transform build`
Expected: prints row counts including a non-zero `fact_delivery` count (~76,889 in the real data) and an N3 count (expected 0, per the design doc's finding).

- [ ] **Step 2: Start the API and query it manually**

Run: `cd backend && python -m uvicorn kestrel.main:app &` (or use the already-running dev server), then:

```bash
curl -s "http://127.0.0.1:8000/api/service/otif?grain=region" | head -c 2000
```

Expected: JSON with `headline.due_count > 0`, `headline.otif` close to 0 (per the design doc's finding that `in_full` almost never fires), and `basis.tolerance_minutes == 30`.

- [ ] **Step 3: No commit** (verification step only)

---

### Task 9: Frontend types and API client

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`

**Interfaces:**
- Produces: `OtifRow`, `OtifResult` types; `fetchOtif(params: OtifParams): Promise<OtifResult>`.

- [ ] **Step 1: Add the types**

In `frontend/src/api/types.ts`, add `tolerance_minutes` to `MetricBasis`:

```typescript
export interface MetricBasis {
  metric: string;
  period_start: string;
  period_end: string;
  period_label: string;
  unit: Unit;
  scope: string;
  exclusions_applied: string[];
  unmeasured_count: number;
  tolerance_minutes: number | null;
  source_row_count: number;
}
```

Append at the end of the file:

```typescript
export interface OtifRow {
  key: string;
  label: string;
  due_count: number;
  on_time_count: number;
  in_full_count: number;
  otif_count: number;
  on_time_rate: number | null;
  in_full_rate: number | null;
  otif: number | null;
}

export interface OtifResult {
  headline: OtifRow;
  rows: OtifRow[];
  basis: MetricBasis;
}
```

- [ ] **Step 2: Add the fetch function**

In `frontend/src/api/client.ts`, add the import and function:

```typescript
import type { Grain, MetricResult, OtifResult, Unit } from "./types";
```

```typescript
export interface OtifParams {
  grain?: Grain;
  regionId?: number | null;
  period?: string;
  ascending?: boolean;
  limit?: number;
  includeExcluded?: boolean;
  toleranceMinutes?: number;
}

export function fetchOtif(params: OtifParams = {}): Promise<OtifResult> {
  return get<OtifResult>("/api/service/otif", {
    grain: params.grain ?? "outlet",
    region_id: params.regionId,
    period: params.period ?? "latest",
    ascending: params.ascending,
    limit: params.limit,
    include_excluded: params.includeExcluded,
    tolerance_minutes: params.toleranceMinutes,
  });
}
```

- [ ] **Step 3: Verify the frontend still typechecks**

Run: `cd frontend && npx tsc --noEmit`
Expected: no type errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/client.ts
git commit -m "feat: add OTIF types and fetchOtif to the API client"
```

---

### Task 10: Generalise `BasisLine` for deliveries and tolerance

**Files:**
- Modify: `frontend/src/components/BasisLine.tsx`

**Interfaces:**
- Produces: `BasisLine({ basis, rowNoun = "order lines" })` — existing callers (`FillRateCard`) are unaffected since the prop is optional with the current default preserved.

- [ ] **Step 1: Update the component**

Replace the contents of `frontend/src/components/BasisLine.tsx`:

```tsx
import type { MetricBasis } from "../api/types";

/**
 * Every figure renders the basis it was derived from.
 *
 * This is the whole point of the product: a number without its basis is
 * the contested number the control tower exists to replace.
 */
export function BasisLine({
  basis,
  rowNoun = "order lines",
}: {
  basis: MetricBasis;
  rowNoun?: string;
}) {
  return (
    <p className="basis">
      {basis.period_label} ({basis.period_start} to {basis.period_end}) &middot;{" "}
      {basis.scope} &middot; {basis.unit} &middot;{" "}
      {basis.source_row_count.toLocaleString()} {rowNoun}
      {basis.exclusions_applied.length > 0 && (
        <> &middot; excludes {basis.exclusions_applied.join(", ")}</>
      )}
      {basis.tolerance_minutes != null && (
        <> &middot; {basis.tolerance_minutes} min tolerance</>
      )}
      {basis.unmeasured_count > 0 && (
        <> &middot; {basis.unmeasured_count.toLocaleString()} unmeasured</>
      )}
    </p>
  );
}
```

- [ ] **Step 2: Verify the frontend still typechecks and fill rate is unaffected**

Run: `cd frontend && npx tsc --noEmit`
Expected: no type errors. `FillRateCard` calls `<BasisLine basis={data.basis} />` with no `rowNoun`, so it keeps showing "order lines" exactly as before.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/BasisLine.tsx
git commit -m "feat: generalise BasisLine for row noun and tolerance display"
```

---

### Task 11: `OtifCard` component

**Files:**
- Create: `frontend/src/features/service/OtifCard.tsx`
- Modify: `frontend/src/index.css`

**Interfaces:**
- Consumes: `fetchOtif` (Task 9), `BasisLine` (Task 10).
- Produces: `OtifCard({ regionId, period }: { regionId: number | null; period: string })`.

- [ ] **Step 1: Add a small style for the sub-rate row**

Append to `frontend/src/index.css`:

```css
.submetrics {
  display: flex;
  gap: 1.5rem;
  margin: 0 0 1.25rem;
}
.submetrics dt {
  font-size: 0.6875rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--muted);
  margin: 0;
}
.submetrics dd {
  margin: 0;
  font-size: 1.125rem;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
```

- [ ] **Step 2: Write the component**

Create `frontend/src/features/service/OtifCard.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";

import { fetchOtif } from "../../api/client";
import { BasisLine } from "../../components/BasisLine";

const percent = (value: number | null) =>
  value === null ? "—" : `${(value * 100).toFixed(1)}%`;

interface Props {
  regionId: number | null;
  period: string;
}

export function OtifCard({ regionId, period }: Props) {
  const { data, isPending, error } = useQuery({
    queryKey: ["otif", regionId, period],
    queryFn: () =>
      fetchOtif({
        grain: "outlet",
        regionId,
        period,
        ascending: true,
        limit: 5,
      }),
  });

  if (isPending) return <section className="card">Loading OTIF…</section>;
  if (error)
    return (
      <section className="card card--error">
        <h2>OTIF unavailable</h2>
        <p>{(error as Error).message}</p>
      </section>
    );

  return (
    <section className="card">
      <header className="card__head">
        <h2>On-time in-full</h2>
      </header>

      <p className="headline">{percent(data.headline.otif)}</p>

      <dl className="submetrics">
        <div>
          <dt>On time</dt>
          <dd>{percent(data.headline.on_time_rate)}</dd>
        </div>
        <div>
          <dt>In full</dt>
          <dd>{percent(data.headline.in_full_rate)}</dd>
        </div>
      </dl>

      <BasisLine basis={data.basis} rowNoun="deliveries" />

      <h3>Worst performing outlets</h3>
      <table>
        <thead>
          <tr>
            <th scope="col">Outlet</th>
            <th scope="col">OTIF</th>
            <th scope="col">On time</th>
            <th scope="col">In full</th>
            <th scope="col">Due</th>
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row) => (
            <tr key={row.key}>
              <td>{row.label}</td>
              <td>{percent(row.otif)}</td>
              <td>{percent(row.on_time_rate)}</td>
              <td>{percent(row.in_full_rate)}</td>
              <td>{row.due_count.toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
```

- [ ] **Step 3: Verify it typechecks**

Run: `cd frontend && npx tsc --noEmit`
Expected: no type errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/service/OtifCard.tsx frontend/src/index.css
git commit -m "feat: add OtifCard component"
```

---

### Task 12: Wire `OtifCard` into the landing view

**Files:**
- Modify: `frontend/src/features/landing/LandingView.tsx`

**Interfaces:**
- Consumes: `OtifCard` (Task 11).

- [ ] **Step 1: Update the view**

Replace the contents of `frontend/src/features/landing/LandingView.tsx`:

```tsx
import { useScope } from "../../lib/scope";
import { FillRateCard } from "../service/FillRateCard";
import { OtifCard } from "../service/OtifCard";

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
      <OtifCard regionId={regionId} period={period} />
    </main>
  );
}
```

- [ ] **Step 2: Add spacing between cards**

Append to `frontend/src/index.css`:

```css
.page .card + .card {
  margin-top: 1.5rem;
}
```

- [ ] **Step 3: Manually verify in the browser**

Run: `cd frontend && npm run dev` (or use the already-running dev server), open `http://localhost:5173`.
Expected: fill rate card, then an OTIF card below it showing a headline percentage, on-time/in-full sub-rates, a basis line ending in "... deliveries · excludes ... · 30 min tolerance", and a worst-outlets table.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/landing/LandingView.tsx frontend/src/index.css
git commit -m "feat: show OtifCard on the landing view"
```

---

### Task 13: Documentation — DECISIONS.md and PROGRESS.md

**Files:**
- Modify: `DECISIONS.md`
- Modify: `PROGRESS.md`

**Interfaces:** none

- [ ] **Step 1: Add the OTIF findings to DECISIONS.md**

Read `DECISIONS.md` first to match its existing style (see the N1 zero-fire entry), then add an entry documenting:
- `in_full` never reaches 100% in the real data (max 99.37%), so OTIF and `in_full_rate` report near-zero honestly rather than inventing a softer threshold.
- The source `deliveries.delay_minutes` column is not used because it disagrees with `actual_arrival - planned_arrival` on ~87% of rows; `delay_minutes` is computed from the two timestamps directly.
- N3 (two-vendor arrival timestamp parsing) is defined but currently fires 0 times against the real data, the same pattern as N1's zero-fire in Slice 1.

- [ ] **Step 2: Update PROGRESS.md**

Update the status table (slices complete, test count, curated build row counts to include deliveries), move Slice 2 from "Next" into a completed section following the Slice 1 section's format (design → plan → tasks, what now runs end to end, changed from the plan while building if anything changed, found in the data), and update "Metrics live" / "Metrics not started" at the top.

- [ ] **Step 3: Final full-suite verification**

Run: `cd backend && python -m ruff check src tests && python -m pytest -q`
Expected: ruff clean, all tests PASS.

Run: `cd frontend && npx tsc --noEmit`
Expected: no type errors.

- [ ] **Step 4: Commit**

```bash
git add DECISIONS.md PROGRESS.md
git commit -m "docs: record OTIF slice completion and its data findings"
```
