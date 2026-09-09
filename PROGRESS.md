# Progress log

A running record of what has been built, what was decided along the way, and
what is next. Working notes — the assignment's two required documents are
[README.md](README.md) and [DECISIONS.md](DECISIONS.md); this file is neither
and is not written for a grader.

Update it at the end of each slice, not continuously.

---

## Status at 2026-09-09

| | |
|---|---|
| Slices complete | 5 (fill rate, OTIF, returns, near-expiry, excursions) — ask-anything next |
| Backend tests | 132 passing, Ruff clean |
| Frontend | tsc and oxlint clean; no test suite yet (see Known gaps) |
| Curated build | 14.4s (warm) — 511,516 order lines, 76,889 deliveries, 14,000 returns, 131,040 inventory snapshots, 42,377 ledger rows |
| Fill rate query | 0.10s over 68,329 lines (NF3 allows 2s) |
| Returns query | 0.6s over 2,099 credit notes (NF3 allows 2s) |
| Near-expiry query | 0.01s over 1,680 batches (NF3 allows 2s) |
| Cold start | Verified from a clean `git clone`, README only |

**Metrics live:** fill rate (PRD §5.2), OTIF (PRD §5.3), returns (PRD §5.6), near-expiry (PRD §5.5), excursions (PRD §5.4).
**Metrics not started:** none — ask-anything (C4) is next, routing across all five.

**Original "Slice 3" (PROGRESS.md, 2026-09-09) bundled returns and
near-expiry.** Split into two on request: they don't share a fact table or
grain, unlike fill rate/OTIF which shared `fact_delivery`. Returns went
first as the rupee-denominated metric (PRD C3.4); near-expiry is next.

---

## Slice 1 — scaffold and fill rate (done, 2026-09-08)

Design [spec](docs/superpowers/specs/2026-09-08-kestrel-portal-design.md) →
[plan](docs/superpowers/plans/2026-09-08-scaffold-and-fill-rate-slice.md) →
11 tasks, TDD throughout, `1877f59`..`8c9569e`.

What now runs end to end:

- `python -m kestrel.transform build` reads `kestrel_ops.db` read-only and
  materialises `kestrel_curated.db` — atomic `.tmp` + rename, so a failed build
  leaves the previous one serving.
- Quality ledger populated by the build: X4 41,401 (cancelled/open orders),
  X1 42 (soft-deleted outlets), N5 27 (city names mapped), X5 4 (duplicate
  outlets), X2 3 (test outlets).
- One fill-rate implementation, returning the figure *with* its basis; the API
  and the landing view both call it and neither does arithmetic.
- Landing view: national headline, basis line, five worst outlets, eaches/cases
  toggle, scope in the URL.

**The contradiction in the brief is resolved, not picked.** Divya asked for
cases, Rakesh for eaches. Eaches is the default; cases is derived from the each
figure, so the two views cannot disagree. They currently read 85.6% and 85.9%.

### Changed from the plan while building

- **Relative DB paths now resolve against the repo root**, not the shell's cwd.
  `../data/kestrel_ops.db` silently meant two different files depending on
  whether you stood in `backend/` or the root. Found by running the build.
- **Router dependencies use `Annotated`** rather than `Depends()` in argument
  defaults, which Ruff flags (B008). Fixed rather than suppressed.
- **README build timing widened to 10–35 seconds.** 11s here, 31.7s on the
  clean clone; one number would have been wrong for most readers.

### Found in the data (verified, not assumed)

- **N1 never fires.** Every `case_pack_at_order` matches the product master, so
  the A5 fallback reports 0. Rule kept, zero reported.
- **X5 excludes 4 outlets, not 2.** Two shared GST numbers, but the groups are
  sized 4 and 2.
- **Duplicates must key on GST, not name.** 158 name+city pairs repeat
  legitimately; keying on name would have excluded 197 real outlets.
- **Test outlets are `outlet_code LIKE 'TST%'`.** All three are ACTIVE and not
  deleted, so a status rule would have missed them.
- **X3 (closed outlets) is period-scoped**, so it is applied at query time, not
  as a build-time flag. A shop that closed in June 2025 belongs in FY26 and not
  in FY27.

---

## Slice 2 — OTIF (done, 2026-09-09)

Design [spec](docs/superpowers/specs/2026-09-09-otif-slice-design.md) →
[plan](docs/superpowers/plans/2026-09-09-otif-slice.md) → 13 tasks, TDD
throughout.

What now runs end to end:

- `s30_deliveries` transform step, producing `fact_delivery` (76,889 rows)
  from the source `deliveries` table joined to `fact_order_line`'s eaches
  sums, so nothing here redoes case-pack conversion.
