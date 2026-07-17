import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  input,
  signal,
} from '@angular/core';

import {
  NOTIFICATION_TYPES,
  buildHeatmap,
  engagementSummary,
  hashtagUsage,
  mergeArchive,
  notificationTrends,
  typeMix,
} from './lite-analytics';
import { sampleAccount, sampleStatuses } from './lite-fixtures';
import { LITE_LIMITS, LiteRequestBudget } from './lite.limits';
import { LiteMastodonService } from './lite-mastodon.service';
import { LiteStorageService } from './lite-storage.service';
import { LiteNotification, LiteNotificationType, LiteStatus } from './lite.models';

const ARCHIVE_CACHE = 'analytics-archive';

/**
 * Fixed entity→color assignment for notification types (validated
 * categorical palette; the legend always shows counts as text, which is the
 * relief for the low-contrast yellow/aqua slots).
 */
export const NOTIFICATION_COLORS: Record<LiteNotificationType, string> = {
  mention: '#2a78d6',
  reblog: '#1baf7a',
  favourite: '#eda100',
  follow: '#008300',
  status: '#4a3aa7',
};

export const NOTIFICATION_TYPE_LABELS: Record<LiteNotificationType, string> = {
  mention: 'Mentions',
  reblog: 'Boosts',
  favourite: 'Favourites',
  follow: 'Follows',
  status: 'New posts',
};

/** Sequential indigo ramp, light→dark; index 0 is reserved for zero cells. */
const HEAT_RAMP = ['#eef2ff', '#c7d2fe', '#a5b4fc', '#818cf8', '#6366f1', '#4f46e5', '#3730a3'];

const DOW_LABELS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

