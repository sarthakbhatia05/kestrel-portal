# Progress log

A running record of what has been built, what was decided along the way, and
what is next. Working notes — the assignment's two required documents are
[README.md](README.md) and [DECISIONS.md](DECISIONS.md); this file is neither
and is not written for a grader.

Update it at the end of each slice, not continuously.

---

## Status at 2026-09-10

| | |
|---|---|
| Slices complete | 8 (fill rate, OTIF, returns, near-expiry, excursions, ask-anything, scope + investigation, data quality) |
| Backend tests | 286 passing, Ruff clean |
| Quality view query | 0.12s national, 0.19s one region (NF3 allows 2s) |
| Frontend | tsc and oxlint clean; no test suite yet (see Known gaps) |
| Curated build | 14.4s (warm) — 511,516 order lines, 76,889 deliveries, 14,000 returns, 131,040 inventory snapshots, 42,377 ledger rows |
| Fill rate query | 0.10s over 68,329 lines (NF3 allows 2s) |
| Returns query | 0.6s over 2,099 credit notes (NF3 allows 2s) |
| Near-expiry query | 0.01s over 1,680 batches (NF3 allows 2s) |
| Cold start | Verified from a clean `git clone`, README only |

**Metrics live:** fill rate (PRD §5.2), OTIF (PRD §5.3), returns (PRD §5.6), near-expiry (PRD §5.5), excursions (PRD §5.4).
**Ask-anything (C4)** routes plain-English questions across all five, and
investigates "why" questions by taking several measurements in sequence.
**Scope** is selectable: region and period (quarters and months in the UI;
weeks and explicit ranges accepted in a question).
**Data quality** (PRD 6.4) states, for the selected scope, what each
measure excludes and under which rule, with the ledger entries behind it.

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

## Slice 6 — ask-anything (done, 2026-09-09)

Implemented directly (no design doc), TDD throughout, in the established
order: types → pure modules → resolver against a fake model → dispatch →
endpoint → frontend surface.

**No vector database, no RAG.** Vector search answers "which document is
relevant"; there is no unstructured corpus here, and retrieval would put
rows in front of a model that must never see one. The problem is intent
resolution, so that is what the model does: `question → AskIntent`, a typed
Pydantic object, via Gemini structured output. Everything after that is the
same code the dashboard runs.

What now runs end to end:

- `kestrel/ask/`, previously an empty placeholder package:
  - `types.py` — `AskIntent` (flat, not a discriminated union: a flat
    `response_schema` is what a model resolves reliably), `AskTurn`,
    `AskRequest`, `AskAnswer`. `metric` is a closed enum whose values
    include `unsupported`, so declining is expressible *inside* the schema
    rather than being an error path (C4.4).
  - `catalogue.py` — regions, warehouses, categories and return reasons read
    from the curated DB into the prompt as a closed set. Outlets are the one
    dimension too large to enumerate; they go through the existing `q`
    substring filter.
  - `resolver.py` — the one place a model reads a question. Anything that
    fails — malformed object, metric outside the enum, invented `region_id`,
    transport error — resolves to `unsupported`. There is no path from a
    failed resolution to a figure.
  - `dispatch.py` — `AskIntent` → the same `MetricRequest`/`ReturnsRequest`/
    `NearExpiryRequest`/`ExcursionsRequest` objects the router builds, then
    the same `compute` functions (C4.3). No SQL, no arithmetic of its own.
  - `answer.py` — the deterministic answer of record, assembled in Python.
    Every sentence states the figure, period (or snapshot), scope, unit and
    exclusions (C4.1, C4.2).
  - `narrator.py` + `guard.py` — the hybrid: optional model framing over the
    computed answer, with every number in it checked against the numbers in
    the result at the precision it rendered them. Prose that fails is
    dropped whole, never repaired.
  - `gemini.py` — the only module that imports the SDK, and it imports it
    lazily. `get_client()` returns `None` when no key is configured.
- `POST /api/service/ask` and `GET /api/service/ask/capability`. Declines
  return **200 with `declined: true`**, not an error: declining is an answer
  the product is designed to give.
- Frontend `AskPanel` above the five cards, reusing `useScope` (C5.3). Prose
  renders above the deterministic answer, never instead of it. When
  capability reports unavailable it renders an explicit unavailable state
  naming what it would answer (C4.6) — the first cut removed the panel
  entirely, which reads as a broken build rather than a deliberate
  degradation.
- `config.anthropic_api_key` (unused since slice 1) → `gemini_api_key`, plus
  `gemini_model` (default `gemini-2.5-flash`). `google-genai` added to
  `requirements.txt`.