- One OTIF implementation, returning on-time, in-full and the combined
  figure separately (PRD C2.4), each with its own count and rate, not just
  the combined number.
- The on-time tolerance is a request parameter (`tolerance_minutes`),
  defaulting from config (`on_time_tolerance_minutes`, 30). The basis states
  the tolerance that produced a given figure.
- Landing view: an OTIF card below fill rate's, same shape — headline,
  on-time/in-full sub-rates, basis line, five worst outlets — sharing the
  existing scope/period plumbing with no changes to `useScope`.

### Found in the data (verified, not assumed)

- **`in_full` never fires.** PRD 5.3 defines "in full" as delivery-level
  fill rate = 100% in eaches. Across all 76,889 real deliveries, the maximum
  observed is 99.37%; zero reach 100%. OTIF and `in_full_rate` report near-
  zero honestly — implemented literally per spec, not softened. This is the
  headline finding of the slice, not a bug: it says something real about
  delivery execution that a smoothed number would have hidden.
- **The source `deliveries.delay_minutes` column is unreliable.** It
  disagrees with `actual_arrival - planned_arrival` on ~87% of rows, with no
  discernible pattern. Not read; `s30_deliveries` computes delay itself from
  the two timestamps, per the PRD 5.3 formula.
- **`actual_arrival` is genuinely two vendor formats**, not one with noise:
  ISO (the majority) and a 12-hour `DD-Mon-YYYY hh:mm AM/PM` format. Both
  parse cleanly. N3 (logged only when neither format matches) is 0 in the
  real data — the same zero-fire pattern N1 showed in Slice 1.
- **`deliveries` is exactly 1:1 with non-cancelled/non-open orders**
  (76,889 rows against 76,889 distinct order IDs), and `actual_arrival` is
  never NULL — so the "unmeasured" count PRD 5.3 asks for is 0 today. The
  rule stays in the query (`delay_minutes IS NULL`), not hard-coded to zero,
  in case future data has gaps.

---

## Slice 3 — returns (done, 2026-09-09)

Implemented directly (no design doc), following the fill-rate/OTIF pattern:
transform step → metric → router → landing card, TDD throughout.

What now runs end to end:

- `s40_returns` transform step, producing `fact_return` (14,000 rows) from
  `returns_credit_notes` joined to `orders` (region) and the new
  `dim_product` (category, built by `s00_reference`).
- `fact_order_line` gains `dispatched_value_inr` (`s20_orders`), priced off
  **delivered**, not ordered, quantity — a return can only happen against
  stock actually delivered, so it is the correct `dispatch_value`
  denominator for PRD 5.6, not the existing ordered-basis `line_value_inr`.
- One returns implementation, reporting `returns_rate` and a
  `cold_chain_rate` sub-rate (RT01/RT06) separately, each against the same
  dispatch-value denominator — the same separation OTIF applies to on-time
  and in-full.
- Landing view: a third card — headline rate, cold-chain sub-rate, worst
  five categories, basis line stating pending/rejected value alongside the
  rate (see below).

### Found in the data (verified, not assumed)

- **Only `APPROVED` credit notes count as leakage.** `status` also carries
  `PENDING` (3,509) and `REJECTED` (3,556) — neither resulted in an actual
  credit, so including them would overstate the rate with money never (or
  not yet) given back. Both are still surfaced in the basis as a count and
  value, so they are not silently invisible — the same principle as OTIF's
  `unmeasured_count`.
- **`return_qty` sign is inconsistent (N4): 900 of 14,000 rows are
  negative.** `credit_note_value_inr` itself is never negative — only the
  quantity needed normalising. Original sign kept for audit
  (`return_qty_orig_sign`).
- **Category and region breakdowns divide by a matching dispatch slice;
  reason cannot.** A delivered order line carries no "reason it might later
  be returned for," so reason-grain rows divide by the scope's total
  dispatch value — each reads as that reason's share of all dispatch value
  lost to returns, not a rate confined to that reason. Category and region
  both exist on dispatched lines too, so those grains divide correctly.
- **National returns_rate is ~0.03% of dispatch value** (₹6.6L credit
  against ₹233 crore dispatched, FY27 Q1) — plausible for FMCG credit-note
  leakage, not a flag.

### Changed from the plan while building

- **Curated build time roughly doubled, 29.7s → 61.7s**, from the added
  `dispatched_value_inr` computation over 511k order lines and the new
  returns step. Still comfortably under NF1's cold-start expectations;
  worth watching if a later slice adds another full-table computed column.

## Slice 4 — near-expiry (done, 2026-09-09)

Implemented directly (no design doc), following the returns pattern: source
table → transform step → metric → router → landing card, TDD throughout.

