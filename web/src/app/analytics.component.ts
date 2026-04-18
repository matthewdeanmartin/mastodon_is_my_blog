import { Component, OnInit, OnDestroy, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { Subject, Subscription, of } from 'rxjs';
import { catchError, debounceTime, distinctUntilChanged, switchMap, takeUntil } from 'rxjs/operators';

import { ApiService } from './api.service';
import {
  ContentSearchRow,
  HashtagTrendRow,
  HeatmapCell,
  MastodonAccount,
  NotificationTrendsResponse,
  ReposterRow,
} from './mastodon';

type Bucket = 'day' | 'week' | 'month';

const TAG_COLORS = [
  '#6366f1', '#f59e0b', '#10b981', '#ec4899', '#0ea5e9',
  '#a855f7', '#ef4444', '#14b8a6', '#eab308', '#8b5cf6',
  '#f97316', '#06b6d4', '#84cc16', '#db2777', '#22c55e',
  '#3b82f6', '#d946ef', '#f43f5e', '#0891b2', '#65a30d',
];

const DOW_LABELS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

const NOTIFICATION_TYPE_COLORS: Record<string, string> = {
  favourite: '#f59e0b',
  reblog: '#10b981',
  mention: '#6366f1',
  follow: '#ec4899',
  status: '#0ea5e9',
};

interface HashtagChartSeries {
  tag: string;
  color: string;
  total: number;
  points: { x: number; y: number; count: number; bucket: string }[];
}

interface HeatmapGridCell {
  dow: number;
  hour: number;
  count: number;
  color: string;
}

interface NotificationChartSegment {
  bucket: string;
  type: string;
  color: string;
  count: number;
  x: number;
  y: number;
  width: number;
  height: number;
}

@Component({
  selector: 'app-analytics',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './analytics.component.html',
})
export class AnalyticsComponent implements OnInit, OnDestroy {
  private api = inject(ApiService);
  private router = inject(Router);
  private readonly destroy$ = new Subject<void>();

  identityId: number | null = null;

  // Global controls
  bucket: Bucket = 'week';

  // Section A: Hashtag trends
  hashtagTop = 20;
  hashtagRows: HashtagTrendRow[] = [];
  hashtagLoading = false;
  hashtagError: string | null = null;
  hashtagSortCol: 'tag' | 'total' = 'total';
  hashtagSortDir: 'asc' | 'desc' = 'desc';

  // Section B: Content search
  searchQuery = '';
  searchLimit = 50;
  searchResults: ContentSearchRow[] = [];
  searchLoading = false;
  searchError: string | null = null;
  searchSubmitted = false;
  private readonly searchInput$ = new Subject<string>();
  private searchSub?: Subscription;

  // Section C: Posting heatmap
  heatmapAuthor = '';
  heatmapNormalize = false;
  heatmapCells: HeatmapCell[] = [];
  heatmapLoading = false;
  heatmapError: string | null = null;
  typeaheadSuggestions: MastodonAccount[] = [];
  private heatmapDebounce$ = new Subject<string>();
  private blogroll: MastodonAccount[] = [];

  // Section D: Top reposters
  repostersWindow: 7 | 30 | 90 = 30;
  repostersLimit = 20;
  repostersRows: ReposterRow[] = [];
  repostersLoading = false;
  repostersError: string | null = null;
  repostersSortCol: 'current' | 'prior' | 'delta' = 'current';
  repostersSortDir: 'asc' | 'desc' = 'desc';

  // Section E: Notification trends
  notifType = '';
  notifData: NotificationTrendsResponse | null = null;
  notifLoading = false;
  notifError: string | null = null;

  ngOnInit(): void {
    this.api.identityId$.pipe(takeUntil(this.destroy$)).subscribe((id) => {
      this.identityId = id;
      if (id !== null) {
        this.loadAll();
        this.loadBlogroll();
      }
    });

    // Debounce regex search (400 ms)
    this.searchSub = this.searchInput$
      .pipe(
        debounceTime(400),
        distinctUntilChanged(),
        switchMap((q) => {
          if (!q || !this.identityId) {
            this.searchResults = [];
            this.searchError = null;
            this.searchSubmitted = false;
            this.searchLoading = false;
            return of<ContentSearchRow[] | null>(null);
          }
          this.searchLoading = true;
          this.searchError = null;
          this.searchSubmitted = true;
          return this.api.searchContent(this.identityId, q, this.searchLimit).pipe(
            catchError((err: unknown) => {
              this.searchLoading = false;
              const detail =
                (err as { error?: { detail?: string } })?.error?.detail ?? 'Search failed';
              this.searchError = detail;
              return of<ContentSearchRow[] | null>(null);
            }),
          );
        }),
        takeUntil(this.destroy$),
      )
      .subscribe((rows) => {
        this.searchLoading = false;
        if (rows) this.searchResults = rows;
      });

    // Debounce heatmap author typeahead
    this.heatmapDebounce$
      .pipe(debounceTime(250), distinctUntilChanged(), takeUntil(this.destroy$))
      .subscribe((acct) => {
        this.updateTypeaheadSuggestions(acct);
        this.loadHeatmap();
      });
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
    this.searchSub?.unsubscribe();
  }

  private loadBlogroll(): void {
    if (!this.identityId) return;
    this.api.getBlogRoll(this.identityId, 'all').subscribe({
      next: (accts) => (this.blogroll = accts),
      error: () => (this.blogroll = []),
    });
  }

  private loadAll(): void {
    this.loadHashtags();
    this.loadReposters();
    this.loadHeatmap();
    this.loadNotifications();
    // Section B: do not auto-fire — it's user-typed
  }

  // --- Section A: Hashtag trends ---

  loadHashtags(): void {
    if (!this.identityId) return;
    this.hashtagLoading = true;
    this.hashtagError = null;
    this.api.getHashtagTrends(this.identityId, this.bucket, this.hashtagTop).subscribe({
      next: (rows) => {
        this.hashtagRows = rows;
        this.hashtagLoading = false;
      },
      error: (err: unknown) => {
        this.hashtagLoading = false;
        this.hashtagError =
          (err as { error?: { detail?: string } })?.error?.detail ?? 'Failed to load hashtag trends';
      },
    });
  }

  onBucketChange(): void {
    this.loadHashtags();
    this.loadNotifications();
  }

  onHashtagTopChange(): void {
    if (this.hashtagTop < 1) this.hashtagTop = 1;
    if (this.hashtagTop > 50) this.hashtagTop = 50;
    this.loadHashtags();
  }

  get hashtagBuckets(): string[] {
    const set = new Set<string>();
    for (const r of this.hashtagRows) set.add(r.bucket_start);
    return [...set].sort();
  }

  get hashtagSeries(): HashtagChartSeries[] {
    const buckets = this.hashtagBuckets;
    const byTag = new Map<string, Map<string, number>>();
    for (const r of this.hashtagRows) {
      if (!byTag.has(r.tag)) byTag.set(r.tag, new Map());
      byTag.get(r.tag)!.set(r.bucket_start, r.count);
    }
    const tags = [...byTag.keys()];
    const maxCount = this.hashtagMaxStacked;

    const width = 600;
    const height = 220;
    const padLeft = 40;
    const padRight = 16;
    const padTop = 12;
    const padBottom = 32;
    const plotW = width - padLeft - padRight;
    const plotH = height - padTop - padBottom;

    // Assign colors by descending total
    const sorted = tags
      .map((tag) => ({
        tag,
        total: [...byTag.get(tag)!.values()].reduce((a, b) => a + b, 0),
      }))
      .sort((a, b) => b.total - a.total);

    return sorted.map((entry, idx) => {
      const map = byTag.get(entry.tag)!;
      const points = buckets.map((b, i) => {
        const count = map.get(b) ?? 0;
        const x =
          buckets.length > 1
            ? padLeft + (i * plotW) / (buckets.length - 1)
            : padLeft + plotW / 2;
        const y = maxCount > 0 ? padTop + plotH - (count / maxCount) * plotH : padTop + plotH;
        return { x, y, count, bucket: b };
      });
      return {
        tag: entry.tag,
        color: TAG_COLORS[idx % TAG_COLORS.length],
        total: entry.total,
        points,
      };
    });
  }

  get hashtagMaxStacked(): number {
    const perBucket = new Map<string, number>();
    for (const r of this.hashtagRows) {
      perBucket.set(r.bucket_start, (perBucket.get(r.bucket_start) ?? 0) + r.count);
    }
    let max = 0;
    for (const v of perBucket.values()) if (v > max) max = v;
    return max || 1;
  }

  get hashtagAxisLabels(): { x: number; label: string }[] {
    const buckets = this.hashtagBuckets;
    if (buckets.length === 0) return [];
    const padLeft = 40;
    const plotW = 600 - padLeft - 16;
    const maxLabels = 6;
    const step = Math.max(1, Math.ceil(buckets.length / maxLabels));
    const out: { x: number; label: string }[] = [];
    for (let i = 0; i < buckets.length; i += step) {
      const x =
        buckets.length > 1 ? padLeft + (i * plotW) / (buckets.length - 1) : padLeft + plotW / 2;
      out.push({ x, label: buckets[i].slice(0, 10) });
    }
    return out;
  }

  hashtagLinePath(s: HashtagChartSeries): string {
    if (s.points.length === 0) return '';
    return s.points
      .map((p, i) => (i === 0 ? `M ${p.x} ${p.y}` : `L ${p.x} ${p.y}`))
      .join(' ');
  }

  hashtagTableRows(): { tag: string; total: number; color: string }[] {
    const series = this.hashtagSeries.map((s) => ({ tag: s.tag, total: s.total, color: s.color }));
    return series.sort((a, b) => {
      const dir = this.hashtagSortDir === 'asc' ? 1 : -1;
      if (this.hashtagSortCol === 'tag') return a.tag.localeCompare(b.tag) * dir;
      return (a.total - b.total) * dir;
    });
  }

  sortHashtags(col: 'tag' | 'total'): void {
    if (this.hashtagSortCol === col) {
      this.hashtagSortDir = this.hashtagSortDir === 'asc' ? 'desc' : 'asc';
    } else {
      this.hashtagSortCol = col;
      this.hashtagSortDir = col === 'tag' ? 'asc' : 'desc';
    }
  }

  // --- Section B: Content search ---

  onSearchInput(value: string): void {
    this.searchQuery = value;
    if (!value.trim()) {
      this.searchResults = [];
      this.searchError = null;
      this.searchSubmitted = false;
      return;
    }
    this.searchInput$.next(value.trim());
  }

  submitSearch(): void {
    if (!this.searchQuery.trim()) return;
    this.searchInput$.next(this.searchQuery.trim());
  }

  relativeTime(iso: string): string {
    const then = new Date(iso).getTime();
    if (Number.isNaN(then)) return iso;
    const diffMs = Date.now() - then;
    const sec = Math.floor(diffMs / 1000);
    if (sec < 60) return `${sec}s ago`;
    const min = Math.floor(sec / 60);
    if (min < 60) return `${min}m ago`;
    const hr = Math.floor(min / 60);
    if (hr < 24) return `${hr}h ago`;
    const d = Math.floor(hr / 24);
    if (d < 30) return `${d}d ago`;
    const mo = Math.floor(d / 30);
    if (mo < 12) return `${mo}mo ago`;
    return `${Math.floor(mo / 12)}y ago`;
  }

  // --- Section C: Posting heatmap ---

  onHeatmapAuthorInput(value: string): void {
    this.heatmapAuthor = value;
    this.heatmapDebounce$.next(value);
  }

  pickTypeahead(acct: string): void {
    this.heatmapAuthor = acct;
    this.typeaheadSuggestions = [];
    this.loadHeatmap();
  }

  loadHeatmap(): void {
    if (!this.identityId) return;
    this.heatmapLoading = true;
    this.heatmapError = null;
    const author = this.heatmapAuthor.trim() || undefined;
    this.api.getPostingHeatmap(this.identityId, author).subscribe({
      next: (cells) => {
        this.heatmapCells = cells;
        this.heatmapLoading = false;
      },
      error: (err: unknown) => {
        this.heatmapLoading = false;
        this.heatmapError =
          (err as { error?: { detail?: string } })?.error?.detail ?? 'Failed to load heatmap';
      },
    });
  }

  private updateTypeaheadSuggestions(q: string): void {
    const trimmed = q.trim().toLowerCase();
    if (!trimmed) {
      this.typeaheadSuggestions = [];
      return;
    }
    this.typeaheadSuggestions = this.blogroll
      .filter(
        (a) =>
          a.acct.toLowerCase().includes(trimmed) ||
          (a.display_name ?? '').toLowerCase().includes(trimmed),
      )
      .slice(0, 8);
  }

  get heatmapMax(): number {
    let max = 0;
    for (const c of this.heatmapCells) if (c.count > max) max = c.count;
    return max;
  }

  get heatmapGrid(): HeatmapGridCell[][] {
    const map = new Map<string, number>();
    for (const c of this.heatmapCells) map.set(`${c.dow}:${c.hour}`, c.count);
    const max = this.heatmapMax;
    const grid: HeatmapGridCell[][] = [];
    for (let dow = 0; dow < 7; dow++) {
      const row: HeatmapGridCell[] = [];
      for (let hour = 0; hour < 24; hour++) {
        const count = map.get(`${dow}:${hour}`) ?? 0;
        row.push({ dow, hour, count, color: this.heatmapColor(count, max) });
      }
      grid.push(row);
    }
    return grid;
  }

  private heatmapColor(count: number, max: number): string {
    const base = '#f1f5f9';
    if (count === 0 || max === 0) return base;
    // log scale so single-author views have contrast
    const t = this.heatmapNormalize
      ? Math.log1p(count) / Math.log1p(max)
      : Math.log1p(count) / Math.log1p(Math.max(max, 10));
    return this.lerpColor('#e0e7ff', '#6366f1', Math.min(1, Math.max(0.08, t)));
  }

  private lerpColor(a: string, b: string, t: number): string {
    const ax = parseInt(a.slice(1), 16);
    const bx = parseInt(b.slice(1), 16);
    const ar = (ax >> 16) & 255;
    const ag = (ax >> 8) & 255;
    const ab = ax & 255;
    const br = (bx >> 16) & 255;
    const bg = (bx >> 8) & 255;
    const bb = bx & 255;
    const r = Math.round(ar + (br - ar) * t);
    const g = Math.round(ag + (bg - ag) * t);
    const bl = Math.round(ab + (bb - ab) * t);
    return `rgb(${r},${g},${bl})`;
  }

  dowLabel(dow: number): string {
    return DOW_LABELS[dow] ?? '';
  }

  hourLabel(hour: number): string {
    return hour.toString().padStart(2, '0');
  }

  heatmapAriaLabel(cell: HeatmapGridCell): string {
    const fullDow = [
      'Sunday',
      'Monday',
      'Tuesday',
      'Wednesday',
      'Thursday',
      'Friday',
      'Saturday',
    ][cell.dow];
    const h = cell.hour % 12 === 0 ? 12 : cell.hour % 12;
    const ampm = cell.hour < 12 ? 'AM' : 'PM';
    return `${fullDow}, ${h} ${ampm}, ${cell.count} posts`;
  }

  // --- Section D: Top reposters ---

  loadReposters(): void {
    if (!this.identityId) return;
    this.repostersLoading = true;
    this.repostersError = null;
    this.api
      .getTopReposters(this.identityId, this.repostersWindow, this.repostersLimit)
      .subscribe({
        next: (rows) => {
          this.repostersRows = rows;
          this.repostersLoading = false;
        },
        error: (err: unknown) => {
          this.repostersLoading = false;
          this.repostersError =
            (err as { error?: { detail?: string } })?.error?.detail ??
            'Failed to load top reposters';
        },
      });
  }

  onRepostersWindowChange(): void {
    this.loadReposters();
  }

  onRepostersLimitChange(): void {
    if (this.repostersLimit < 1) this.repostersLimit = 1;
    if (this.repostersLimit > 100) this.repostersLimit = 100;
    this.loadReposters();
  }

  get repostersSorted(): ReposterRow[] {
    const dir = this.repostersSortDir === 'asc' ? 1 : -1;
    const col = this.repostersSortCol;
    return [...this.repostersRows].sort((a, b) => (a[col] - b[col]) * dir);
  }

  sortReposters(col: 'current' | 'prior' | 'delta'): void {
    if (this.repostersSortCol === col) {
      this.repostersSortDir = this.repostersSortDir === 'asc' ? 'desc' : 'asc';
    } else {
      this.repostersSortCol = col;
      this.repostersSortDir = 'desc';
    }
  }

  deltaSymbol(d: number): string {
    if (d > 0) return '▲';
    if (d < 0) return '▼';
    return '·';
  }

  deltaClass(d: number): string {
    if (d > 0) return 'delta-up';
    if (d < 0) return 'delta-down';
    return 'delta-flat';
  }

  openReposter(acct: string): void {
    this.router.navigate(['/'], { queryParams: { user: acct, filter: 'storms' } });
  }

  openActor(acct: string): void {
    this.router.navigate(['/'], { queryParams: { user: acct } });
  }

  // --- Section E: Notification trends ---

  loadNotifications(): void {
    if (!this.identityId) return;
    this.notifLoading = true;
    this.notifError = null;
    const type = this.notifType || undefined;
    this.api.getNotificationTrends(this.identityId, type, this.bucket).subscribe({
      next: (data) => {
        this.notifData = data;
        this.notifLoading = false;
      },
      error: (err: unknown) => {
        this.notifLoading = false;
        this.notifError =
          (err as { error?: { detail?: string } })?.error?.detail ??
          'Failed to load notification trends';
      },
    });
  }

  onNotifTypeChange(): void {
    this.loadNotifications();
  }

  get notifBuckets(): string[] {
    if (!this.notifData) return [];
    const set = new Set<string>();
    for (const r of this.notifData.by_type) set.add(r.bucket_start);
    return [...set].sort();
  }

  get notifTypes(): string[] {
    if (!this.notifData) return [];
    const set = new Set<string>();
    for (const r of this.notifData.by_type) set.add(r.type);
    return [...set].sort();
  }

  get notifMaxStack(): number {
    if (!this.notifData) return 1;
    const perBucket = new Map<string, number>();
    for (const r of this.notifData.by_type) {
      perBucket.set(r.bucket_start, (perBucket.get(r.bucket_start) ?? 0) + r.count);
    }
    let max = 0;
    for (const v of perBucket.values()) if (v > max) max = v;
    return max || 1;
  }

  get notifSegments(): NotificationChartSegment[] {
    if (!this.notifData) return [];
    const buckets = this.notifBuckets;
    const types = this.notifTypes;
    const width = 560;
    const height = 220;
    const padLeft = 40;
    const padRight = 16;
    const padTop = 12;
    const padBottom = 32;
    const plotW = width - padLeft - padRight;
    const plotH = height - padTop - padBottom;
    const barW = buckets.length > 0 ? Math.max(6, (plotW / buckets.length) * 0.75) : 0;
    const max = this.notifMaxStack;

    const byBucket = new Map<string, Map<string, number>>();
    for (const r of this.notifData.by_type) {
      if (!byBucket.has(r.bucket_start)) byBucket.set(r.bucket_start, new Map());
      byBucket.get(r.bucket_start)!.set(r.type, r.count);
    }

    const segments: NotificationChartSegment[] = [];
    buckets.forEach((b, i) => {
      const center =
        buckets.length > 1
          ? padLeft + (i * plotW) / (buckets.length - 1)
          : padLeft + plotW / 2;
      const x = center - barW / 2;
      let stackY = padTop + plotH;
      for (const t of types) {
        const count = byBucket.get(b)?.get(t) ?? 0;
        if (count === 0) continue;
        const h = (count / max) * plotH;
        stackY -= h;
        segments.push({
          bucket: b,
          type: t,
          color: NOTIFICATION_TYPE_COLORS[t] ?? '#94a3b8',
          count,
          x,
          y: stackY,
          width: barW,
          height: h,
        });
      }
    });
    return segments;
  }

  get notifAxisLabels(): { x: number; label: string }[] {
    const buckets = this.notifBuckets;
    if (buckets.length === 0) return [];
    const padLeft = 40;
    const plotW = 560 - padLeft - 16;
    const maxLabels = 6;
    const step = Math.max(1, Math.ceil(buckets.length / maxLabels));
    const out: { x: number; label: string }[] = [];
    for (let i = 0; i < buckets.length; i += step) {
      const x =
        buckets.length > 1 ? padLeft + (i * plotW) / (buckets.length - 1) : padLeft + plotW / 2;
      out.push({ x, label: buckets[i].slice(0, 10) });
    }
    return out;
  }

  notifColor(type: string): string {
    return NOTIFICATION_TYPE_COLORS[type] ?? '#94a3b8';
  }

  trackByIndex(i: number): number {
    return i;
  }

  trackByAcct(_i: number, row: { account_acct: string }): string {
    return row.account_acct;
  }

  trackByPostId(_i: number, row: ContentSearchRow): string {
    return row.id;
  }

  trackByTag(_i: number, s: { tag: string }): string {
    return s.tag;
  }

  trackByBucket(_i: number, b: string): string {
    return b;
  }
}
