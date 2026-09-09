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
| Slices complete | 2 of 4 planned (fill rate, OTIF) |
| Backend tests | 63 passing, Ruff clean |
| Curated build | 29.7s — 511,516 order lines, 76,889 deliveries, 41,477 ledger rows |
| Fill rate query | 0.10s over 68,329 lines (NF3 allows 2s) |
| Cold start | Verified from a clean `git clone`, README only |

**Metrics live:** fill rate (PRD §5.2), OTIF (PRD §5.3).
**Metrics not started:** excursions §5.4, near-expiry §5.5, returns §5.6.

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

## Next

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

- `unmeasured_count` is now live (OTIF's unparseable-arrival case) but reads 0
  against the real data, since `actual_arrival` is never NULL there.
- No frontend tests yet. The API contract is typed by hand in `api/types.ts`
  rather than generated from the OpenAPI schema, so the two can drift.
- Transform is a full rebuild. Fine at 511k lines; not at 50 million.
- `coldchain/`, `quality/`, `ask/` and `reference/` are empty packages that
  exist to make the intended structure visible.
