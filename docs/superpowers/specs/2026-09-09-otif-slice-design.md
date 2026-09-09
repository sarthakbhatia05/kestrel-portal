# OTIF (On-Time In-Full) — Slice 2 Design

| | |
|---|---|
| Date | 9 September 2026 |
| Status | Approved |
| Implements | [PRD.md](../../../PRD.md) §5.3, C2.4 |
| Precedes | [2026-09-08-kestrel-portal-design.md](2026-09-08-kestrel-portal-design.md) §6.3's planned `s30_deliveries` step |

---

## 1. Purpose

Slice 2 of 4. Adds OTIF as the second live metric, following the same
transform → metric → API → frontend spine fill rate established in Slice 1.
Where this document and the PRD disagree, the PRD wins.

## 2. Findings that shape this design (verified against the real `kestrel_ops.db`)

- **`in_full` never fires.** PRD 5.3 defines "in full" as delivery-level fill
  rate = 100% in eaches. Across all 76,889 real deliveries, the maximum
  observed is 99.37%; zero reach 100%. OTIF and `in_full_rate` will therefore
  report honestly near-zero — not a bug, and not silently smoothed over. This
  gets its own line in DECISIONS.md, the same way N1's zero-fire was recorded
  in Slice 1.
- **The source `deliveries.delay_minutes` column is unreliable.** It disagrees
  with `actual_arrival − planned_arrival` on ~87% of rows, with no discernible
  pattern (not a fixed offset, not a format artifact). PRD 5.3 defines on-time
  from the two timestamps directly, so this column is not read at all — we
  compute our own `delay_minutes` in the transform step.
- **`actual_arrival` is stored in two vendor formats**: ISO
  (`2025-01-04 10:24:00`, 50,082 rows) and `DD-Mon-YYYY hh:mm AM/PM`
  (`04-Jan-2025 09:00 AM`, 26,807 rows). Both parse cleanly in the real data.
  This is rule **N3**, already anticipated in the Slice 1 design doc's step
  table. N3 is logged (as `REJECTED`) only when a value matches neither
  format — currently 0 rows, mirroring N1's zero-fire pattern.
- **`deliveries` is 1:1 with non-cancelled/non-open orders.** 76,889 delivery
  rows against 76,889 distinct order IDs; the 6,782 orders with no delivery
  row are exactly the CANCELLED (5,066) and OPEN (1,716) ones already excluded
  by X4 in `s20_orders`. `actual_arrival` is never NULL, so the PRD's
  "unmeasured" count (deliveries with no recorded arrival) is currently 0 —
  the rule stays, in case future data has gaps; it isn't hard-coded to zero.

## 3. Data foundation — `transform/steps/s30_deliveries.py`

New curated table:

```sql
CREATE TABLE fact_delivery (
    delivery_id           INTEGER PRIMARY KEY,
    order_id              INTEGER NOT NULL,
    planned_arrival       TEXT NOT NULL,   -- ISO, period field
    delay_minutes         REAL,            -- NULL when actual_arrival unparseable
    outlet_id             INTEGER NOT NULL,
    region_id             INTEGER,
    warehouse_id          INTEGER,
    route_id              INTEGER,
    ordered_qty_eaches    REAL NOT NULL,
    delivered_qty_eaches  REAL NOT NULL,
    is_excluded            INTEGER NOT NULL DEFAULT 0,
    exclusion_rules        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX ix_fd_planned ON fact_delivery (planned_arrival);
CREATE INDEX ix_fd_outlet ON fact_delivery (outlet_id);
CREATE INDEX ix_fd_region ON fact_delivery (region_id);
```

Runs after `s20_orders` (needs `fact_order_line` for eaches sums) and after
`s00_reference` (needs `dim_outlet.exclusion_rules`).

- `delay_minutes = actual_arrival − planned_arrival`, both parsed by trying
  the two known formats in turn; a value matching neither is logged as N3
  `REJECTED` and stored as `NULL`.
- `ordered_qty_eaches`/`delivered_qty_eaches` are `SUM(...)` from
  `fact_order_line` grouped by `order_id` — the same eaches figures fill rate
  already computes, not a second conversion.
- `is_excluded`/`exclusion_rules` copy the owning outlet's X1/X2/X3/X5 flags
  (same source `dim_outlet.exclusion_rules` join `s20_orders` uses), so OTIF's
  default scope matches fill rate's (PRD C5.3).
