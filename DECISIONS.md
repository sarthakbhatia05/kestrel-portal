# Decisions

## What is built

A curated data layer and one metric, end to end, on the real database.

`python -m kestrel.transform build` reads `kestrel_ops.db` read-only and
materialises a separate `kestrel_curated.db` in about 11 seconds: 5 regions,
724 outlets, 511,516 order lines, and 41,477 quality-ledger rows. Every row the
build excludes or repairs is written to that ledger with the rule that did it.
The current counts are X4 41,401 (cancelled and open orders), X1 42
(soft-deleted outlets), N5 27 (city names mapped), X5 4 (duplicate outlets), X2
3 (test outlets).

On top of that, fill rate: one implementation, called by the API, returned with
the basis it was derived from — period, scope, unit, exclusion rules, and the
number of order lines behind the figure. The landing view shows the national
figure, that basis line, and the five worst outlets without any navigation. It
answers in about 0.1 seconds against 68,329 lines. 41 tests, all passing.

## What is deliberately not built

OTIF, cold-chain excursions, near-expiry and returns; the ask-anything
interface; the quality-ledger screen; the region selector. All are designed
(spec sections 6–9) and the structure for them exists. I chose depth over
breadth: one metric that is genuinely defensible demonstrates more than five
that are not.

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

## What two more weeks would add

The remaining four metrics against the same contract; the ask-anything path
(the LLM resolves intent into a validated request and never sees a row or emits
a number, so it cannot invent a figure); the quality ledger as a screen, since
it is already a table; and the region selector, which the URL scope and the
endpoint both already carry.

## What breaks first

The transform is a full rebuild. At 511k order lines that is 11 seconds; at 50
million it is not, and the ledger would need to be written incrementally.
SQLite is right for one analyst and a single machine, and wrong for concurrent
writes — but the read path is a file swap, so a scheduled rebuild would keep
serving throughout. The rules most likely to be wrong are the ones this data
cannot test: X5 has only two duplicate groups to learn from, and N1 has none.
