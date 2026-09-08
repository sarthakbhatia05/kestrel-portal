# Product Requirements Document

**Kestrel Provisions — Supply Chain Control Tower**

| | |
|---|---|
| Status | Draft for review |
| Version | 0.1 |
| Date | 8 September 2026 |
| Owner | Delivery team |

---

## 1. Problem statement

Kestrel Provisions distributes ambient, chilled and frozen grocery products from eight distribution centres to approximately 700 retail outlets across five regions, through general trade, modern trade, HORECA and e-commerce dark store channels.

Operational data is fragmented across systems that were never designed to reconcile. Orders originate from three separate channels, deliveries are tracked by two telematics vendors with different data conventions, and freight is billed by five carriers on an external platform. Each system holds a partial and differently-shaped view of the same events.

The consequence is not missing data. It is **contested data**. When leadership asks a routine operational question, multiple teams answer from different systems and produce different numbers, none of which is obviously wrong. Roughly ninety minutes of each operating day is spent adjudicating between those numbers before any decision can be made.

**The product must replace that adjudication with a single, documented, reproducible answer.**

---

## 2. Goals

| # | Goal | Measured by |
|---|---|---|
| G1 | Establish one canonical definition per operational metric | Every metric has exactly one implementation, shared by all surfaces |
| G2 | Surface service and margin loss without the user having to ask | Worst performers visible on the landing view, no drill-down required |
| G3 | Allow ad-hoc questions in natural language | User can ask an unanticipated question and receive a figure with its basis |
| G4 | Make data quality visible rather than silent | Every excluded or repaired record is counted and attributable |
| G5 | Open reliably with no setup knowledge | Cold start on a clean machine from documented commands |

### Non-goals

- Replacing the ERP, WMS or order capture systems.
- Correcting data in source systems. The product observes and reports; it does not write back.
- Real-time or streaming operation. Daily granularity is sufficient.
- Forecasting, optimisation or prescriptive recommendation.

---

## 3. Users

### P1 — Head of Supply Chain Operations (primary)

National scope. Opens the product first thing each morning to establish what happened yesterday. Needs the exceptions surfaced, not a canvas to explore. Low tolerance for setup, navigation depth, or charts requiring interpretation. Their questions change daily and they will not raise a ticket for each one.

**Success looks like:** they stop reconstructing yesterday by hand.

### P2 — Regional Manager

Single-region scope. Same questions as P1, narrowed to their own region, and needs to see how their region compares to the others.

**Success looks like:** they answer P1's questions before being asked.

### P3 — National Sales Manager (secondary)

Commercially focused. Cares about customer-facing service measures — specifically units short, because that is the basis on which modern trade accounts levy penalties.

**Success looks like:** the reported service number matches the number the customer is quoting back at them.

---

## 4. Scope

### In scope for v1

| Ref | Capability |
|---|---|
| **C1** | Data foundation: ingestion, normalisation and quality ledger |
| **C2** | Service performance: fill rate and OTIF |
| **C3** | Cold chain and returns: excursions, near-expiry stock, credit note leakage |
| **C4** | Ask-anything: natural language querying over C2 and C3 |
| **C5** | Scoping: national and per-region views |

### Explicitly out of scope for v1

| Deferred | Rationale |
|---|---|
| Freight cost per delivered case | Actual billed cost lives only in the external carrier platform, and carrier invoices carry no delivery-level identifier. Attributing invoice value to individual deliveries requires an allocation model that must be agreed with Finance before it is built, not invented by the delivery team. |
| Competitor price position | Requires reconciling third-party listing titles to internal SKUs with no shared key. The matching heuristic is the entire cost of the feature and its accuracy cannot be asserted without a validation set. |
| Weather and public holiday enrichment | Explanatory rather than diagnostic. Adds interpretive surface before the base measures are trusted. |
| Authentication, roles and permissions | Single-tenant internal deployment behind an existing network boundary. Region scoping is a view filter, not a security control, and is documented as such. |
| Alerting, subscriptions and scheduled digests | Depends on thresholds that cannot be set until baseline distributions are observed. |

---

## 5. Metric definitions

These are normative. Any surface reporting a figure below must use these definitions and no other.

### 5.1 Unit of measure

Order lines are captured in mixed units — some in cases, some in eaches — and the case configuration is captured per line at order time. All quantities are therefore **normalised to eaches at ingestion** using the line's captured case pack, falling back to the product master case pack where the line value is absent or implausible. Case-denominated figures are derived from the normalised each figure, never computed independently.

This guarantees that the case view and the each view of the same event can never disagree.

### 5.2 Fill rate

```
fill_rate_eaches = SUM(delivered_qty_eaches) / SUM(ordered_qty_eaches)

fill_rate_cases  = SUM(delivered_qty_eaches / case_pack)
                 / SUM(ordered_qty_eaches   / case_pack)
```

Reported at region, warehouse, route and outlet grain.

