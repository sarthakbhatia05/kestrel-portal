export type Unit = "eaches" | "cases";
export type Grain = "region" | "warehouse" | "route" | "outlet";

/** What a figure was derived from. Displayed with every figure (C4.2). */
export interface MetricBasis {
  metric: string;
  period_start: string;
  period_end: string;
  period_label: string;
  unit: Unit;
  scope: string;
  exclusions_applied: string[];
  unmeasured_count: number;
  tolerance_minutes: number | null;
  source_row_count: number;
}

export interface MetricRow {
  key: string;
  label: string;
  numerator: number;
  denominator: number;
  value: number | null;
}

export interface MetricResult {
  headline: number | null;
  numerator: number;
  denominator: number;
  rows: MetricRow[];
  basis: MetricBasis;
}

export interface OtifRow {
  key: string;
  label: string;
  due_count: number;
  on_time_count: number;
  in_full_count: number;
  otif_count: number;
  on_time_rate: number | null;
  in_full_rate: number | null;
  otif: number | null;
}

export interface OtifResult {
  headline: OtifRow;
  rows: OtifRow[];
  basis: MetricBasis;
}

export type ReturnsGrain = "category" | "reason" | "region";

export interface ReturnsRow {
  key: string;
  label: string;
  credit_note_value_inr: number;
  dispatch_value_inr: number;
  returns_rate: number | null;
  cold_chain_value_inr: number;
  cold_chain_rate: number | null;
}

/** Mirrors MetricBasis's shape but drops `unit` (returns has no
 * eaches/cases toggle) and adds the pending/rejected value that PRD 5.6's
 * APPROVED-only rate would otherwise make invisible. */
export interface ReturnsBasis {
  metric: string;
  period_start: string;
  period_end: string;
  period_label: string;
  scope: string;
  exclusions_applied: string[];
  pending_count: number;
  pending_value_inr: number;
  rejected_count: number;
  rejected_value_inr: number;
  source_row_count: number;
}

export interface ReturnsResult {
  headline: ReturnsRow;
  rows: ReturnsRow[];
  basis: ReturnsBasis;
}

export type NearExpiryGrain = "warehouse" | "category";

export interface NearExpiryRow {
  key: string;
  label: string;
  near_expiry_cases: number;
  total_available_cases: number;
  near_expiry_rate: number | null;
  near_expiry_value_inr: number;
}

/** Inventory is a weekly snapshot, not a period range, so this basis states
 * snapshot_date and threshold_days instead of a period. No exclusion rule
 * (PRD 6.3) is scoped to warehouses, so there is no exclusions_applied
 * either -- unlike every other basis. */
export interface NearExpiryBasis {
  metric: string;
  snapshot_date: string;
  scope: string;
  threshold_days: number;
  damaged_cases: number;
  damaged_value_inr: number;
  blocked_cases: number;
  blocked_value_inr: number;
  source_row_count: number;
}

export interface NearExpiryResult {
  headline: NearExpiryRow;
  rows: NearExpiryRow[];
  basis: NearExpiryBasis;
}

export type ExcursionsGrain = "month" | "route" | "warehouse";

export interface ExcursionsRow {
  key: string;
  label: string;
  chilled_count: number;
  excursion_count: number;
  excursion_rate: number | null;
}

/** Mirrors ReturnsBasis's shape (a period, not a snapshot) but has no
 * unit toggle and no pending/rejected concept -- just the exclusions and
 * the chilled-delivery count the rate was computed over. */
export interface ExcursionsBasis {
  metric: string;
  period_start: string;
  period_end: string;
  period_label: string;
  scope: string;
  exclusions_applied: string[];
  source_row_count: number;
}

export interface ExcursionsResult {
  headline: ExcursionsRow;
  rows: ExcursionsRow[];
  basis: ExcursionsBasis;
}