### Decisions worth defending

- **The model never sees a row, a figure or a query.** Its entire output is
  one `AskIntent`, and its only other job is rephrasing an answer that has
  already been computed. C4.3/C4.4/C4.6 hold by construction, not by prompt
  discipline.
- **Conversation window carries `{question, intent}`, never answers.** Ten
  overlapping turns, held by the client; the server stays stateless. A
  follow-up ("and Delhi?") needs the previous *request* to merge onto, not
  the previous figures — and this way no computed number is ever in the
  model's context at any depth.
- **A grain the metric cannot serve is declined, not swapped.** "Returns by
  outlet" is a different question from "returns by category"; answering the
  second when asked the first is the C4.4 failure arriving by a side door.
- **Periods are resolved by `fiscal.py`, never by the model.** The fiscal
  year starts in April; model date arithmetic gets quarter boundaries wrong.
  `resolve_period` was split into a plain `parse_period` so ask and the
  router share one implementation.
- **The guard is tested against our own answer text.** A parametrised test
  runs `guard.check` over the deterministic answer for all five metrics: if
  the answer of record ever quotes a number the result does not contain, it
  fails the same check generated prose does.

### Verified live against Gemini (2026-09-09)

Four questions through the real API, `gemini-2.5-flash`:

- *"Which five outlets had the worst fill rate last quarter?"* → resolved to
  `fill_rate / outlet / latest / limit 5 / ascending true`. Correct on every
  field, including the two nobody states explicitly (limit, direction).
- *"How is OTIF in the West region?"* then *"and South?"* → the follow-up
  carried metric and grain from the window and changed only `region_id`.
  Delta resolution works on a real model, not just the fake.
- *"Why did fill rate drop, and what will it be next quarter?"* → declined.
  Both halves are outside the measured data (cause, forecast) and it did not
  answer the answerable-looking half.
- *"Where is near-expiry stock concentrated?"* → `near_expiry / warehouse`,
  answered as at the 2026-06-29 snapshot rather than a period.

Generated prose passed the numeric guard on every answered question.

### Two bugs the live call found that the fake model could not

- **The SDK client was collected mid-request.** `self._client().models
  .generate_content(...)` keeps no reference to the client, whose `__del__`
  closes its httpx transport — so the request in flight died with "Cannot
  send a request, as the client has been closed". The client is now built
  once and held. A fake model can never surface this: it has no transport.
- **A transport failure was reported as a decline.** Every exception funnelled
  to `unsupported`, so an outage told the user "I cannot answer that from the
  measured data" — a false statement about the data, and exactly the kind of
  confident wrongness C4.4 exists to prevent. Transport failures now raise
  `LanguageUnavailable` → 503; only a model that answered unusably still
  declines.

### OTIF's 0.0% investigated (2026-09-10)

Made visible by ask-anything: *"How is OTIF in the West region?"* returned
0.0% with in-full 0.0%, which reads as a broken metric.

It is not. PRD 5.3 defines in full as fill rate = 100% in eaches; `otif.py`
implements exactly that (`delivered_qty_eaches >= ordered_qty_eaches`), and
the *source* data has **zero** fully-delivered lines out of 511,516 — 0 in
CASE rows (398,741, mean ratio 0.74) and 0 in EACH rows (112,775, mean 0.83).
Checked at line level, order level and delivery level; no exceptions
anywhere. The transform is not at fault and neither is the metric.

Changed nothing in the computation. Added a note on the OTIF card explaining
why the figure is 0% and that on-time is the discriminating axis, plus an
entry in DECISIONS.md. Introducing an in-full tolerance would have been an
assumption invented to improve a number, and would have buried a real data
finding.

I called this a bug before checking it. It was not one — the check took four
queries, and the claim should have waited for them.

### On UI copy

The OTIF note first shipped citing "PRD 5.3" on the card. Spec section
numbers are an internal artefact; nobody operating a control tower has the
PRD open. Rewritten in operational language — the requirement traceability
lives in code comments and in DECISIONS.md, which is where a reader who
wants it will be looking.

### Not done

- `.env.example` still lists `KESTREL_ANTHROPIC_API_KEY` (the file is
  outside what this session can write).

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

## Slice 7 — scope controls and an investigating ask (done, 2026-09-10)

Three things asked for together: a region selector, a period selector, and
ask-anything answering "why did fill rate drop in the West last week?".
Brainstormed to a design, then implemented directly (spec and plan docs
skipped on request), TDD throughout.

