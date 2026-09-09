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

CREATE TABLE dim_product (
    product_id       INTEGER PRIMARY KEY,
    sku_code         TEXT NOT NULL,
    category         TEXT,
    case_pack        INTEGER,
    list_price_inr   REAL
);

CREATE TABLE dim_warehouse (
    warehouse_id     INTEGER PRIMARY KEY,
    warehouse_code   TEXT NOT NULL,
    warehouse_name   TEXT NOT NULL,
    region_id        INTEGER
);

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
    dispatched_value_inr REAL NOT NULL,
    short_reason_code    TEXT,
    is_excluded          INTEGER NOT NULL DEFAULT 0,
    exclusion_rules      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX ix_fol_date ON fact_order_line (order_date);
CREATE INDEX ix_fol_outlet ON fact_order_line (outlet_id);
CREATE INDEX ix_fol_region ON fact_order_line (region_id);

CREATE TABLE fact_delivery (
    delivery_id           INTEGER PRIMARY KEY,
    order_id              INTEGER NOT NULL,
    planned_arrival       TEXT NOT NULL,
    delay_minutes         REAL,
    outlet_id             INTEGER NOT NULL,
    region_id             INTEGER,
    warehouse_id          INTEGER,
    route_id              INTEGER,
    ordered_qty_eaches    REAL NOT NULL,
    delivered_qty_eaches  REAL NOT NULL,
    is_excluded           INTEGER NOT NULL DEFAULT 0,
    exclusion_rules       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX ix_fd_planned ON fact_delivery (planned_arrival);
CREATE INDEX ix_fd_outlet ON fact_delivery (outlet_id);
CREATE INDEX ix_fd_region ON fact_delivery (region_id);

CREATE TABLE fact_return (
    return_id             INTEGER PRIMARY KEY,
    credit_note_number    TEXT NOT NULL,
    order_id              INTEGER,
    order_line_id         INTEGER,
    outlet_id             INTEGER,
    region_id             INTEGER,
    product_id            INTEGER,
    category              TEXT,
    return_date           TEXT NOT NULL,
    return_qty            REAL NOT NULL,
    return_qty_orig_sign  INTEGER NOT NULL,
    qty_uom               TEXT,
    return_reason_code    TEXT,
    credit_note_value_inr REAL NOT NULL,
    disposition           TEXT,
    status                TEXT NOT NULL,
    is_excluded           INTEGER NOT NULL DEFAULT 0,
    exclusion_rules       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX ix_fr_date ON fact_return (return_date);
CREATE INDEX ix_fr_region ON fact_return (region_id);
CREATE INDEX ix_fr_category ON fact_return (category);

CREATE TABLE fact_inventory_snapshot (
    snapshot_id               INTEGER PRIMARY KEY,
    snapshot_date             TEXT NOT NULL,
    warehouse_id              INTEGER NOT NULL,
    region_id                 INTEGER,
    product_id                INTEGER NOT NULL,
    category                  TEXT,
    batch_id                  TEXT,
    on_hand_cases             REAL NOT NULL,
    allocated_cases           REAL NOT NULL,
    damaged_cases             REAL NOT NULL,
    blocked_cases             REAL NOT NULL,
    available_cases           REAL NOT NULL,
    days_of_cover             REAL,
    expiry_date                TEXT NOT NULL,
    remaining_shelf_life_days INTEGER NOT NULL,
    ageing_bucket             TEXT,
    storage_temp_celsius      REAL,
    is_excluded               INTEGER NOT NULL DEFAULT 0,
    exclusion_rules           TEXT NOT NULL DEFAULT ''
);
CREATE INDEX ix_fis_snapshot_date ON fact_inventory_snapshot (snapshot_date);
CREATE INDEX ix_fis_warehouse ON fact_inventory_snapshot (warehouse_id);
CREATE INDEX ix_fis_region ON fact_inventory_snapshot (region_id);
CREATE INDEX ix_fis_category ON fact_inventory_snapshot (category);
"""
