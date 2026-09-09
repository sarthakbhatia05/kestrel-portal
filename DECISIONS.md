# Decisions

## What is built

A curated data layer and two metrics, end to end, on the real database.

`python -m kestrel.transform build` reads `kestrel_ops.db` read-only and
materialises a separate `kestrel_curated.db` in under a minute: 5 regions,
724 outlets, 511,516 order lines, 76,889 deliveries, and 41,477
quality-ledger rows. Every row the build excludes or repairs is written to
that ledger with the rule that did it. The current counts are X4 41,401
(cancelled and open orders), X1 42 (soft-deleted outlets), N5 27 (city names
mapped), X5 4 (duplicate outlets), X2 3 (test outlets).

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

63 backend tests, all passing, Ruff clean.

## What is deliberately not built

Cold-chain excursions, near-expiry and returns; the ask-anything interface;
the quality-ledger screen; the region selector. All are designed (spec
sections 6–9) and the structure for them exists. I chose depth over breadth:
metrics that are genuinely defensible demonstrate more than five that are
not.

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

## What two more weeks would add

The remaining three metrics against the same contract; the ask-anything path
(the LLM resolves intent into a validated request and never sees a row or emits
a number, so it cannot invent a figure); the quality ledger as a screen, since
it is already a table; and the region selector, which the URL scope and the
endpoint both already carry.

## What breaks first

The transform is a full rebuild. At 511k order lines that is seconds; at 50
million it is not, and the ledger would need to be written incrementally.
SQLite is right for one analyst and a single machine, and wrong for concurrent
writes — but the read path is a file swap, so a scheduled rebuild would keep
serving throughout. The rules most likely to be wrong are the ones this data
cannot test: X5 has only two duplicate groups to learn from, and N1 has none.
