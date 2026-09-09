# Decisions

## What is built

A curated data layer and all five PRD metrics, end to end, on the real
database.

`python -m kestrel.transform build` reads `kestrel_ops.db` read-only and
materialises a separate `kestrel_curated.db` in well under a minute: 5
regions, 724 outlets, 511,516 order lines, 76,889 deliveries, 14,000
returns, 131,040 inventory snapshots, and 42,377 quality-ledger rows. Every
row the build excludes or repairs is written to that ledger with the rule
that did it. The current counts are X4 41,401 (cancelled and open orders),
X1 42 (soft-deleted outlets), N5 27 (city names mapped), X5 4 (duplicate
outlets), X2 3 (test outlets), N4 900 (return-quantity sign normalised).

Fill rate: one implementation, called by the API, returned with the basis it
was derived from — period, scope, unit, exclusion rules, and the number of
order lines behind the figure. The landing view shows the national figure,
that basis line, and the five worst outlets without any navigation. It
answers in about 0.1 seconds against 68,329 lines.

OTIF: on-time, in-full and the combined figure, each reported separately
(PRD C2.4) so a delivery's two ways of failing don't collapse into one
number. The on-time tolerance (30 minutes, no documented SLA) is a request
parameter, not a build-time constant, so the same curated data can answer
"on time within 30 minutes" and "within 15" without a rebuild — and the
basis line always states which tolerance produced the figure on screen.

Returns and credit note leakage: value credited back, as a share of
dispatch value, with only `APPROVED` credit notes counted as real leakage —
`PENDING` and `REJECTED` value is still surfaced in the basis rather than
silently dropped. A cold-chain-attributable sub-rate isolates returns coded
as near-expiry or cold-chain breach (PRD C3.5).

Near-expiry stock: available cases (on-hand less allocated, damaged and
blocked — recomputed, not copied from the source column, which does not
exclude damaged/blocked) within a configurable day threshold of expiry, as
at the latest weekly snapshot, never as at today.

Temperature excursions: chilled deliveries whose reefer breached its
temperature band in transit, over all chilled deliveries, reported by month
and by route/warehouse for concentration (PRD C3.1/C3.2).

132 backend tests, all passing, Ruff clean.

## What is deliberately not built

The ask-anything interface; the quality-ledger screen; the region selector.
All are designed (spec sections 6–9) and the structure for them exists —
`useScope` already carries `regionId`, and the quality ledger is already a
populated table. Ask-anything is deliberately last: with only one or two
metrics to route to, an intent resolver has nothing to choose between, and
the guarantee that matters (the LLM resolves intent into a validated
request, never sees a row, never emits a number) is unconvincing until there
are enough metrics to make routing a real problem. With all five now built,
that precondition is met.

## What I assumed

**Eaches, not cases.** Divya's brief asks for cases; Rakesh's reply asks for
eaches. Both are right about their own job. Eaches is the default because
modern-trade penalties are assessed on units short, and cases is a toggle
*derived from* the each figure rather than computed separately — so the two
views of the same event cannot disagree. Today they read 85.6% and 85.9%: a
real, explainable difference, from one derivation.

**Exclusions are flags, not deletions.** Excluded rows stay in the curated
tables carrying the rules that excluded them, so `include_excluded=true`
reverses any exclusion as a query, not a rebuild.

**Closed outlets are excluded at query time, not build time.** The rule is
period-scoped: a shop that closed in June 2025 belongs in the FY26 numbers and
not in FY27's. A build-time flag cannot express that.

**Duplicate outlets key on GST number, not name.** 158 name-and-city pairs
repeat legitimately across the estate; only two GST numbers are shared. Keying
on name would have wrongly excluded 197 real outlets.

**Test outlets are identified by `outlet_code LIKE 'TST%'`.** All three are
`ACTIVE` and not deleted, so a status-based rule would have missed them.

**No SLA is documented**, so the on-time tolerance (30 minutes) and the
near-expiry window (30 days) are configuration, not constants — visible in
`.env.example` and changeable without touching code.

**The case-pack fallback never fires.** Every `case_pack_at_order` matches the
product master, so N1 reports 0. I kept the rule and report the zero rather
than deleting it: a rule with a zero count is information about the data.

**OTIF's "in full" is implemented literally, and it never fires.** PRD 5.3
defines "in full" as a delivery's fill rate reaching 100% in eaches. Across
all 76,889 real deliveries, the maximum observed is 99.37% — zero reach
100%. OTIF and the in-full rate therefore report honestly near-zero. I did
not invent a softer threshold to make the number look more useful: a metric
that is always ~0% is itself the finding, the same way N1's zero-fire is —
and it belongs to whoever owns delivery quality on the ground, not to this
build.

**The source `delay_minutes` column on deliveries is not used.** Verified
against the real data, it disagrees with `actual_arrival - planned_arrival`
on roughly 87% of rows, with no discernible pattern — not a fixed offset,
not a format artifact. PRD 5.3 defines on-time from the two timestamps
directly, so `s30_deliveries` computes delay itself and never reads that
column.

**`actual_arrival` is parsed as two vendor formats, not one.** ISO
(`2025-01-04 10:24:00`, the majority) and a 12-hour `DD-Mon-YYYY hh:mm AM/PM`
format both appear in the real data. A timestamp matching neither is logged
as N3 and counted as unmeasured (PRD 5.3) rather than dropped — currently 0
rows, the same zero-fire pattern as N1.

**Only `APPROVED` credit notes count as returns leakage.** `PENDING` and
`REJECTED` notes never resulted in an actual credit, so including them would
overstate money given back that was never (or not yet) handed over. Both are
still reported in the basis by count and value, the same principle as OTIF's
`unmeasured_count`.

**Return-quantity sign is normalised, original sign kept for audit.** 900 of
14,000 rows arrive negative from one upstream feed (KP-2402); the credit
note value itself is never negative, only the quantity needed correcting.

**Near-expiry's `available_cases` is recomputed, not copied.** The source
column is `on_hand_cases - allocated_cases` only; PRD 5.5 requires damaged
and blocked stock excluded too, so the curated column is
`on_hand - allocated - damaged - blocked`, with damaged/blocked still
surfaced separately in the basis rather than folded invisibly into the rate.

**A chilled delivery is derived, not read off a source column.** PRD 5.4
defines it as "any line on the order is a chilled or frozen product," so
`is_chilled` on `fact_delivery` is computed from `fact_order_line` joined to
the product master's `is_chilled` flag — the same join pattern already used
for OTIF's eaches sums — rather than trusting a delivery-level flag that
does not exist in the source.

**Excursion duration and severity are not inferred.** The source captures
only a breach flag and a peak temperature per delivery; PRD 5.4 is explicit
that a fuller severity profile must not be invented from those two numbers,
so none is reported.

## What two more weeks would add

The ask-anything path (the LLM resolves intent into a validated request and
never sees a row or emits a number, so it cannot invent a figure); the
quality ledger as a screen, since it is already a table; and the region
selector, which the URL scope and the endpoint both already carry.

## What breaks first

The transform is a full rebuild. At 511k order lines that is seconds; at 50
million it is not, and the ledger would need to be written incrementally.
SQLite is right for one analyst and a single machine, and wrong for concurrent
writes — but the read path is a file swap, so a scheduled rebuild would keep
serving throughout. The rules most likely to be wrong are the ones this data
cannot test: X5 has only two duplicate groups to learn from, and N1 has none.
