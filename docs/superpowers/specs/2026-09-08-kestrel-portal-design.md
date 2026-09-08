# Kestrel Portal — Architecture & Scaffold Design

| | |
|---|---|
| Date | 8 September 2026 |
| Status | Approved |
| Implements | [PRD.md](../../../PRD.md) v0.1 |

---

## 1. Purpose and scope of this document

This document fixes the architecture of the Kestrel Provisions Supply Chain
Control Tower and defines the first implementation step: the project scaffold
plus one working vertical slice.

It is an architecture decision record, not a feature specification. The
normative feature and metric definitions live in `PRD.md`; where this document
and the PRD disagree, the PRD wins.

**In scope here:** repository layout, module boundaries, the curated data
layer, the metric layer, the ask-anything pipeline, the frontend structure,
configuration, testing strategy, and the definition of done for the first
slice.

**Not in scope here:** the full metric implementations for C2/C3, the complete
transform ruleset, and the finished UI. Those are built on this scaffold in
subsequent steps and are covered by the implementation plan.

---

## 2. Technology decisions

| Layer | Choice | Rationale |
|---|---|---|
| Backend | FastAPI (Python 3.11+) | Typed request/response contracts, OpenAPI schema for free, which the frontend consumes to prevent contract drift. |
| Data access | Raw SQL over `sqlite3`, thin repository layer | The workload is read-only and analytical. Metric definitions are the product's core asset (G1) and must be readable as definitions; an ORM obscures them. Matches the SQL-first stance of the reference best-practices guide. |
| Storage | SQLite (source, read-only) + SQLite (curated, built) | Source data ships as SQLite. A second file keeps the curated layer physically separate, which is what makes NF6 enforceable. |
| Frontend | Vite + React + TypeScript | Fast cold start (NF1), no framework server to run, types generated from the backend OpenAPI schema. |
| Server state | TanStack Query | Caching and request deduplication so scope/unit changes do not refetch the whole landing view (NF3). |
| Language capability | Anthropic API, optional | Used only for intent resolution, never for computing figures. Absent key degrades to a deterministic parser (NF7, C4.6). |

### Rejected alternatives

- **dbt-core with the dbt-sqlite adapter** for the transform stage. Lineage
  and docs are attractive, but the adapter is community-maintained, and a
  fragile dependency directly threatens NF1 (cold start with no undocumented
  prerequisites).
- **SQL views over the source database** instead of a materialised curated
  layer. Cheapest option, but the quality ledger (PRD §6.4) has nowhere to be
  written, and aggregate views over 511,516 order lines put NF3 at risk.
- **LLM-generated SQL (text-to-SQL)** for ask-anything. Maximum flexibility,
  but it bypasses the canonical metric implementations and so violates G1 and
  C4.3 by construction. A figure produced by a path other than the metric
  layer is exactly the contested number this product exists to eliminate.
- **SQLAlchemy ORM.** Conventional, but a poor fit for a read-only analytical
  workload, and it hides the metric SQL that reviewers need to read.

---

## 3. Repository layout

The submission is a single repository. This directory (`kestrel-portal/`) is
its root. The assignment pack sits outside the repository; the source database
is referenced by configured path and is never committed.

```
kestrel-portal/
├── README.md                  # cold start, one machine, no tribal knowledge
├── DECISIONS.md               # built / not built / assumed / next / breaks first
├── PRD.md
├── .env.example
├── .gitignore
├── docs/superpowers/specs/
├── backend/
│   ├── pyproject.toml
│   ├── tests/
│   └── src/kestrel/
│       ├── main.py
│       ├── config.py
│       ├── database.py
│       ├── exceptions.py
│       ├── transform/
│       ├── metrics/
│       ├── service/
│       ├── coldchain/
│       ├── quality/
│       ├── ask/
│       └── reference/
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       ├── main.tsx
│       ├── api/
│       ├── features/
│       └── components/
└── data/curated/              # build output, gitignored
```

