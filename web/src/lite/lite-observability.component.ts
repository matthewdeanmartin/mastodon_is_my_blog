import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';

import {
  ApiBucket,
  bucketAvgLatency,
  bucketErrorRate,
  dailySeries,
  endpointRows,
  hourlySeries,
  recentHours,
} from './lite-api-stats';
import { LiteApiStatsService } from './lite-api-stats.service';

@Component({
  selector: 'app-lite-observability',
  imports: [CommonModule],
  templateUrl: './lite-observability.component.html',
  styleUrl: './lite-observability.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LiteObservabilityComponent {
  private readonly statsService = inject(LiteApiStatsService);

  readonly stats = this.statsService.stats;
  readonly lastDay = computed(() => recentHours(this.stats(), 24));
  readonly lastHour = computed(() => recentHours(this.stats(), 1));
  readonly hourly = computed(() => hourlySeries(this.stats(), 24));
  readonly hourlyMax = computed(() =>
    this.hourly().reduce((max, point) => Math.max(max, point.bucket.calls), 0),
  );
  readonly daily = computed(() => dailySeries(this.stats(), 14));
  readonly dailyMax = computed(() =>
    this.daily().reduce((max, point) => Math.max(max, point.bucket.calls), 0),
  );
  readonly endpoints = computed(() => endpointRows(this.stats()));

  errorRatePct(bucket: ApiBucket): string {
    return `${(bucketErrorRate(bucket) * 100).toFixed(1)}%`;
  }

  avgLatency(bucket: ApiBucket): string {
    return bucket.calls > 0 ? `${Math.round(bucketAvgLatency(bucket))} ms` : '—';
  }

  barHeight(calls: number, max: number): string {
    if (max === 0 || calls === 0) return '2px';
    return `${Math.max(3, (calls / max) * 110)}px`;
  }

  barTitle(label: string, bucket: ApiBucket): string {
    return `${label} — ${bucket.calls} calls, ${bucket.errors} errors, avg ${this.avgLatency(bucket)}`;
  }

  rateLimitNote(): string {
    const stats = this.stats();
    if (stats.rateLimitRemaining === null) return 'No rate-limit headers seen yet.';
    const limit = stats.rateLimitLimit !== null ? ` of ${stats.rateLimitLimit}` : '';
    return `${stats.rateLimitRemaining}${limit} requests left in the instance's current window.`;
  }

  reset(): void {
    this.statsService.reset();
  }
}
