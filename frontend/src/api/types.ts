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

export type AskMetric =
  | "fill_rate"
  | "otif"
  | "returns"
  | "near_expiry"
  | "excursions"
  | "unsupported";

export type AskGrain =
  | "region"
  | "warehouse"
  | "route"
  | "outlet"
  | "category"
  | "reason"
  | "month";

/** What a question resolved to. Carried back on the next turn so a
 * follow-up ("and Delhi?") has something to build on -- never the answer,
 * so no computed figure ever re-enters the model's context. */
export interface AskIntent {
  metric: AskMetric;
  grain: AskGrain | null;
  period: string;
  region_id: number | null;
  unit: Unit;
  limit: number | null;
  ascending: boolean;
  q: string | null;
  include_excluded: boolean;
  mode: AskMode;
}

/** Whether a question needs one measurement or several compared. */
export type AskMode = "lookup" | "investigate";

/** One measurement an investigation took, and why.
 *
 * The `result` is stripped from the streamed step (the rows arrive with
 * the final answer); `delta` is the change against an earlier step of the
 * same metric, computed server-side so no figure originates with the model. */
export interface StepRecord {
  reasoning: string;
  intent: AskIntent;
  summary: string;
  error: string | null;
  delta: number | null;
  /** Which way round the comparison ran, e.g. "FY26 Q4 to FY27 Q1". */
  delta_basis: string | null;
}

export interface AskTurn {
  question: string;
  intent: AskIntent;
}

export type AskResult =
  | MetricResult
  | OtifResult
  | ReturnsResult
  | NearExpiryResult
  | ExcursionsResult;

export interface AskAnswer {
  question: string;
  intent: AskIntent | null;
  /** Deterministic and always present: the answer of record. */
  answer: string;
  /** Optional model framing that passed the numeric guard. */
  prose: string | null;
  result: AskResult | null;
  declined: boolean;
  supported_metrics: string[] | null;
  /** Present only for an investigation: the measurements actually run. */
  steps: StepRecord[] | null;
}

/** One frame of a streamed answer. */
export type AskEvent =
  | ({ type: "step" } & StepRecord)
  | ({ type: "answer" } & AskAnswer)
  | { type: "error"; message: string };

export interface AskCapability {
  available: boolean;
  supported_metrics: string[];
}

/** Scope options, derived from the data rather than hard-coded. */
export interface RegionOption {
  region_id: number;
  region_name: string;
}

export interface PeriodOption {
  value: string;
  label: string;
  kind: "quarter" | "month" | "relative";
}

export interface ScopeOptions {
  regions: RegionOption[];
  periods: PeriodOption[];
}

/** Data quality (PRD 6.4). */
export interface RuleCount {
  rule_ref: string;
  rule_name: string;
  count: number;
}

/** What one measure leaves out of the selected scope. A record can be
 * excluded by several rules, so `by_rule` counts overlap and can sum to
 * more than `excluded_count`. Counts are null only where no rule applies. */
export interface MeasureExclusions {
  measure: string;
  label: string;
  entity: string;
  applies: boolean;
  in_scope_count: number | null;
  included_count: number | null;
  excluded_count: number | null;
  by_rule: RuleCount[];
  note: string | null;
}

export interface RuleSummary {
  rule_ref: string;
  rule_name: string;
  kind: "normalisation" | "exclusion";
  applied: "build" | "query";
  recorded: boolean;
  /** Ledger entries for the whole build; null when the rule records none. */
  ledger_count: number | null;
}

export interface QualityResult {
  period_start: string;
  period_end: string;
  period_label: string;
  scope: string;
  measures: MeasureExclusions[];
  rules: RuleSummary[];
  built_at: string | null;
}

export interface LedgerEntry {
  ledger_id: number;
  entity_type: string;
  entity_id: string | null;
  action: string;
  reason: string;
  source_system: string | null;
}

export interface LedgerPage {
  rule_ref: string;
  rule_name: string;
  total: number;
  limit: number;
  offset: number;
  entries: LedgerEntry[];
}