What now runs end to end:

- `s50_inventory` transform step, producing `fact_inventory_snapshot`
  (131,040 rows, all 8 weekly snapshots in the source) from
  `inventory_snapshots`, denormalising `region_id` from the new
  `dim_warehouse` and `category` from `dim_product` the same way returns
  denormalises onto `fact_return`.
- `dim_product` gains `case_pack` and `list_price_inr` (near-expiry's own
  columns, per the existing "gains columns only when a metric needs them"
  convention).
- One near-expiry implementation, reporting `near_expiry_rate` (available
  cases within the threshold over total available cases) and the rupee
  value at risk, by warehouse and category (PRD C3.3).
- Unlike every other metric, the request carries `snapshot_date` instead of
  a period range — inventory is a single weekly position, not a range to
  sum over (PRD 5.5) — and the basis states that date, defaulting to the
  latest snapshot present, never today.
- Landing view: a fourth card — headline rate, value at risk, worst five
  categories, basis line stating damaged/blocked value alongside the rate
  (see below).

### Found in the data (verified, not assumed)

- **The source's own `available_cases` doesn't exclude damaged or blocked
  stock**, only allocated (`on_hand_cases - allocated_cases`, confirmed
  across sampled rows). PRD 5.5 requires damaged and blocked to be excluded
  from available stock, so `fact_inventory_snapshot.available_cases` is
  recomputed as `on_hand - allocated - damaged - blocked` rather than
  copied from source. Damaged and blocked are still reported in the basis
  (counts and value), the same way returns' basis surfaces pending/rejected
  value.
- **No PRD 6.3 exclusion rule is scoped to warehouses or inventory** — all
  eight warehouses in the source are ACTIVE, and X1/X2/X3/X5 are all outlet
  rules — so, unlike every other metric, near-expiry has no
  `include_excluded`/`exclusions_applied` at all.
- **National near-expiry rate is ~14.2% of available stock** (85,827 of
  603,672 cases, ₹24.6 crore at risk, snapshot 2026-06-29) — high enough to
  be a genuine finding, not a rounding artefact; product shelf lives in the
  master range from single digits to hundreds of days, so a material tail
  is always inside 30 days of expiry.

### Changed from the plan while building

- **Prices for near-expiry value are the current product master
  (`list_price_inr`), not resolved as-at any order date (N6).** Stock
  sitting in a warehouse has no order event to resolve a price history
  window against, so N6's as-at-order-date rule doesn't apply here — a
  scope decision, not a gap.

## Slice 5 — excursions (done, 2026-09-09)

Implemented directly (no design doc), following the returns/near-expiry
pattern: extend the existing `s30_deliveries` step and `s00_reference` →
metric → router → landing card, TDD throughout.

What now runs end to end:

- `dim_product` gains `is_chilled` (own product-master column, unlike
  near-expiry's `case_pack`/`list_price_inr` which are also product-master
  columns — same "gains columns only when a metric needs them" convention).
  New `dim_route` dimension (route_code, route_name, warehouse_id), needed
  for PRD C3.2's route breakdown the way `dim_warehouse` already serves
  OTIF's warehouse grain.
- `fact_delivery` gains three columns from `s30_deliveries`:
  `temperature_excursion_flag` and `max_temp_celsius`, copied straight from
  the source (PRD 5.4: only a breach flag and peak temperature are
  captured, duration/severity must not be inferred), and `is_chilled`,
  which is *derived*, not copied — "a delivery is chilled if any line on it
  is a chilled or frozen product" (PRD 5.4), computed via the same
  `fact_order_line` join pattern the step already uses for eaches sums.
- One excursions implementation, reporting `excursion_rate` (chilled
  deliveries with a breach over all chilled deliveries) by month (C3.1, the
  headline breakdown) and by route/warehouse for concentration (C3.2) — a
  third grain set, distinct from fill rate/OTIF's region/warehouse/
  route/outlet and returns' category/reason/region.
- Landing view: a fifth card, in the money-loss group (PRD's own C3 groups
  excursions with returns and near-expiry as "cold chain and returns") —
  headline rate, chilled/breached sub-counts, worst five routes (the
  concentration view, C3.2), basis line. Month grain (C3.1) is reachable via
  the API's `grain=month` but not surfaced on the card, the same way
  returns/near-expiry expose `region`/`warehouse` grains only through the
  API, not the landing table.

### Found in the data (verified, not assumed)