**Default unit is eaches.** Modern trade penalties are assessed on units short, and a material share of the SKU base ships in mixed configurations, so the each measure is the one that carries commercial consequence. The case measure remains available as a toggle because it is the unit in which service is committed to customers and is the existing operational language.

Cancelled orders are excluded from both numerator and denominator. Open orders are excluded as not yet due.

### 5.3 On-Time In-Full (OTIF)

A delivery is **in full** when its constituent lines are fully delivered (fill rate = 100% in eaches).

A delivery is **on time** when actual arrival is no later than planned arrival plus a tolerance window. **Tolerance is 30 minutes by default and is configurable.** No tolerance is documented in the source systems; 30 minutes is an assumption pending confirmation from Operations and is exposed as a setting rather than hard-coded.

```
otif = COUNT(deliveries on_time AND in_full) / COUNT(deliveries due)
```

Deliveries with no recorded actual arrival are treated as **not on time** and reported separately as an unmeasured count, so the denominator is never silently reduced.

### 5.4 Temperature excursion rate

```
excursion_rate = COUNT(chilled deliveries with excursion) * 100
               / COUNT(chilled deliveries)
```

Expressed per hundred chilled deliveries, reported by month. A delivery is chilled if any line on it is a chilled or frozen product.

Only a breach flag and a peak temperature are captured per delivery. Excursion **duration and severity profile are not derivable** and must not be inferred.

### 5.5 Near-expiry stock

Stock is near-expiry when, at the snapshot date, remaining shelf life is **30 days or fewer**. The threshold is configurable and applies uniformly; per-category thresholds are a known future requirement.

Inventory is captured weekly. All stock positions are therefore as-at the most recent snapshot, never as-at today, and must be labelled with the snapshot date wherever displayed.

Damaged and blocked quantities are excluded from available stock and reported separately.

### 5.6 Returns and credit note leakage

```
returns_rate = SUM(credit_note_value) / SUM(dispatch_value)
```

Reported by category, by return reason, and by region. Return quantities arrive with inconsistent sign conventions across upstream feeds and are normalised to a positive magnitude at ingestion, with the original sign retained for audit.

Reason codes are reported as captured. Cold-chain-attributable returns are those coded as cold chain breach or near expiry.

### 5.7 Fiscal calendar

The financial year runs **April to March**. Q1 is April to June.

All period selectors, quarter labels and "last complete quarter" logic follow the fiscal calendar, not the calendar year. The landing view leads with the current or most recent complete **fiscal Q1** headline figures.

---

## 6. Data foundation (C1)

### 6.1 Requirement

Source data is not fit for direct reporting. A dedicated transformation stage must produce a curated, query-ready dataset. All reporting surfaces read the curated dataset only; none query source tables directly.

This is a hard architectural constraint, not a preference. It is what makes G1 enforceable.

### 6.2 Normalisation rules

| Ref | Rule |
|---|---|
| N1 | Order line quantities converted to eaches using line-level case pack, falling back to product master |
| N2 | Order timestamps parsed from three distinct source formats; UTC-denominated timestamps converted to Asia/Kolkata |
| N3 | Delivery arrival timestamps parsed from two vendor-specific formats into a single representation |
| N4 | Return quantities sign-normalised to positive magnitude |
| N5 | City names mapped to a canonical form via an explicit, reviewable mapping table |
| N6 | Product prices resolved as-at order date from the price history windows, not from current master values |

### 6.3 Exclusion rules

| Ref | Rule | Applies to |
|---|---|---|
| X1 | Soft-deleted outlets excluded | All measures |
| X2 | Test and migration outlets excluded | All measures |
| X3 | Closed outlets excluded from current-period views, retained in historical periods up to their closure date | Period-scoped measures |
| X4 | Cancelled orders excluded | Service measures |
| X5 | Duplicate outlet records resolved to a single surviving entity | All measures |

Exclusions must be **applied by default and reversible on request**. A user must be able to see what was excluded.

### 6.4 Data quality ledger

Every record that is excluded, repaired or rejected during transformation is written to a quality ledger recording the rule applied, the affected entity and the reason.

The ledger is surfaced as a **first-class view in the product**, not an engineering artifact. It must state, in counts, what the numbers on every other screen exclude.

### 6.5 Known integrity issues to be reported, not silently corrected

- Order header values do not reconcile to the sum of their line values for at least one source system. The variance is to be **quantified and displayed**, not adjusted away. Line values are treated as authoritative for reporting.
- Outlet route and salesperson assignments are current-state only, with no history. Historical attribution to route and salesperson is therefore approximate and must be labelled as such wherever it appears.
- Credit note approval dates are never populated. Approval latency is not reportable.

---

## 7. Functional requirements

### C2 — Service performance

