import { Component, OnInit, OnDestroy, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Subject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';

import { ApiService } from './api.service';
import {
  ApiSummaryResponse,
  ApiVolumePoint,
  ApiMethodRow,
  ApiLatencyPoint,
  ApiThrottleEvent,
  ApiDataVolumePoint,
  ApiErrorRatePoint,
} from './mastodon';

type BucketOption = 'hour' | 'day' | 'week';

const CHART_COLORS = [
  '#6366f1',
  '#f59e0b',
  '#10b981',
  '#ec4899',
  '#0ea5e9',
  '#a855f7',
  '#ef4444',
  '#14b8a6',
  '#eab308',
  '#8b5cf6',
];

interface BarSegment {
  label: string;
  value: number;
  color: string;
  pct: number;
}

interface LinePoint {
  x: number;
  y: number;
  label: string;
  value: number;
}

interface LineSeries {
  label: string;
  color: string;
  points: LinePoint[];
}

@Component({
  selector: 'app-observability',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './observability.component.html',
})
export class ObservabilityComponent implements OnInit, OnDestroy {
  private api = inject(ApiService);
  private readonly destroy$ = new Subject<void>();

  days = 30;
  bucket: BucketOption = 'day';
  selectedMethod: string | null = null;

  summary: ApiSummaryResponse | null = null;
  summaryLoading = false;
  summaryError: string | null = null;

  volumePoints: ApiVolumePoint[] = [];
  volumeLoading = false;
  volumeError: string | null = null;

  methodRows: ApiMethodRow[] = [];
  methodLoading = false;
  methodError: string | null = null;

  latencyPoints: ApiLatencyPoint[] = [];
  latencyLoading = false;
  latencyError: string | null = null;

  throttleEvents: ApiThrottleEvent[] = [];
  throttleLoading = false;
  throttleError: string | null = null;

  dataVolumePoints: ApiDataVolumePoint[] = [];
  dataVolumeLoading = false;
  dataVolumeError: string | null = null;

  errorRatePoints: ApiErrorRatePoint[] = [];
  errorRateLoading = false;
  errorRateError: string | null = null;

  ngOnInit(): void {
    this.loadAll();
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  loadAll(): void {
    this.loadSummary();
    this.loadVolume();
    this.loadMethods();
    this.loadLatency();
    this.loadThrottles();
    this.loadDataVolume();
    this.loadErrors();
  }

  onDaysChange(): void {
    this.loadAll();
  }

  onBucketChange(): void {
    this.loadVolume();
    this.loadLatency();
  }

  onMethodSelect(method: string | null): void {
    this.selectedMethod = method === this.selectedMethod ? null : method;
    this.loadLatency();
  }

  private loadSummary(): void {
    this.summaryLoading = true;
    this.summaryError = null;
    this.api
      .getObservabilitySummary()
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (data) => {
          this.summary = data;
          this.summaryLoading = false;
        },
        error: () => {
          this.summaryError = 'Failed to load summary';
          this.summaryLoading = false;
        },
      });
  }

  private loadVolume(): void {
    this.volumeLoading = true;
    this.volumeError = null;
    this.api
      .getApiVolume(this.bucket, this.days)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (data) => {
          this.volumePoints = data;
          this.volumeLoading = false;
        },
        error: () => {
          this.volumeError = 'Failed to load volume';
          this.volumeLoading = false;
        },
      });
  }

  private loadMethods(): void {
    this.methodLoading = true;
    this.methodError = null;
    this.api
      .getApiByMethod(this.days)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (data) => {
          this.methodRows = data;
          this.methodLoading = false;
        },
        error: () => {
          this.methodError = 'Failed to load method breakdown';
          this.methodLoading = false;
        },
      });
  }

  private loadLatency(): void {
    this.latencyLoading = true;
    this.latencyError = null;
    this.api
      .getApiLatency(this.selectedMethod, this.bucket, this.days)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (data) => {
          this.latencyPoints = data;
          this.latencyLoading = false;
        },
        error: () => {
          this.latencyError = 'Failed to load latency';
          this.latencyLoading = false;
        },
      });
  }

  private loadThrottles(): void {
    this.throttleLoading = true;
    this.throttleError = null;
    this.api
      .getApiThrottles(this.days)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (data) => {
          this.throttleEvents = data;
          this.throttleLoading = false;
        },
        error: () => {
          this.throttleError = 'Failed to load throttle events';
          this.throttleLoading = false;
        },
      });
  }

  private loadDataVolume(): void {
    this.dataVolumeLoading = true;
    this.dataVolumeError = null;
    this.api
      .getApiDataVolume(this.days)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (data) => {
          this.dataVolumePoints = data;
          this.dataVolumeLoading = false;
        },
        error: () => {
          this.dataVolumeError = 'Failed to load data volume';
          this.dataVolumeLoading = false;
        },
      });
  }

  private loadErrors(): void {
    this.errorRateLoading = true;
    this.errorRateError = null;
    this.api
      .getApiErrors(this.days)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (data) => {
          this.errorRatePoints = data;
          this.errorRateLoading = false;
        },
        error: () => {
          this.errorRateError = 'Failed to load error rate';
          this.errorRateLoading = false;
        },
      });
  }

  // --- Chart helpers ---

  get maxVolumeCount(): number {
    return Math.max(1, ...this.volumePoints.map((p) => p.count));
  }

  volumeBars(): BarSegment[] {
    const max = this.maxVolumeCount;
    return this.volumePoints.map((p, i) => ({
      label: p.bucket_start?.slice(0, 10) ?? '',
      value: p.count,
      color: CHART_COLORS[i % CHART_COLORS.length],
      pct: (p.count / max) * 100,
    }));
  }

  methodBars(): BarSegment[] {
    const max = Math.max(1, ...this.methodRows.map((r) => r.calls));
    return this.methodRows.map((r, i) => ({
      label: r.method_name,
      value: r.calls,
      color: r.throttle_count > 0 ? '#ef4444' : CHART_COLORS[i % CHART_COLORS.length],
      pct: (r.calls / max) * 100,
    }));
  }

  latencySeries(): LineSeries[] {
    if (!this.latencyPoints.length) return [];
    const xs = this.latencyPoints.map((p) => new Date(p.bucket_start).getTime());
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const rangeX = maxX - minX || 1;
    const allY = this.latencyPoints.flatMap((p) => [p.p50, p.p95]);
    const maxY = Math.max(0.001, ...allY);

    const toPoints = (key: 'p50' | 'p95'): LinePoint[] =>
      this.latencyPoints.map((p) => ({
        x: ((new Date(p.bucket_start).getTime() - minX) / rangeX) * 100,
        y: 100 - (p[key] / maxY) * 100,
        label: p.bucket_start?.slice(0, 10) ?? '',
        value: p[key],
      }));

    return [
      { label: 'P50', color: '#10b981', points: toPoints('p50') },
      { label: 'P95', color: '#ef4444', points: toPoints('p95') },
    ];
  }

  dataVolumeBars(): BarSegment[] {
    const max = Math.max(0.0001, ...this.dataVolumePoints.map((p) => p.mb));
    return this.dataVolumePoints.map((p, i) => ({
      label: p.day,
      value: p.mb,
      color: CHART_COLORS[i % CHART_COLORS.length],
      pct: (p.mb / max) * 100,
    }));
  }

  errorRateSeries(): LineSeries[] {
    if (!this.errorRatePoints.length) return [];
    const xs = this.errorRatePoints.map((p) => new Date(p.day).getTime());
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const rangeX = maxX - minX || 1;
    const maxRate = Math.max(0.001, ...this.errorRatePoints.map((p) => p.rate));

    const points: LinePoint[] = this.errorRatePoints.map((p) => ({
      x: ((new Date(p.day).getTime() - minX) / rangeX) * 100,
      y: 100 - (p.rate / maxRate) * 100,
      label: p.day,
      value: p.rate,
    }));

    return [{ label: 'Error rate', color: '#ef4444', points }];
  }

  svgPolyline(points: LinePoint[]): string {
    return points.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
  }

  get totalThrottleEvents(): number {
    return this.throttleEvents.reduce((s, e) => s + e.count, 0);
  }

  get throttlesByMethod(): { method: string; total: number }[] {
    const map = new Map<string, number>();
    for (const e of this.throttleEvents) {
      map.set(e.method_name, (map.get(e.method_name) ?? 0) + e.count);
    }
    return [...map.entries()]
      .map(([method, total]) => ({ method, total }))
      .sort((a, b) => b.total - a.total);
  }
}
