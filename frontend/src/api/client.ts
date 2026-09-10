import type {
  AskAnswer,
  AskCapability,
  AskTurn,
  ExcursionsGrain,
  ExcursionsResult,
  Grain,
  MetricResult,
  NearExpiryGrain,
  NearExpiryResult,
  OtifResult,
  ReturnsGrain,
  ReturnsResult,
  AskEvent,
  LedgerPage,
  QualityResult,
  ScopeOptions,
  Unit,
} from "./types";

export interface FillRateParams {
  grain?: Grain;
  unit?: Unit;
  regionId?: number | null;
  period?: string;
  ascending?: boolean;
  limit?: number;
  includeExcluded?: boolean;
  q?: string;
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
    q: params.q,
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
  q?: string;
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
    q: params.q,
  });
}

export interface ReturnsParams {
  grain?: ReturnsGrain;
  regionId?: number | null;
  period?: string;
  ascending?: boolean;
  limit?: number;
  includeExcluded?: boolean;
  q?: string;
}

export function fetchReturns(params: ReturnsParams = {}): Promise<ReturnsResult> {
  return get<ReturnsResult>("/api/service/returns", {
    grain: params.grain ?? "category",
    region_id: params.regionId,
    period: params.period ?? "latest",
    ascending: params.ascending,
    limit: params.limit,
    include_excluded: params.includeExcluded,
    q: params.q,
  });
}

export interface NearExpiryParams {
  grain?: NearExpiryGrain;
  regionId?: number | null;
  snapshotDate?: string;
  ascending?: boolean;
  limit?: number;
  thresholdDays?: number;
  q?: string;
}

export function fetchNearExpiry(params: NearExpiryParams = {}): Promise<NearExpiryResult> {
  return get<NearExpiryResult>("/api/service/near-expiry", {
    grain: params.grain ?? "category",
    region_id: params.regionId,
    snapshot_date: params.snapshotDate,
    ascending: params.ascending,
    limit: params.limit,
    threshold_days: params.thresholdDays,
    q: params.q,
  });
}

export interface ExcursionsParams {
  grain?: ExcursionsGrain;
  regionId?: number | null;
  period?: string;
  ascending?: boolean;
  limit?: number;
  includeExcluded?: boolean;
  q?: string;
}

export function fetchExcursions(params: ExcursionsParams = {}): Promise<ExcursionsResult> {
  return get<ExcursionsResult>("/api/service/excursions", {
    grain: params.grain ?? "route",
    region_id: params.regionId,
    period: params.period ?? "latest",
    ascending: params.ascending,
    limit: params.limit,
    include_excluded: params.includeExcluded,
    q: params.q,
  });
}

export function fetchAskCapability(): Promise<AskCapability> {
  return get<AskCapability>("/api/service/ask/capability", {});
}

export async function postAsk(body: {
  question: string;
  window: AskTurn[];
  regionId: number | null;
  period?: string;
}): Promise<AskAnswer> {
  const response = await fetch("/api/service/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question: body.question,
      window: body.window,
      region_id: body.regionId,
      period: body.period,
    }),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new ApiError(
      payload?.error?.code ?? "UNKNOWN",
      payload?.error?.message ?? `Request failed with ${response.status}`,
    );
  }
  return response.json() as Promise<AskAnswer>;
}

/**
 * The regions and periods the selectors offer.
 *
 * Fetched rather than hard-coded: the server derives periods from the
 * order dates actually present, so the dropdown can never offer a period
 * that renders five empty cards.
 */
export function fetchScope(): Promise<ScopeOptions> {
  return get<ScopeOptions>("/api/service/reference/scope", {});
}

/** What every other screen excludes, for the selected scope (PRD 6.4). */
export function fetchQuality(params: {
  regionId: number | null;
  period: string;
}): Promise<QualityResult> {
  return get<QualityResult>("/api/service/quality", {
    region_id: params.regionId,
    period: params.period,
  });
}

/** The ledger entries behind one rule's count. Build-wide, not scoped. */
export function fetchLedger(params: {
  rule: string;
  limit: number;
  offset: number;
}): Promise<LedgerPage> {
  return get<LedgerPage>("/api/service/quality/ledger", params);
}

/**
 * Ask, streaming each measurement as the investigation takes it.
 *
 * The server emits one JSON object per SSE frame, each tagged with a
 * `type`. Frames can be split across network chunks, so the buffer is
 * drained on blank-line boundaries rather than per chunk — a step landing
 * mid-packet would otherwise be parsed as truncated JSON.
 */
export async function streamAsk(
  body: {
    question: string;
    window: AskTurn[];
    regionId: number | null;
    period?: string;
  },
  onEvent: (event: AskEvent) => void,
): Promise<void> {
  const response = await fetch("/api/service/ask/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question: body.question,
      window: body.window,
      region_id: body.regionId,
      period: body.period,
    }),
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new ApiError(
      payload?.error?.code ?? "UNKNOWN",
      payload?.error?.message ?? `Request failed with ${response.status}`,
    );
  }
  if (!response.body) throw new ApiError("NO_STREAM", "The server sent no response body.");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const line = frame.split("\n").find((part) => part.startsWith("data: "));
      if (line) onEvent(JSON.parse(line.slice("data: ".length)) as AskEvent);
      boundary = buffer.indexOf("\n\n");
    }
  }
}