| Ref | Requirement | Priority |
|---|---|---|
| C2.1 | Fill rate by region, warehouse, route and outlet, for a selected period | Must |
| C2.2 | Unit toggle between eaches and cases, defaulting to eaches | Must |
| C2.3 | Worst performers ranked and visible on entry, without navigation | Must |
| C2.4 | OTIF by region, warehouse and route, with on-time and in-full separable | Must |
| C2.5 | Exclusion of closed, deleted and test outlets by default | Must |
| C2.6 | Short-delivery reason code breakdown | Should |
| C2.7 | Period-over-period movement on headline figures | Should |

### C3 — Cold chain and returns

| Ref | Requirement | Priority |
|---|---|---|
| C3.1 | Temperature excursions per hundred chilled deliveries, by month | Must |
| C3.2 | Excursion concentration by route and warehouse | Must |
| C3.3 | Near-expiry stock by warehouse and category, as-at the latest snapshot | Must |
| C3.4 | Returns value by category and reason code, as a percentage of dispatch value | Must |
| C3.5 | Cold-chain-attributable returns isolated from other return reasons | Must |
| C3.6 | Disposition split (scrap, restock, vendor recovery) on returned value | Should |

### C4 — Ask-anything

| Ref | Requirement | Priority |
|---|---|---|
| C4.1 | Accept a plain-English question and return a direct answer containing the figure | Must |
| C4.2 | Every answer states the period, filters, unit of measure and exclusions applied | Must |
| C4.3 | Answers are computed by the same metric implementations that serve the dashboard | Must |
| C4.4 | Questions outside the supported metric set are **declined explicitly**, naming what is supported | Must |
| C4.5 | Supporting figures are returned alongside the answer, not only prose | Must |
| C4.6 | The product remains fully usable when the language capability is unavailable | Must |

**C4.4 is a firm requirement.** The product must not generate a plausible number for a question it cannot actually answer. A confidently wrong figure reproduces the exact failure this product exists to eliminate, and is worse than a refusal.

### C5 — Scoping

| Ref | Requirement | Priority |
|---|---|---|
| C5.1 | National view across all regions | Must |
| C5.2 | Region-scoped view showing that region against the national position | Must |
| C5.3 | Selected scope applies consistently to every surface, including ask-anything | Must |

---

## 8. Non-functional requirements

| Ref | Requirement |
|---|---|
| NF1 | Cold start on a clean machine from documented commands, with no undocumented prerequisites |
| NF2 | Operates fully offline once source data is present; no account, credential or paid service required to run the reporting surfaces |
| NF3 | Landing view renders in under two seconds on the full dataset |
| NF4 | A natural language answer returns within ten seconds |
| NF5 | Transformation stage is idempotent and safely re-runnable |
| NF6 | Source data is never mutated |
| NF7 | Absence of the language capability degrades only the ask-anything surface |
| NF8 | Metric logic is unit-testable independently of the interface |

---

## 9. Assumptions

Recorded where source documentation is absent, incomplete or contradicted by the data. Each is a decision made in order to proceed, and each is revisable.

| # | Assumption |
|---|---|
| A1 | On-time tolerance is 30 minutes. No documented SLA exists; exposed as configuration. |
| A2 | Near-expiry is 30 days remaining shelf life, applied uniformly across categories. |
| A3 | Line values are authoritative where they disagree with order header values. |
| A4 | Deliveries with no actual arrival recorded are not on time, and are counted separately as unmeasured. |
| A5 | Missing or implausible line-level case pack falls back to the product master case pack. |
| A6 | An outlet identified as test, migration or soft-deleted is excluded from all operational measures. |
| A7 | Fiscal Q1 means April to June. |
| A8 | Current route and salesperson assignments are applied to historical periods, as no assignment history exists. |

---

## 10. Success criteria

The product is successful at v1 when:

1. A single figure is produced for any in-scope metric, and its derivation can be traced from the screen back to source rows.
2. The primary user can identify the worst-performing region, warehouse, route and outlet within one screen of opening the product.
3. An unanticipated in-scope question can be asked in plain English and answered with its basis stated.
4. An out-of-scope question is refused rather than answered incorrectly.
5. The volume and nature of excluded data is visible and quantified.
6. A person who has never seen the system can start it from the documentation alone.

---

## 11. Future scope

Ordered by expected value, not by effort.

1. **Freight cost per delivered case.** Requires an agreed allocation model for distributing carrier invoice value across deliveries, since invoices carry no delivery-level key. Blocked on Finance sign-off, not on engineering.
2. **Competitor price position.** Requires a validated SKU matching approach and an accepted confidence threshold below which matches are not asserted.
3. **Assignment history for route and salesperson.** Removes the approximation in A8 and makes historical attribution exact.
4. **Per-category near-expiry thresholds.** Shelf life varies by an order of magnitude across the range; a single threshold under- and over-reports simultaneously.
5. **Threshold-based alerting.** Deferred until baseline distributions are observed and thresholds can be set from evidence.
6. **Source system data quality feedback loop.** The quality ledger identifies which upstream system produces which defect; that signal is currently consumed only by this product and should be returned to the system owners.