@Component({
  selector: 'app-lite-analytics',
  imports: [CommonModule],
  templateUrl: './lite-analytics.component.html',
  styleUrl: './lite-analytics.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LiteAnalyticsComponent implements OnInit {
  private readonly storage = inject(LiteStorageService);
  private readonly mastodon = inject(LiteMastodonService);

  readonly sampleMode = input(false);

  readonly archive = signal<LiteStatus[]>([]);
  readonly notifications = signal<LiteNotification[]>([]);
  readonly loading = signal(false);
  readonly error = signal<string | null>(null);
  readonly callsUsed = signal(0);

  readonly dowLabels = DOW_LABELS;
  readonly hours = Array.from({ length: 24 }, (_unused, hour) => hour);
  readonly notificationTypes = NOTIFICATION_TYPES;
  readonly typeColors = NOTIFICATION_COLORS;
  readonly typeLabels = NOTIFICATION_TYPE_LABELS;

  readonly heatmap = computed(() => buildHeatmap(this.archive()));
  readonly heatMax = computed(() =>
    this.heatmap().reduce((max, cell) => Math.max(max, cell.count), 0),
  );
  readonly hashtags = computed(() => hashtagUsage(this.archive()));
  readonly hashtagMax = computed(() =>
    this.hashtags().reduce((max, row) => Math.max(max, row.count), 0),
  );
  readonly engagement = computed(() => engagementSummary(this.archive()));
  readonly mix = computed(() => typeMix(this.archive()));
  readonly mixTotal = computed(() => {
    const mix = this.mix();
    return mix.posts + mix.replies + mix.boosts;
  });
  readonly trendRows = computed(() => notificationTrends(this.notifications()));
  readonly trendMax = computed(() =>
    this.trendRows().reduce((max, row) => Math.max(max, row.total), 0),
  );
  readonly trendTotals = computed(() => {
    const totals = { mention: 0, favourite: 0, reblog: 0, status: 0, follow: 0 };
    for (const row of this.trendRows()) {
      for (const type of NOTIFICATION_TYPES) totals[type] += row.counts[type];
    }
    return totals;
  });
  readonly oldestDate = computed(() => {
    const archive = this.archive();
    return archive.length > 0 ? archive[archive.length - 1].created_at : null;
  });
  readonly archiveFull = computed(() => this.archive().length >= LITE_LIMITS.analyticsArchiveCap);

  async ngOnInit(): Promise<void> {
    if (this.sampleMode()) {
      this.archive.set(sampleStatuses.filter((status) => status.account.id === sampleAccount.id));
      return;
    }
    const connection = this.storage.connection();
    if (!connection) return;
    const cached = this.storage.readCache<LiteStatus[]>(connection, ARCHIVE_CACHE) ?? [];
    const own = this.storage.readCache<LiteStatus[]>(connection, 'own-statuses') ?? [];
    this.archive.set(
      mergeArchive(
        cached,
        own.filter((status) => status.account.id === connection.account.id),
        LITE_LIMITS.analyticsArchiveCap,
      ),
    );
    await this.loadFresh();
  }

  /** Extend the archive backwards by ~100 older statuses. */
  async fetchOlder(): Promise<void> {
    const connection = this.storage.connection();
    if (!connection || this.sampleMode() || this.loading()) return;
    this.loading.set(true);
    this.error.set(null);
    const budget = new LiteRequestBudget();
    try {
      let oldest = this.archive()[this.archive().length - 1]?.id ?? null;
      for (let page = 0; page < LITE_LIMITS.analyticsPagesPerFetch; page += 1) {
        const older = oldest
          ? await this.mastodon.accountStatusesBefore(
              connection,
              connection.account.id,
              oldest,
              budget,
            )
          : await this.mastodon.accountStatuses(connection, connection.account.id, budget);
        if (older.length === 0) break;
        this.archive.set(mergeArchive(this.archive(), older, LITE_LIMITS.analyticsArchiveCap));
        oldest = older[older.length - 1]?.id ?? oldest;
      }
      this.persistArchive();
    } catch (error: unknown) {
      this.error.set(error instanceof Error ? error.message : 'Could not load older posts.');
    } finally {
      this.callsUsed.set(budget.callsUsed);
      this.loading.set(false);
    }
  }

  heatColor(count: number): string {
    if (count === 0) return 'transparent';
    const max = this.heatMax();
    const level = Math.min(
      HEAT_RAMP.length - 1,
      Math.max(1, Math.ceil((count / max) * (HEAT_RAMP.length - 1))),
    );
    return HEAT_RAMP[level];
  }

  heatTitle(dow: number, hour: number, count: number): string {
    return `${DOW_LABELS[dow]} ${String(hour).padStart(2, '0')}:00 — ${count} post${count === 1 ? '' : 's'}`;
  }

  barWidth(count: number, max: number): string {
    return max > 0 ? `${Math.max(2, (count / max) * 100)}%` : '0%';
  }

  segmentHeight(count: number, max: number): string {
    if (max === 0 || count === 0) return '0px';
    return `${(count / max) * 120}px`;
  }

  postExcerpt(status: LiteStatus): string {
    const element = document.createElement('div');
    element.innerHTML = status.content;
    const text = (element.textContent ?? '').trim();
    return text.length > 120 ? `${text.slice(0, 120)}…` : text || '(media post)';
  }

  shortDate(iso: string): string {
    return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }

  private async loadFresh(): Promise<void> {
    const connection = this.storage.connection();
    if (!connection) return;
    this.loading.set(true);
    this.error.set(null);
    const budget = new LiteRequestBudget();
    try {
      // Top up the archive to ~100 recent posts, then pull two notification
      // pages for the trends chart. Both fit well inside one budget.
      if (this.archive().length < 100) {
        let oldest = this.archive()[this.archive().length - 1]?.id ?? null;
        for (let page = 0; page < LITE_LIMITS.analyticsPagesPerFetch; page += 1) {
          const fresh = oldest
            ? await this.mastodon.accountStatusesBefore(
                connection,
                connection.account.id,
                oldest,
                budget,
              )
            : await this.mastodon.accountStatuses(connection, connection.account.id, budget);
          if (fresh.length === 0) break;
          this.archive.set(mergeArchive(this.archive(), fresh, LITE_LIMITS.analyticsArchiveCap));
          oldest = fresh[fresh.length - 1]?.id ?? oldest;
        }
        this.persistArchive();
      }
      this.notifications.set(await this.mastodon.notifications(connection, budget));
    } catch (error: unknown) {
      this.error.set(error instanceof Error ? error.message : 'Could not load analytics data.');
    } finally {
      this.callsUsed.set(budget.callsUsed);
      this.loading.set(false);
    }
  }

  private persistArchive(): void {
    const connection = this.storage.connection();
    if (!connection) return;
    try {
      this.storage.writeCache(connection, ARCHIVE_CACHE, this.archive());
    } catch {
      // Storage quota — analytics still work from memory this session.
    }
  }
}
