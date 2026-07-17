import { LiteNotification, LiteNotificationType, LiteStatus } from './lite.models';
import { statusHashtags } from './lite-forums';

export interface HeatmapCell {
  dow: number;
  hour: number;
  count: number;
}

export interface HashtagUsageRow {
  tag: string;
  count: number;
}

export interface EngagementSummary {
  posts: number;
  totalFavourites: number;
  totalBoosts: number;
  totalReplies: number;
  top: LiteStatus[];
}

export interface TypeMix {
  posts: number;
  replies: number;
  boosts: number;
  withMedia: number;
}

export interface NotificationDayRow {
  day: string;
  counts: Record<LiteNotificationType, number>;
  total: number;
}

export const NOTIFICATION_TYPES: readonly LiteNotificationType[] = [
  'mention',
  'favourite',
  'reblog',
  'status',
  'follow',
];

/**
 * Posting activity by local day-of-week and hour. Counts everything the
 * account authored (posts and replies); boosts are excluded because their
 * timestamp is the original author's.
 */
export function buildHeatmap(statuses: LiteStatus[]): HeatmapCell[] {
  const counts = new Map<string, number>();
  for (const status of statuses) {
    if (status.reblog) continue;
    const date = new Date(status.created_at);
    if (Number.isNaN(date.getTime())) continue;
    const key = `${date.getDay()}:${date.getHours()}`;
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  const cells: HeatmapCell[] = [];
  for (let dow = 0; dow < 7; dow += 1) {
    for (let hour = 0; hour < 24; hour += 1) {
      cells.push({ dow, hour, count: counts.get(`${dow}:${hour}`) ?? 0 });
    }
  }
  return cells;
}

export function hashtagUsage(statuses: LiteStatus[], top = 15): HashtagUsageRow[] {
  const counts = new Map<string, number>();
  for (const status of statuses) {
    if (status.reblog) continue;
    for (const tag of statusHashtags(status)) {
      counts.set(tag, (counts.get(tag) ?? 0) + 1);
    }
  }
  return [...counts.entries()]
    .map(([tag, count]) => ({ tag, count }))
    .sort((left, right) => right.count - left.count || left.tag.localeCompare(right.tag))
    .slice(0, top);
}

export function engagementSummary(statuses: LiteStatus[], top = 5): EngagementSummary {
  const own = statuses.filter((status) => !status.reblog);
  const score = (status: LiteStatus): number =>
    status.favourites_count + 2 * status.reblogs_count + status.replies_count;
  return {
    posts: own.length,
    totalFavourites: own.reduce((total, status) => total + status.favourites_count, 0),
    totalBoosts: own.reduce((total, status) => total + status.reblogs_count, 0),
    totalReplies: own.reduce((total, status) => total + status.replies_count, 0),
    top: [...own].sort((left, right) => score(right) - score(left)).slice(0, top),
  };
}

export function typeMix(statuses: LiteStatus[]): TypeMix {
  const mix: TypeMix = { posts: 0, replies: 0, boosts: 0, withMedia: 0 };
  for (const status of statuses) {
    if (status.reblog) {
      mix.boosts += 1;
      continue;
    }
    if (status.in_reply_to_id) mix.replies += 1;
    else mix.posts += 1;
    if (status.media_attachments.length > 0) mix.withMedia += 1;
  }
  return mix;
}

/** Notifications per local day and type over the last `days` days. */
export function notificationTrends(
  notifications: LiteNotification[],
  days = 14,
  now: number = Date.now(),
): NotificationDayRow[] {
  const rows = new Map<string, NotificationDayRow>();
  for (let back = days - 1; back >= 0; back -= 1) {
    const day = localDay(new Date(now - back * 86_400_000));
    rows.set(day, { day, counts: emptyCounts(), total: 0 });
  }
  for (const notification of notifications) {
    const date = new Date(notification.created_at);
    if (Number.isNaN(date.getTime())) continue;
    const row = rows.get(localDay(date));
    if (!row) continue;
    row.counts[notification.type] += 1;
    row.total += 1;
  }
  return [...rows.values()];
}

/**
 * Merge freshly fetched statuses into the persistent analytics archive:
 * dedupe by id, newest first, hard cap so localStorage stays bounded.
 */
export function mergeArchive(
  existing: LiteStatus[],
  fresh: LiteStatus[],
  cap: number,
): LiteStatus[] {
  const merged = new Map<string, LiteStatus>();
  for (const status of [...fresh, ...existing]) {
    if (!merged.has(status.id)) merged.set(status.id, status);
  }
  return [...merged.values()]
    .sort((left, right) => right.created_at.localeCompare(left.created_at))
    .slice(0, cap);
}

function emptyCounts(): Record<LiteNotificationType, number> {
  return { mention: 0, favourite: 0, reblog: 0, status: 0, follow: 0 };
}

function localDay(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${date.getFullYear()}-${month}-${day}`;
}