**The model now decides what to measure.** Previously it resolved a
question into one `AskIntent` and stopped. It now runs a bounded loop:
emit a step, we execute it via the existing `dispatch.run`, feed the
summary back, repeat to a cap of six. Adaptive, so "the drop concentrates
in three outlets — now check *their* OTIF" is expressible. Built on
`generate_json`, so the fake-model test seam every other ask test uses is
untouched.

**Causes are now answered rather than declined** — a deliberate reversal
of slice 6, recorded in DECISIONS.md with its cost stated. The numeric
guard is unchanged and now runs over the union of every step's result, so
the allowed set grows by exactly what the model saw. Invented figures stay
impossible; invented explanations do not, and that is the accepted
trade.

What now runs end to end:

- `parse_period` grew a grammar: quarters (unchanged), `2026-06`,
  `2026-W24`, `2026-04-01..2026-06-30`. `Period` carries a `kind` so
  `previous_period` can step back by the right unit.
- `kestrel/reference/` — previously an empty placeholder package — gained
  `scope.py` and a router. `GET /api/service/reference/scope` returns
  regions and the periods that actually have rows (6 quarters, 18 months
  against the real data), so the dropdown cannot offer an empty view. A
  test asserts every period offered is one the metric API accepts.
- `ask/investigate.py`: the loop, the chronological delta, and the
  coverage note that tells the model when the data ends.
- `POST /api/service/ask/stream` (SSE) beside the existing JSON endpoint,
  which stays as the C4.6 fallback. Steps stream as they land.
- Frontend: `ScopeBar` in the topbar (region and period selects, both fed
  by the reference endpoint); the topbar reads "West · June 2026" rather
  than `Region 3 · latest`; `AskPanel` consumes the stream, showing each
  measurement live and then folding them into a "2 measurements taken"
  trail beneath the explanation.
- C5.3 closed properly: the dashboard's *period* now reaches ask-anything
  the same way its region always did.

### Four bugs the live model found that the fake could not

Same pattern as slice 6 — a scripted model cannot surface any of these.

- **Every explanation of a decline was silently dropped.** A drop is a
  negative delta; English states its magnitude ("fell 0.41 points"); the
  number regex never captures the minus, so the guard rejected it. The
  feature's whole purpose, broken, and green on every test.
- **The delta was subtracted in step order, not time order.** The model
  measures the recent period first, so a rise was reported as a fall —
  live, "86.0% vs 85.9%" was explained as "a drop". Deltas now run
  earlier→later and carry a `delta_basis` naming both ends.
- **"Last week" resolved to a two-day week.** The data ends Tuesday
  30 June, so the containing week is part-covered; comparing it against a
  full week manufactures a collapse. The coverage note now names the last
  *complete* week and month, which is what `latest_complete_quarter`
  already does one grain up.
- **Three of six steps were spent re-measuring the same quarter**, because
  nothing told the model when the data ends or what "last week" means in
  it. Fixed by the coverage note plus deduplicating repeated intents.

A fifth, caught by reasoning rather than a live call: the guard walked the
whole `StepRecord`, including the model's own `reasoning` text — so a model
could write a figure into one step's reasoning and quote it as a finding in
the next. It now walks only the fields we computed.

### Housekeeping

- `vite.config.ts` reads `KESTREL_API_TARGET` for its `/api` proxy,
  defaulting to `127.0.0.1:8000` as before. Needed because another session
  held port 8000 running stale code, and a live check against it nearly
  passed for the wrong reason — a second dev instance can now point at its
  own backend.
- Hand-tested end to end on the standard ports (backend 8000, frontend
  5173) against the real curated database and a live Gemini key.

### Where it ended up

Asked "why did fill rate drop in the West last week?" against the real
511k-row database, it measures the last complete week, measures the week
before, computes the change — and answers that **there was no drop**: the
rate rose 0.08 points. Contradicting a leading question is the behaviour
worth having.

## Slice 8 — data quality view (done, 2026-09-10)

PRD 6.4 asks for the ledger as "a first-class view in the product" that
states "in counts, what the numbers on every other screen exclude". The
table had been populated since slice 1; nothing rendered it. Brainstormed
in chat (bounded path, no spec doc), TDD throughout.

**Rendering the ledger table would not have met the requirement.** The
ledger records one entry per soft-deleted *outlet* (X1: 42), while the
dashboard excludes every *order line* belonging to those outlets (4,773 in
FY27 Q1 alone). X3 is never in the ledger, because whether a closed outlet
counts depends on the period being viewed. And a rule that never fired
(N1, N3) has no rows, so "checked, found nothing" and "never implemented"
looked identical. Decided with the user: the view follows the selected
region and period, like every other surface.