- **Route and warehouse names in the source are generic** (`route_name` is
  literally `"Route <n>"` for all 140 routes). The metric's `COALESCE(...,
  'Route ' || route_id)` fallback — written defensively, mirroring OTIF's
  warehouse/route label fallback — never actually fires; the real column
  already reads that way. Not a bug, just a flatter source than the
  fixture's hand-written route names suggested.
- **National excursion rate is ~2.9% of chilled deliveries** (257 of 8,826,
  FY27 Q1) — plausible for reefer transit in Indian ambient conditions, not
  a flag. Worst routes concentrate at 8-14%, a real signal for targeted
  reefer maintenance rather than a fleet-wide problem.

### Changed from the plan while building

- **No new transform step file.** Unlike returns/near-expiry, which each
  introduced a new source table and step (`s40_returns`, `s50_inventory`),
  excursions reuses `deliveries` (already read by `s30_deliveries` for
  OTIF) and needs only new columns on the existing `fact_delivery` output,
  plus two new/extended reference dimensions. The metric's own file
  (`excursions.py`) is the only new module in the compute path.

## UI redesign, search, and a concurrency fix (done, 2026-09-09)

Not a slice — no new metric, done directly in chat (bounded path, no design
doc). Prompted by the landing view being functionally complete but visually
default: system font, flat grey-on-white, no hierarchy between the four
cards.

What changed:

- **Visual system**: IBM Plex Sans/Mono (numbers are always mono — an
  ops-console convention, not decoration), a slate-blue/red accent pair
  reflecting the page's own framing (service loss vs money loss) as a
  left-edge bar per card, sentence-case labels throughout (the previous
  uppercase-letterspaced section headers were the generic-page tell removed).
  The single worst row in every table is flagged (tint + left tick) rather
  than left for the reader to find — the exception-surface point (`LandingView.tsx`'s own
  comment on G2/C2.3) made visible, not just structurally true.
- **All four cards now share one grid** (`display: contents` on the
  service/money wrapper sections) so every card stretches to match the
  single tallest one, at every screen size — not just within its own row.
  Getting here took two false starts, both instructive: first pass left
  cards at natural height, which misaligned bottom edges across a row;
  stretching to fix that left the shorter card full of dead white space.
  The actual fix was structural — fill rate was the one card missing a
  submetrics row the other three had, so its card was genuinely shorter,
  not just differently laid out. It now shows delivered/ordered totals
  (`MetricResult.numerator`/`.denominator`, computed all along, just not
  previously returned), closing the gap honestly instead of papering over
  it with CSS.
- **Search**: each table's `q` param does a case-insensitive substring
  match against the full outlet/category set, applied before ranking and
  the worst-5 limit — not a client-side filter over the 5 rows already
  shown. `fill_rate`/`otif` do it in SQL (`HAVING label LIKE ?`);
  `returns`/`near_expiry` already built their rows in Python, so it's a
  list-comprehension filter there instead. Frontend debounces 300ms.
- **Info tooltips**: one plain-language sentence per metric title, on
  hover/focus, sourced from the PRD's own definitions.

### Found while verifying, not designing

- **The curated DB connection broke under concurrent requests** — roughly
  10–25% of page loads threw 500s, present before any of today's changes
  and not noticed until stress-testing the new UI surfaced it repeatedly.
  `get_curated_db` opens one `sqlite3.Connection` per request, but FastAPI
  resolves a sync dependency and runs the sync endpoint body via
  `run_in_threadpool`, which can pick different worker threads for the same
  request; `sqlite3.Connection` defaults to rejecting exactly that. Fixed
  with `check_same_thread=False` on `open_curated_readonly` only (not
  `curated_connection`/`source_connection`, which are single-threaded build
  code) — safe here because the connection is still only ever used
  sequentially within one request, never concurrently from two threads at
  once. Confirmed with 60 concurrent requests across all four endpoints,
  all 200; regression test added in `test_database.py`.

## Next

**Slice 6 — ask-anything (C4).** All five PRD metrics are now live, which is
the precondition this slice was deliberately waiting on: with one metric to
route to, an intent resolver has nothing to choose between and the guarantee
that matters — the LLM resolves intent into a validated request, never sees a
row, never emits a number — is unconvincing. With five metrics it is the
sharpest thing in the build.

**Small, fold into a slice rather than planning separately:** the quality-ledger
screen (the table is already populated) and the region selector (`useScope`
carries `regionId`, the endpoint accepts it).

---

## Known gaps

- `unmeasured_count` is now live (OTIF's unparseable-arrival case) but reads 0
  against the real data, since `actual_arrival` is never NULL there.
- No frontend tests yet. The API contract is typed by hand in `api/types.ts`
  rather than generated from the OpenAPI schema, so the two can drift.
- Transform is a full rebuild. Fine at 511k lines; not at 50 million.
- `coldchain/`, `quality/`, `ask/` and `reference/` are empty packages that
  exist to make the intended structure visible.
