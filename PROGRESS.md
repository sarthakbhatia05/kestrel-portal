# Progress log

A running record of what has been built, what was decided along the way, and
what is next. Working notes — the assignment's two required documents are
[README.md](README.md) and [DECISIONS.md](DECISIONS.md); this file is neither
and is not written for a grader.

Update it at the end of each slice, not continuously.

---

## Status at 2026-09-08

| | |
|---|---|
| Slices complete | 1 of 4 planned (fill rate) |
| Backend tests | 41 passing, Ruff clean |
| Curated build | 11s local / 32s clean clone — 511,516 order lines, 41,477 ledger rows |
| Fill rate query | 0.10s over 68,329 lines (NF3 allows 2s) |
| Cold start | Verified from a clean `git clone`, README only |

**Metrics live:** fill rate (PRD §5.2).
**Metrics not started:** OTIF §5.3, excursions §5.4, near-expiry §5.5, returns §5.6.

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

## Next

**Slice 2 — OTIF (§5.3).** Recommended next. Needs one transform step
(`s30_deliveries`); everything else is reuse. Chosen over more breadth because
it exercises two parts of the design fill rate never touched: a configurable
assumption (the 30-minute tolerance, which has no documented SLA behind it) and
the unmeasured count (deliveries with no recorded arrival are not on time and
are reported separately, so the denominator is never quietly shrunk).
`MetricBasis.unmeasured_count` exists and is 0 today because fill rate has
nothing to put in it.

Open design question to settle first: the tolerance should be an endpoint
parameter, not only config, so the basis line states which tolerance produced
the figure.

**Slice 3 — returns (§5.6) and near-expiry (§5.5).** The loss side of the
landing view's promise. Returns is the only rupee-denominated metric. Inventory
is a weekly snapshot and must be labelled as-at the snapshot date, never today.

**Slice 4 — ask-anything (C4).** Deliberately last. With one metric to route
to, an intent resolver has nothing to choose between and the guarantee that
matters — the LLM resolves intent into a validated request, never sees a row,
never emits a number — is unconvincing. With five metrics it is the sharpest
thing in the build.

**Small, fold into a slice rather than planning separately:** the quality-ledger
screen (the table is already populated) and the region selector (`useScope`
carries `regionId`, the endpoint accepts it).

---

## Known gaps

- `unmeasured_count` is wired through the basis but always 0 until OTIF lands.
- No frontend tests yet. The API contract is typed by hand in `api/types.ts`
  rather than generated from the OpenAPI schema, so the two can drift.
- Transform is a full rebuild. Fine at 511k lines; not at 50 million.
- `coldchain/`, `quality/`, `ask/` and `reference/` are empty packages that
  exist to make the intended structure visible.
