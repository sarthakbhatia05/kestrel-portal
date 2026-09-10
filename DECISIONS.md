# Decisions

## What I built

- **A curated layer.** `python -m kestrel.transform build` reads `kestrel_ops.db` read-only and writes `kestrel_curated.db`. Every row it excludes or repairs is written to a quality ledger naming the rule. The biggest are X4, 41,401 cancelled or open orders, and N4, 900 negative return quantities.
- **Five measures, one implementation each,** returned with their basis (period, scope, unit, exclusions, row count). Fill rate and OTIF cover region to outlet; then returns and credit-note leakage, near-expiry stock and temperature excursions. One screen shows all five with the worst performers already listed. Region and period live in the URL, which gives regional managers their own view.
- **A data quality view.** For the selected scope it shows what each figure leaves out and why, down to the ledger records. It answers "four people, four numbers".
- **Ask-anything.** Gemini picks up to six measurements from the same functions the dashboard calls. It computes nothing, and prose quoting a figure it was not shown is discarded.

## What I deliberately did not build

- **Freight cost per case.** Carrier invoices have no delivery-level key, so this needs an allocation model, and that is Finance's decision.
- **Competitor price position.** BazaarPulse titles share no key with our SKUs. The matching *is* the feature, and without a validated match set a price gap would be confidently wrong.
- **Rules N2 (UTC→IST) and N6 (as-at-order price).** The quality view shows them as "not recorded".
- **Authentication, frontend tests and generated API types.** Region scoping is a view filter, not a security control.

## What I assumed

- **Eaches, not cases.** Modern-trade penalties are on units, so eaches is the default. Cases is derived from the same lines, so FY27 Q1 reads 85.6% eaches and 85.9% cases, and the two cannot disagree.
- **Q1 on the front page.** The default is the latest complete fiscal quarter *that has data*, FY27 Q1. It follows the data's last date, not today's, so an ageing extract never opens on an empty quarter.
- **OTIF reads 0%, deliberately.** In full means every each delivered, and none of the 511,516 lines were. Adding a tolerance would invent a number. On-time (43.0%) still discriminates, and whether complete deliveries are ever recorded is a question for Operations.
- **There is no SLA.** The 30-minute on-time tolerance and the 30-day near-expiry window are configuration.
- **Exclusions are flags, not deletions.** Closed outlets are excluded per period. Duplicates key on GST, because keying on name would drop 197 real outlets. Test outlets are `TST%` codes, even though all three are marked ACTIVE.
- **Contradictory source columns lose.** `delay_minutes` disagrees with the timestamps on about 87% of rows, so delay is recomputed. Only APPROVED credit notes count as leakage. Available stock excludes damaged and blocked cases.
- **Ask-anything may state causes it cannot measure.** Invented figures are blocked; invented explanations are not. The measurements sit beside the prose so a reader can judge it.

## With two more weeks

Freight, once an allocation is agreed. Price position, using a hand-labelled match set and a confidence threshold. A shareable investigation view. An evaluation set of real questions for ask-anything, since every serious bug in it so far was found live rather than by tests.

## What breaks first in production

The transform is a full rebuild. That is seconds at 511k lines but not at 100×, so the build and the ledger must go incremental. SQLite is fine on one machine, but many concurrent users need a real warehouse. An investigation costs about six model calls and 15–25 s, so cost and rate limits bite once every manager uses it. Some rules can't be tested properly on this data: X5 had only two duplicate groups and N1 never fired.
