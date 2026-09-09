import type { Grain, MetricResult, OtifResult, Unit } from "./types";

export interface FillRateParams {
  grain?: Grain;
  unit?: Unit;
  regionId?: number | null;
  period?: string;
  ascending?: boolean;
  limit?: number;
  includeExcluded?: boolean;
}

export class ApiError extends Error {
  code: string;

  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

async function get<T>(path: string, params: Record<string, unknown>): Promise<T> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) query.set(key, String(value));
  }

  const response = await fetch(`${path}?${query}`);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(
      body?.error?.code ?? "UNKNOWN",
      body?.error?.message ?? `Request failed with ${response.status}`,
    );
  }
  return response.json() as Promise<T>;
}

export function fetchFillRate(params: FillRateParams = {}): Promise<MetricResult> {
  return get<MetricResult>("/api/service/fill-rate", {
    grain: params.grain ?? "outlet",
    unit: params.unit ?? "eaches",
    region_id: params.regionId,
    period: params.period ?? "latest",
    ascending: params.ascending,
    limit: params.limit,
    include_excluded: params.includeExcluded,
  });
}

export interface OtifParams {
  grain?: Grain;
  regionId?: number | null;
  period?: string;
  ascending?: boolean;
  limit?: number;
  includeExcluded?: boolean;
  toleranceMinutes?: number;
}

export function fetchOtif(params: OtifParams = {}): Promise<OtifResult> {
  return get<OtifResult>("/api/service/otif", {
    grain: params.grain ?? "outlet",
    region_id: params.regionId,
    period: params.period ?? "latest",
    ascending: params.ascending,
    limit: params.limit,
    include_excluded: params.includeExcluded,
    tolerance_minutes: params.toleranceMinutes,
  });
}