- No `is_on_time` column: the on-time tolerance is a query-time parameter
  (§5 below), so only the raw signed `delay_minutes` is stored.

## 4. Metric layer — `metrics/otif.py`

PRD C2.4 (Must) requires on-time and in-full to be separable, not just the
combined figure — so OTIF gets its own row/result shapes rather than reusing
`MetricRow`/`MetricResult`:

```python
class OtifRow(BaseModel):
    key: str
    label: str
    due_count: int
    on_time_count: int
    in_full_count: int
    otif_count: int              # on_time AND in_full
    on_time_rate: float | None
    in_full_rate: float | None
    otif: float | None

class OtifResult(BaseModel):
    headline: OtifRow
    rows: list[OtifRow]
    basis: MetricBasis           # reused as-is
```

`MetricRequest` gains one field, `tolerance_minutes: int | None = None`,
read only by `otif.compute`; other metrics ignore it. The router resolves
`None` to `settings.on_time_tolerance_minutes` before constructing the
request, so the basis line always states the tolerance that produced a given
figure, per PRD A1.

- Grain support matches fill rate: region / warehouse / route / outlet
  (PRD C2.4 lists the first three as the Must-have minimum; outlet is included
  for API consistency with fill rate, at no extra query cost — the row already
  carries `outlet_id`).
- Period field is `planned_arrival` date — a delivery belongs to the period
  it was *due* in, matching PRD 5.3's "deliveries due" denominator language.
- `on_time = delay_minutes IS NOT NULL AND delay_minutes <= tolerance_minutes`
  (early arrivals are always on time; unparseable timestamps are never on
  time and count toward `unmeasured`, per PRD 5.3).
- `in_full = delivered_qty_eaches >= ordered_qty_eaches`.
- Denominator (`due_count`) is every non-excluded `fact_delivery` row in
  scope — `deliveries` is already scoped to non-cancelled/non-open orders, so
  no additional status filter is needed.
- `unmeasured_count` in the basis = count of rows with `delay_minutes IS NULL`
  (currently 0, per §2).

## 5. API

`GET /api/service/otif` in `service/router.py`, mirroring `get_fill_rate`:

```python
@router.get("/otif", response_model=OtifResult)
def get_otif(
    period: Annotated[Period, Depends(resolve_period)],
    conn: Annotated[sqlite3.Connection, Depends(get_curated_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    grain: Grain = Grain.OUTLET,
    region_id: int | None = None,
    include_excluded: bool = False,
    ascending: bool = False,
    limit: int | None = Query(default=None, ge=1, le=500),
    tolerance_minutes: int | None = Query(default=None, ge=0, le=1440),
) -> OtifResult:
```

No arithmetic in the router — `tolerance_minutes` resolution (`None` →
config default) is the only router-side logic, same class of wiring as
`resolve_period`.

## 6. Frontend

- `api/types.ts`: add `OtifRow`, `OtifResult`.
- `api/client.ts`: add `getOtif(params)`.
- `features/service/OtifCard.tsx`: mirrors `FillRateCard.tsx` — headline
  OTIF %, on-time and in-full sub-rates shown alongside it (not hidden behind
  a toggle, since C2.4 requires them separable/visible), worst-performing
  outlets table.
- `LandingView.tsx`: renders `OtifCard` alongside `FillRateCard`, sharing the
  existing `useScope`/period plumbing — no changes to `lib/scope.ts` needed.

## 7. Testing

TDD throughout, per this project's established practice:

- `s30_deliveries`: a miniature source DB fixture with both arrival-timestamp
  formats and one deliberately unparseable value, to exercise N3 actually
  firing in a test (it's 0 in the real data).
- `metrics/otif.py`: fixture rows covering on-time/late/tolerance-boundary
  delay values and full/short deliveries, asserting `on_time_rate`,
  `in_full_rate`, `otif`, and `unmeasured_count` independently.
- `service/router.py`: parameter wiring, including `tolerance_minutes`
  defaulting and basis reflecting the resolved value.
- Existing 41 tests stay green; `ruff check` stays clean.

## 8. Out of scope for this slice

- Frontend tests (tracked as a known gap since Slice 1).
- Excursions (§5.4), near-expiry (§5.5), returns (§5.6), ask-anything (C4) —
  Slices 3 and 4.
