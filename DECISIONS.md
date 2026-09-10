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

**OTIF reads 0.0% because no delivery in this data is ever in full.** PRD
5.3 defines in full as every line delivered complete — fill rate 100% in
eaches. Not one of the 511,516 order lines meets that test: the average
line is delivered at 0.74 (cases) and 0.83 (eaches) of what was ordered, and
there is not a single exception in either unit. So OTIF is 0% everywhere,
and on-time (~43%) is the only axis that discriminates.

I did not introduce an in-full tolerance to make the number move. A
tolerance would be an assumption invented to improve a figure, which is the
failure this product exists to eliminate — and it would hide a real finding:
either the source systems never record complete delivery, or the extract is
wrong. That is a question for Operations, not something a dashboard should
paper over. The OTIF card states the reason on its face so nobody reads 0.0%
as a broken build.

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

**The model plans an investigation; it still computes nothing.** A question
like "why did fill rate drop in the West last week" has no single figure
that answers it. The model now chooses a sequence of measurements — the
week, the week before, then a breakdown — each picked after seeing the
last, up to six. Every figure still comes from the same metric functions
the dashboard calls, and the change between two periods is computed in
Python, because a delta the model worked out itself is a figure with no
provenance. The panel shows the measurements it took alongside the
answer, so a reader can check the prose against the queries.

**The model may state causes it cannot measure, and this is a deliberate
product decision.** The numeric guard still holds absolutely: prose is
checked against every figure the model was shown and discarded whole if it
quotes anything else, so a fabricated *number* remains impossible. A
fabricated *explanation* does not, because "fill rate fell because the
depot flooded" contains no number to check. We accept that: an operator
reading a control tower wants a hypothesis to act on, and the measurements
backing it are on screen to be judged. The cost is real and worth stating
plainly — some explanations will be confidently wrong in a way no
automated check catches. C4.4's hard line, that the product must not
produce a plausible *figure* for a question it cannot answer, is
unchanged.

**Guarded figures include their own magnitude.** A drop is stored as a
negative delta and English states its size — "fell 0.41 points", not
"changed by −0.41 points". The first cut rejected exactly that, so every
explanation of a decline was silently dropped: the one case the feature
exists for. Found by running a live question, not by a test.

**Comparisons are oriented by time, not by the order they were measured.**
The model usually measures the period asked about first and its baseline
second. Subtracting in step order then reports a rise as a fall, which a
live run duly did — 86.0% against 85.9% described as "a drop". The delta
now runs from the chronologically earlier period to the later one and says
which is which.

**"Last week" means the last complete week.** The data ends mid-week, so
the week containing the final row holds two days. Comparing it against a
full week reads as a collapse that is only a truncated period — the same
trap `latest_complete_quarter` already avoids one grain up, now applied to
weeks and months.

## What two more weeks would add

The quality ledger as a screen, since it is already a table; a drill-down
view for an investigation, so the analysis is shareable rather than living
inside one answer; and generated frontend types, since the API contract is
currently typed by hand.

## What breaks first

The transform is a full rebuild. At 511k order lines that is seconds; at 50
million it is not, and the ledger would need to be written incrementally.
SQLite is right for one analyst and a single machine, and wrong for concurrent
writes — but the read path is a file swap, so a scheduled rebuild would keep
serving throughout. The rules most likely to be wrong are the ones this data
cannot test: X5 has only two duplicate groups to learn from, and N1 has none.
