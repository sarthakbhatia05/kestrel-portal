# Kestrel Provisions — Supply Chain Control Tower

Single, documented, reproducible answers for Kestrel Provisions' daily supply chain
operations — replacing the ~90 minutes a day currently spent adjudicating between
systems that each hold a partial, differently-shaped view of the same events.

## Status

Pre-implementation. The product requirements are defined in [PRD.md](PRD.md); nothing
has been built yet.

## What it will cover (v1)

| Ref | Capability |
|---|---|
| C1 | Data foundation: ingestion, normalisation and quality ledger |
| C2 | Service performance: fill rate and OTIF |
| C3 | Cold chain and returns: excursions, near-expiry stock, credit note leakage |
| C4 | Ask-anything: natural language querying over C2 and C3 |
| C5 | Scoping: national and per-region views |

Metric definitions in [PRD.md](PRD.md) §5 are normative — every surface reports a
figure using exactly one implementation of each metric.

## Getting started

Setup instructions will be added alongside the first working slice. Per NF1, the
project must cold-start on a clean machine from documented commands with no
undocumented prerequisites.
