"""DDL for the curated database.

Exclusions are flags, not deletions (PRD 6.3). Excluded rows are retained
with the rule references that excluded them, so the default filter can be
lifted on request and the quality ledger can be reconciled against the
tables it describes.
"""

CURATED_SCHEMA = """
CREATE TABLE build_runs (
    run_id           TEXT PRIMARY KEY,
    started_at       TEXT NOT NULL,
    finished_at      TEXT,
    source_db_path   TEXT NOT NULL,
    table_counts     TEXT
);

CREATE TABLE quality_ledger (
    ledger_id        INTEGER PRIMARY KEY,
    run_id           TEXT NOT NULL,
    rule_ref         TEXT NOT NULL,
    rule_name        TEXT NOT NULL,
    entity_type      TEXT NOT NULL,
    entity_id        TEXT,
    action           TEXT NOT NULL CHECK (action IN ('EXCLUDED','REPAIRED','REJECTED')),
    reason           TEXT NOT NULL,
    source_system    TEXT,
    created_at       TEXT NOT NULL
);
CREATE INDEX ix_ledger_rule ON quality_ledger (rule_ref);

CREATE TABLE dim_region (
    region_id        INTEGER PRIMARY KEY,
    region_code      TEXT NOT NULL,
    region_name      TEXT NOT NULL
);

CREATE TABLE dim_outlet (
    outlet_id        INTEGER PRIMARY KEY,
    outlet_code      TEXT NOT NULL,
    outlet_name      TEXT NOT NULL,
    channel          TEXT,
    city_raw         TEXT,
    city             TEXT,
    region_id        INTEGER,
    route_id         INTEGER,
    salesperson_id   INTEGER,
    status           TEXT,
    closed_date      TEXT,
    is_excluded      INTEGER NOT NULL DEFAULT 0,
    exclusion_rules  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX ix_outlet_region ON dim_outlet (region_id);

CREATE TABLE fact_order_line (
    order_line_id        INTEGER PRIMARY KEY,
    order_id             INTEGER NOT NULL,
    order_date           TEXT NOT NULL,
    outlet_id            INTEGER NOT NULL,
    region_id            INTEGER,
    warehouse_id         INTEGER,
    route_id             INTEGER,
    product_id           INTEGER NOT NULL,
    order_status         TEXT,
    source_system        TEXT,
    qty_uom              TEXT,
    case_pack            INTEGER NOT NULL,
    ordered_qty_eaches   REAL NOT NULL,
    delivered_qty_eaches REAL NOT NULL,
    short_reason_code    TEXT,
    is_excluded          INTEGER NOT NULL DEFAULT 0,
    exclusion_rules      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX ix_fol_date ON fact_order_line (order_date);
CREATE INDEX ix_fol_outlet ON fact_order_line (outlet_id);
CREATE INDEX ix_fol_region ON fact_order_line (region_id);
"""
