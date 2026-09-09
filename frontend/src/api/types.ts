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
