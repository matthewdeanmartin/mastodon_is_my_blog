export interface ApiBucket {
  calls: number;
  errors: number;
  rateLimited: number;
  durationMs: number;
}

export interface ApiEndpointRow extends ApiBucket {
  endpoint: string;
}

export interface LiteApiStats {
  version: 1;
  totals: ApiBucket;
  perEndpoint: Record<string, ApiBucket>;
  /** Keyed by epoch hour (floor(ms / 3600000)), pruned to the newest 48. */
  hourly: Record<string, ApiBucket>;
  /** Keyed by local YYYY-MM-DD, pruned to the newest 30. */
  daily: Record<string, ApiBucket>;
  rateLimitRemaining: number | null;
  rateLimitLimit: number | null;
  updatedAt: number;
}

export const API_STATS_LIMITS = {
  hourlyBuckets: 48,
  dailyBuckets: 30,
} as const;

export interface ApiCallSample {
  endpoint: string;
  ok: boolean;
  rateLimited: boolean;
  durationMs: number;
  rateLimitRemaining?: number | null;
  rateLimitLimit?: number | null;
}

export function emptyApiStats(): LiteApiStats {
  return {
    version: 1,
    totals: emptyBucket(),
    perEndpoint: {},
    hourly: {},
    daily: {},
    rateLimitRemaining: null,
    rateLimitLimit: null,
    updatedAt: Date.now(),
  };
}

/**
 * Fold one API call into the running aggregates. Only sums and counts are
 * kept — never per-call rows — and the hour/day buckets are pruned to a
 * fixed count, so storage stays constant no matter how long Lite runs.
 */
export function recordApiCall(
  stats: LiteApiStats,
  sample: ApiCallSample,
  now: number = Date.now(),
): LiteApiStats {
  const next: LiteApiStats = {
    ...stats,
    totals: { ...stats.totals },
    perEndpoint: { ...stats.perEndpoint },
    hourly: { ...stats.hourly },
    daily: { ...stats.daily },
    updatedAt: now,
  };
  fold(next.totals, sample);
  const endpoint = { ...(next.perEndpoint[sample.endpoint] ?? emptyBucket()) };
  fold(endpoint, sample);
  next.perEndpoint[sample.endpoint] = endpoint;

  const hourKey = String(Math.floor(now / 3_600_000));
  const hour = { ...(next.hourly[hourKey] ?? emptyBucket()) };
  fold(hour, sample);
  next.hourly[hourKey] = hour;
  prune(next.hourly, API_STATS_LIMITS.hourlyBuckets);

  const dayKey = localDay(new Date(now));
  const day = { ...(next.daily[dayKey] ?? emptyBucket()) };
  fold(day, sample);
  next.daily[dayKey] = day;
  prune(next.daily, API_STATS_LIMITS.dailyBuckets);

  if (sample.rateLimitRemaining !== undefined && sample.rateLimitRemaining !== null) {
    next.rateLimitRemaining = sample.rateLimitRemaining;
  }
  if (sample.rateLimitLimit !== undefined && sample.rateLimitLimit !== null) {
    next.rateLimitLimit = sample.rateLimitLimit;
  }
  return next;
}

export function endpointRows(stats: LiteApiStats): ApiEndpointRow[] {
  return Object.entries(stats.perEndpoint)
    .map(([endpoint, bucket]) => ({ endpoint, ...bucket }))
    .sort((left, right) => right.calls - left.calls);
}

export function bucketErrorRate(bucket: ApiBucket): number {
  return bucket.calls > 0 ? bucket.errors / bucket.calls : 0;
}

export function bucketAvgLatency(bucket: ApiBucket): number {
  return bucket.calls > 0 ? bucket.durationMs / bucket.calls : 0;
}

/** Sum the buckets for the last `hours` epoch hours (missing hours = zero). */
export function recentHours(stats: LiteApiStats, hours: number, now: number = Date.now()): ApiBucket {
  const newest = Math.floor(now / 3_600_000);
  const total = emptyBucket();
  for (let hour = newest - hours + 1; hour <= newest; hour += 1) {
    const bucket = stats.hourly[String(hour)];
    if (!bucket) continue;
    total.calls += bucket.calls;
    total.errors += bucket.errors;
    total.rateLimited += bucket.rateLimited;
    total.durationMs += bucket.durationMs;
  }
  return total;
}

/** Newest-last series of the trailing `hours` hour buckets for charting. */
export function hourlySeries(
  stats: LiteApiStats,
  hours: number,
  now: number = Date.now(),
): { label: string; bucket: ApiBucket }[] {
  const newest = Math.floor(now / 3_600_000);
  const series: { label: string; bucket: ApiBucket }[] = [];
  for (let hour = newest - hours + 1; hour <= newest; hour += 1) {
    const date = new Date(hour * 3_600_000);
    series.push({
      label: `${String(date.getHours()).padStart(2, '0')}:00`,
      bucket: stats.hourly[String(hour)] ?? emptyBucket(),
    });
  }
  return series;
}

/** Newest-last series of the trailing `days` day buckets for charting. */
export function dailySeries(
  stats: LiteApiStats,
  days: number,
  now: number = Date.now(),
): { label: string; bucket: ApiBucket }[] {
  const series: { label: string; bucket: ApiBucket }[] = [];
  for (let back = days - 1; back >= 0; back -= 1) {
    const day = localDay(new Date(now - back * 86_400_000));
    series.push({ label: day.slice(5), bucket: stats.daily[day] ?? emptyBucket() });
  }
  return series;
}

function fold(bucket: ApiBucket, sample: ApiCallSample): void {
  bucket.calls += 1;
  if (!sample.ok) bucket.errors += 1;
  if (sample.rateLimited) bucket.rateLimited += 1;
  bucket.durationMs += Math.max(0, sample.durationMs);
}

function prune(buckets: Record<string, ApiBucket>, keep: number): void {
  const keys = Object.keys(buckets).sort();
  for (const key of keys.slice(0, Math.max(0, keys.length - keep))) {
    delete buckets[key];
  }
}

function emptyBucket(): ApiBucket {
  return { calls: 0, errors: 0, rateLimited: 0, durationMs: 0 };
}

function localDay(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${date.getFullYear()}-${month}-${day}`;
}