### Domain packages

`service`, `coldchain`, `quality`, `ask` and `reference` are HTTP-facing
domain packages. Each contains, as needed:

| File | Purpose |
|---|---|
| `router.py` | Endpoints for the domain. No arithmetic. |
| `schemas.py` | Pydantic request and response models. |
| `service.py` | Domain orchestration: assembles metric calls into a response. |
| `dependencies.py` | Scope, period and unit resolution as reusable dependencies. |
| `constants.py` | Error codes and domain constants. |
| `exceptions.py` | Domain exception types. |

There is no `models.py` in any package, because there is no ORM.

`transform/` and `metrics/` are not HTTP-facing and have no router.

---

## 4. Layering rule

```
frontend  →  domain routers  →  domain services  →  metrics/  →  curated DB
                                                     transform/ ↗   ↑
                                                                source DB (read-only)
```

Three constraints hold at every layer:

1. **No HTTP-facing code reads the source database.** Only `transform/` opens
   it, and only read-only. This is PRD §6.1, and it is what makes G1
   enforceable rather than aspirational.
2. **No router or domain service computes a figure.** Every number originates
   in `metrics/`. This is what guarantees C4.3 — that the dashboard and
   ask-anything cannot disagree.
3. **`metrics/` does not import from any domain package.** It depends only on
   `database.py` and its own types, so it is unit-testable without the app
   (NF8).

---

## 5. Configuration

`config.py` exposes a single `Settings` (pydantic-settings) read from
environment and `.env`:

| Setting | Default | Notes |
|---|---|---|
| `source_db_path` | — | Required. Path to `kestrel_ops.db` in the assignment pack. |
| `curated_db_path` | `data/curated/kestrel_curated.db` | Build output. |
| `on_time_tolerance_minutes` | `30` | PRD A1. Configurable, not hard-coded. |
| `near_expiry_days` | `30` | PRD A2. |
| `fiscal_year_start_month` | `4` | PRD §5.7. April–March. |
| `anthropic_api_key` | `None` | Optional. Absent disables LLM intent resolution only. |
| `cors_origins` | `["http://localhost:5173"]` | Vite dev server. |

Per the reference guide, domain-specific settings may later live in a
`config.py` inside their own package. The three metric thresholds above are
deliberately root-level: they are assumptions from the PRD that must be
visible in one place, because they are the settings a reviewer will want to
change.

`.env.example` is committed and documents every variable. `.env` is not.

---

## 6. Data foundation — `transform/` (C1)

### 6.1 Execution model

A CLI entry point, `python -m kestrel.transform build`, runs the whole stage.
It is the only code that opens the source database, and it opens it with
`sqlite3.connect("file:...?mode=ro", uri=True)` — NF6 is enforced by the
connection, not by convention.

### 6.2 Idempotency (NF5)

The build writes to `kestrel_curated.db.tmp` and atomically renames it over
the previous file on success. A failed run leaves the previous curated
database intact and serving. Re-running is therefore always safe, and there is
no partial-state case to reason about.

Each run records a `run_id` (UUID) and a `build_runs` row with start time, end
time, source database path, and row counts per curated table.

### 6.3 Steps

Steps are ordered modules, each exposing `run(src, dst, ledger) -> None`:

| Step | Produces | Rules applied |
|---|---|---|
| `s00_reference` | regions, warehouses, routes, salespeople, outlets | N5 city canonicalisation; X1, X2, X3, X5 outlet flags |
| `s10_products` | products, price windows | N6 as-at price resolution |
| `s20_orders` | order headers, order lines | N1 eaches normalisation; N2 timestamp parsing; X4 cancelled flag |
| `s30_deliveries` | deliveries | N3 two-vendor arrival parsing; on-time evaluation |
| `s40_inventory` | inventory snapshots | Damaged and blocked separated from available |
| `s50_returns` | credit note lines | N4 sign normalisation, original sign retained |
| `s90_integrity` | header-vs-line variance | PRD §6.5, quantified and stored, never adjusted |