What now runs end to end:

- `kestrel/quality/` — previously an empty placeholder package:
  - `exclusions.py` — per measure, the rows in scope, the rows the metric
    actually counts, and a count per rule, over the same fact table, date
    column and joins the metric uses. Build-time rules read the row's
    `exclusion_rules` flags; X3 is evaluated exactly as the metrics do.
    Near-expiry is listed as "no exclusion rules apply" with null counts,
    not zeros.
  - `rules.py` — a catalogue of all eleven PRD rules (N1–N6, X1–X5):
    build-time or per-period, and its ledger count. A rule that writes no
    entries reports `null`, not `0`. Plus paged ledger entries per rule, so
    any count traces to its records.
  - `router.py` — `GET /api/service/quality` (scoped) and
    `GET /api/service/quality/ledger?rule=` (build-wide, labelled so).
- Frontend: `?view=quality` in the URL state `useScope` already owned. The
  top bar moved out of `LandingView` into `App` with "Control tower" /
  "Data quality" links, so scope carries across views. One `useScope`
  instance, owned by `App`: two would each hold their own copy, since
  `pushState` notifies nobody.

### Decisions worth defending

- **Counts reconcile with the metrics by test, not by care.** For each of
  the four period metrics and two periods, the quality view's counted rows
  must equal the metric's `source_row_count`, and in-scope rows must equal
  it with `include_excluded=True`. Mutation-checked: dropping X3 from the
  counted filter fails all four FY27 Q1 cases. The shared fixture's only
  closed-outlet row was also a cancelled order, which would have let an X3
  drift hide behind X4, so the test adds an order that only X3 excludes.
- **Rule counts overlap and the screen says so.** A cancelled order at a
  closed outlet is one excluded line under two rules; the per-rule columns
  can sum past the excluded total.

### Found in the data (verified, not assumed)

- **FY27 Q1 fill rate is measured over 68,329 of 85,861 order lines —
  20.4% are excluded.** OTIF 12.1%, returns 13.7%, excursions 12.4%.
- **X3 is the largest single rule after X4** (5,373 lines nationally;
  2,043 of North's 3,918) — and it was the one the ledger could never show.
- **N2 and N6 appear nowhere in the transform.** No UTC→Asia/Kolkata
  conversion of order timestamps, no as-at-order-date price resolution. The
  catalogue marks both "Not recorded" rather than implying they ran. Whether
  either needs building is an open question, not settled here.
- **3 of the 4 X5 duplicate outlets are also the X2 test outlets** — the
  test outlets share GST numbers.

### What the page says, in plain words

Worked out while walking the user through it, and worth keeping as the
test of whether the page is doing its job:

1. The dashboard deliberately does not use all the data — about 1 in 5
   order lines in FY27 Q1 is left out of fill rate.
2. Every record left out has a rule saying why (mostly cancelled orders
   and closed shops).
3. Some values were repaired rather than removed (negative return
   quantities, city spellings).
4. Any count can be clicked through to the records behind it.

So when someone's spreadsheet disagrees with the dashboard, the argument
becomes "which rule did you apply differently", not "whose number is
right" — Divya's four-people-four-numbers problem, answered directly.

### Verified

Hand-tested in the browser on this session's own servers (backend 8010,
frontend 5183) against the real curated database: the table, X4's 41,401
entries paged 1–50 → 51–100, region switched to North (19.5% excluded,
matching the in-process count), and back to the control tower with region
and period carried over. No console errors.

## Next

**A drill-down view for an investigation**, so an analysis is shareable by
URL rather than living inside one answer in one session's panel.

---

## Known gaps

- `unmeasured_count` is now live (OTIF's unparseable-arrival case) but reads 0
  against the real data, since `actual_arrival` is never NULL there.
- No frontend tests yet, including none over the SSE stream parser, which
  is the fiddliest logic on that side. The API contract is typed by hand in
  `api/types.ts` rather than generated from the OpenAPI schema, so the two
  can drift.
- Transform is a full rebuild. Fine at 511k lines; not at 50 million.
- `coldchain/` is an empty package that exists to make the intended
  structure visible. `ask/`, `reference/` and `quality/` are now populated.
- Ledger entries are build-wide; the ledger stores no region or period, so
  the per-rule entry list cannot be scoped the way the counts are.
- Ask-anything has no automated live-model test. Prompt quality is verified
  by hand against a real key, which is how all five of the above were found
  and is not a substitute for a test.
- An investigation costs ~6 model calls and 15-25 seconds. Streaming makes
  that legible, not fast.
