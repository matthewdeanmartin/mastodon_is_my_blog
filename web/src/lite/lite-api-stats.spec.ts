import { describe, expect, it } from 'vitest';

import {
  API_STATS_LIMITS,
  ApiCallSample,
  bucketAvgLatency,
  bucketErrorRate,
  dailySeries,
  emptyApiStats,
  endpointRows,
  hourlySeries,
  recentHours,
  recordApiCall,
} from './lite-api-stats';

const NOW = new Date(2026, 6, 15, 12, 0).getTime();

describe('Lite API stats aggregates', () => {
  it('folds calls into totals, endpoint, hour, and day buckets', () => {
    let stats = emptyApiStats();
    stats = recordApiCall(stats, sample({ durationMs: 100 }), NOW);
    stats = recordApiCall(stats, sample({ ok: false, rateLimited: true, durationMs: 300 }), NOW);

    expect(stats.totals).toEqual({ calls: 2, errors: 1, rateLimited: 1, durationMs: 400 });
    expect(stats.perEndpoint['home timeline'].calls).toBe(2);
    expect(Object.keys(stats.hourly)).toHaveLength(1);
    expect(Object.keys(stats.daily)).toHaveLength(1);
    expect(bucketErrorRate(stats.totals)).toBe(0.5);
    expect(bucketAvgLatency(stats.totals)).toBe(200);
  });

  it('keeps only a bounded number of hour and day buckets', () => {
    let stats = emptyApiStats();
    for (let hour = 0; hour < API_STATS_LIMITS.hourlyBuckets + 20; hour += 1) {
      stats = recordApiCall(stats, sample({}), NOW + hour * 3_600_000);
    }

    expect(Object.keys(stats.hourly).length).toBeLessThanOrEqual(API_STATS_LIMITS.hourlyBuckets);
    expect(Object.keys(stats.daily).length).toBeLessThanOrEqual(API_STATS_LIMITS.dailyBuckets);
    // Totals keep counting even after old buckets are dropped.
    expect(stats.totals.calls).toBe(API_STATS_LIMITS.hourlyBuckets + 20);
  });

  it('remembers the latest rate-limit headroom', () => {
    let stats = emptyApiStats();
    stats = recordApiCall(stats, sample({ rateLimitRemaining: 250, rateLimitLimit: 300 }), NOW);
    stats = recordApiCall(stats, sample({}), NOW);

    expect(stats.rateLimitRemaining).toBe(250);
    expect(stats.rateLimitLimit).toBe(300);
  });

  it('sums the trailing hours including empty ones', () => {
    let stats = emptyApiStats();
    stats = recordApiCall(stats, sample({}), NOW - 2 * 3_600_000);
    stats = recordApiCall(stats, sample({}), NOW);

    expect(recentHours(stats, 24, NOW).calls).toBe(2);
    expect(recentHours(stats, 1, NOW).calls).toBe(1);
  });

  it('produces fixed-length chart series with zero-filled gaps', () => {
    const stats = recordApiCall(emptyApiStats(), sample({}), NOW);

    expect(hourlySeries(stats, 24, NOW)).toHaveLength(24);
    expect(dailySeries(stats, 14, NOW)).toHaveLength(14);
    expect(hourlySeries(stats, 24, NOW)[23].bucket.calls).toBe(1);
  });

  it('lists endpoints busiest first', () => {
    let stats = emptyApiStats();
    stats = recordApiCall(stats, sample({ endpoint: 'notifications' }), NOW);
    stats = recordApiCall(stats, sample({}), NOW);
    stats = recordApiCall(stats, sample({}), NOW);

    const rows = endpointRows(stats);
    expect(rows[0].endpoint).toBe('home timeline');
    expect(rows[0].calls).toBe(2);
  });

  it('does not mutate the previous stats object', () => {
    const before = emptyApiStats();
    recordApiCall(before, sample({}), NOW);

    expect(before.totals.calls).toBe(0);
  });
});

function sample(overrides: Partial<ApiCallSample>): ApiCallSample {
  return {
    endpoint: 'home timeline',
    ok: true,
    rateLimited: false,
    durationMs: 50,
    ...overrides,
  };
}