### 6.4 Exclusions are flags, not deletions

Excluded rows are **retained in the curated layer** and carry boolean
exclusion flags plus the rule reference that set them. Curated queries apply
the default filter; `include_excluded=true` lifts it.

This is a direct reading of PRD §6.3: "applied by default and reversible on
request". Deleting excluded rows would make reversibility a rebuild, which is
not reversal on request. It also means the quality ledger can be reconciled
against the curated tables it describes.

### 6.5 Quality ledger

A first-class curated table, not application logging:

```
quality_ledger(run_id, rule_ref, rule_name, entity_type, entity_id,
               action, reason, source_system, created_at)
```

`action` is one of `EXCLUDED`, `REPAIRED`, `REJECTED`. Every N-rule repair and
every X-rule exclusion writes a row. The `quality` domain package serves it as
a user-facing screen stating, in counts, what every other screen excludes
(PRD §6.4, G4).

---

## 7. Metric layer — `metrics/` (G1, NF8)

One module per metric: `fill_rate.py`, `otif.py`, `excursions.py`,
`near_expiry.py`, `returns.py`.

Each exports one function with the shape:

```python
def compute(conn: Connection, request: MetricRequest) -> MetricResult
```

`MetricRequest` carries grain, period, scope, unit and `include_excluded`.
`MetricResult` carries the figure **and its basis**:

```python
class MetricBasis(BaseModel):
    metric: str
    period_start: date
    period_end: date
    period_label: str          # fiscal, e.g. "FY26 Q1"
    unit: Literal["eaches", "cases"]
    scope: str                 # "National" | region name
    exclusions_applied: list[str]      # rule refs, e.g. ["X1", "X2", "X4"]
    unmeasured_count: int              # PRD §5.3, never silently dropped
    source_row_count: int
```

Returning the basis from the metric function, rather than assembling it in a
router, is what makes C4.2 and success criterion 1 automatic: any caller —
dashboard or ask-anything — receives the derivation with the figure, because
there is no path that returns the figure alone.

Metric SQL lives in the module as named, parameterised queries. Grain and
scope are bound parameters and a validated column allowlist, never string
interpolation of user input.

---

## 8. Ask-anything — `ask/` (C4)

A three-stage pipeline, with the boundary between stages being the point of
the design:

1. **Resolve.** Question text → `AskIntent` (Pydantic). Two interchangeable
   resolvers: an LLM resolver, and a deterministic keyword/regex resolver.
   The LLM is given a catalogue of supported metrics, grains, periods and
   filters, and returns JSON only. It never sees data rows and never emits a
   number.
2. **Validate.** The intent must name a supported metric, grain and period. A
   resolver returning anything outside the catalogue, or failing to resolve,
   raises `UnsupportedQuestion`, which the router renders as an explicit
   refusal naming what *is* supported (C4.4).
3. **Execute.** The validated intent is translated to a `MetricRequest` and
   passed to `metrics/`. Both the prose answer and the supporting figures come
   from that single `MetricResult` (C4.3, C4.5).

Resolver selection is a dependency: no `anthropic_api_key` configured means
the deterministic resolver, with no other behavioural change anywhere in the
application (NF7, C4.6). A supported question phrased plainly still answers
offline; only phrasing flexibility degrades.

**The LLM cannot produce a figure.** It has no database access and its output
is constrained to a Pydantic model whose fields are enumerated. This is a
structural guarantee, not a prompt instruction, which is the standard C4.4
demands.

---

## 9. Frontend

```
frontend/src/
├── api/            # generated OpenAPI types + typed fetch client
├── features/
│   ├── landing/    # exception surface (G2, C2.3)
│   ├── service/
│   ├── coldchain/
│   ├── quality/
│   └── ask/
├── components/     # shared presentational primitives
└── lib/            # scope/unit/period URL state, fiscal period helpers
```

