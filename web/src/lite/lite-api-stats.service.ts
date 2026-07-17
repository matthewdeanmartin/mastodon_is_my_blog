import { Injectable, signal } from '@angular/core';
import { ApiCallSample, LiteApiStats, emptyApiStats, recordApiCall } from './lite-api-stats';

const STATS_KEY = 'mimb:lite:v1:api-stats';

/**
 * Running aggregates for every Mastodon API call Lite makes. Only sums and
 * bounded hour/day buckets are stored, so the localStorage footprint is
 * constant — see lite-api-stats.ts for the shape.
 */
@Injectable({ providedIn: 'root' })
export class LiteApiStatsService {
  readonly stats = signal<LiteApiStats>(this.read());

  record(sample: ApiCallSample): void {
    const next = recordApiCall(this.stats(), sample);
    this.stats.set(next);
    try {
      localStorage.setItem(STATS_KEY, JSON.stringify(next));
    } catch {
      // Quota pressure — the in-memory aggregates still work this session.
    }
  }

  reset(): void {
    const empty = emptyApiStats();
    this.stats.set(empty);
    try {
      localStorage.removeItem(STATS_KEY);
    } catch {
      // Ignore storage failures on reset.
    }
  }

  private read(): LiteApiStats {
    try {
      const raw = localStorage.getItem(STATS_KEY);
      if (!raw) return emptyApiStats();
      const parsed = JSON.parse(raw) as LiteApiStats;
      return parsed.version === 1 ? parsed : emptyApiStats();
    } catch {
      return emptyApiStats();
    }
  }
}