Feature directories mirror backend domain packages, so a change to a metric
has one obvious place to land on each side.

**Scope, unit and period live in URL query state**, read by a single hook and
passed to every request. C5.3 ("selected scope applies consistently to every
surface, including ask-anything") then holds because there is one source of
truth, and the state is shareable and bookmarkable.

**The landing view is an exception surface, not a canvas.** On entry it
renders the most recent complete fiscal Q1 headline figures (PRD §5.7, and
Rakesh Menon's note) and the worst performers by region, warehouse, route and
outlet — no drill-down, no interaction required (G2, C2.3, success criterion
2).

Every displayed figure renders its basis line (period, scope, unit,
exclusions). Inventory figures additionally render their snapshot date
(PRD §5.5), and any route- or salesperson-attributed historical figure renders
the A8 approximation label.

---

## 10. Error handling

`exceptions.py` defines `AppError(code, message, status)`. Domain packages
subclass it. A single exception handler renders every `AppError` as:

```json
{ "error": { "code": "UNSUPPORTED_QUESTION", "message": "...", "detail": {...} } }
```

Unhandled exceptions return a generic 500 with a correlation id; details are
logged, never returned.

`UnsupportedQuestion` is deliberately **not** an error condition in the UI. It
is a first-class answer type, rendered as a refusal that names the supported
metrics. Treating a refusal as a failure would create pressure to avoid it,
which is the pressure C4.4 exists to remove.

---

## 11. Testing

| Level | Target | Notes |
|---|---|---|
| Unit | `metrics/` | Against a small fixture curated DB built in a tmpdir. No HTTP, no app. This is NF8. |
| Unit | `transform/` steps | Each N- and X-rule gets a case proving both the transformation and its ledger row. |
| Contract | Routers | `httpx.AsyncClient` against the app, dependencies overridden to the fixture DB. |
| Refusal | `ask/` | An out-of-scope question must refuse. Asserted explicitly — this is success criterion 4. |
| Performance | Landing view | Timed against the full dataset, asserted under NF3's two seconds. |

Fixture data is a deterministic subset generated by a committed script, so
tests never depend on the real database being present.

Ruff for lint and format, backend and CI. `pytest` is the single test command.

---

## 12. First vertical slice — definition of done

Fill rate, end to end, proving every layer boundary above:

1. `transform build` produces a curated DB containing normalised order lines
   in eaches (N1), outlet exclusion flags (X1, X2, X5), and quality ledger
   rows for each.
2. `metrics/fill_rate.py` computes fill rate at outlet grain for a fiscal
   period, in eaches and cases, returning a populated `MetricBasis`.
3. `GET /api/service/fill-rate` serves it, with scope, period and unit as
   dependency-resolved query parameters.
4. A React landing card renders the headline figure, its basis line, and the
   five worst outlets.
5. `pytest` passes, including one metric unit test and one router contract
   test.
6. `README.md` cold-start commands work on a clean machine (NF1), and the
   landing view meets NF3 on the full dataset.

The slice is complete when a person who has not seen the system can start it
from `README.md` alone and read a fill rate figure with its basis.

---

## 13. Known deviations and follow-ups

- `.gitignore` currently ignores `*.sqlite` and `*.sqlite3` but not `*.db`.
  It must also ignore `*.db` and `data/curated/`, or the curated build output
  and any stray copy of the source database will be committed. Fixed as part
  of the scaffold step.
- The repository directory was renamed from `Kestral Portal` to
  `kestrel-portal`: the product is spelled *Kestrel* throughout the PRD, and
  a path containing a space is a cold-start hazard (NF1).
- `DECISIONS.md` is written last, once the built/not-built line is real. It
  is a required deliverable and must not be deferred past the final commit.
