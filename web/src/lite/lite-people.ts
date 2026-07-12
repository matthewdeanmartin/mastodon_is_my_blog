import {
  LiteAccount,
  LiteNotification,
  LitePeopleFilter,
  LiteRelationship,
  LiteStatus,
} from './lite.models';

// Mirrors the server-side blog roll filters in routes/accounts.py, built from
// the handful of API pages Lite can afford instead of a full local database.
export const PEOPLE_THRESHOLDS = {
  parasocialFollowersMin: 10_000,
  livelyDays: 30,
  graveyardDays: 90,
  chattyMinReplyRatio: 0.5,
  broadcasterMaxReplyRatio: 0.2,
  broadcasterMinStatuses: 100,
  minSampledStatuses: 5,
  sampledStatusIdCap: 100,
} as const;

export const PEOPLE_FILTER_LABELS: Record<LitePeopleFilter, string> = {
  all: 'All',
  top_friends: 'Top friends',
  readers: 'Readers',
  mutuals: 'Mutuals',
  chatty: 'Chatty',
  idols: 'Idols',
  broadcasters: 'Broadcasters',
  bots: 'Bots',
  lively: 'Lively',
  graveyard: 'Graveyard',
  parasocials: 'Parasocials',
  other: 'Other',
};

export interface PersonEvidence {
  version: 1;
  accountId: string;
  acct: string;
  // Now-and-forever facts: once true they stay true across sessions, so a
  // classification survives even when a later session loads thinner data.
  everMutual: boolean;
  everMentionedMe: boolean;
  everFavouritedMe: boolean;
  everBoostedMe: boolean;
  everStatusNotified: boolean;
  iRepliedToThem: boolean;
  // Latest observations — overwritten when fresher data arrives.
  followsMe: boolean | null;
  followersCount: number;
  bot: boolean;
  lastStatusAt: string | null;
  // Reply-ratio sample used for chatty vs broadcasters. Ids are kept so a
  // re-fetched page does not double count.
  sampledStatusIds: string[];
  sampledPosts: number;
  sampledReplies: number;
  // Thin account snapshot so people we do not follow (readers) can still be
  // listed in the panel.
  snapshot: LiteAccount | null;
  updatedAt: number;
}

export type PeopleLedger = Record<string, PersonEvidence>;

export function ensureEvidence(ledger: PeopleLedger, account: LiteAccount): PersonEvidence {
  const existing = ledger[account.id];
  if (existing) return existing;
  const created: PersonEvidence = {
    version: 1,
    accountId: account.id,
    acct: account.acct,
    everMutual: false,
    everMentionedMe: false,
    everFavouritedMe: false,
    everBoostedMe: false,
    everStatusNotified: false,
    iRepliedToThem: false,
    followsMe: null,
    followersCount: account.followers_count,
    bot: account.bot ?? false,
    lastStatusAt: account.last_status_at ?? null,
    sampledStatusIds: [],
    sampledPosts: 0,
    sampledReplies: 0,
    snapshot: null,
    updatedAt: Date.now(),
  };
  ledger[account.id] = created;
  return created;
}

export function noteAccount(ledger: PeopleLedger, account: LiteAccount): void {
  const evidence = ensureEvidence(ledger, account);
  evidence.acct = account.acct;
  evidence.followersCount = account.followers_count;
  evidence.bot = account.bot ?? evidence.bot;
  if (account.last_status_at) evidence.lastStatusAt = account.last_status_at;
  evidence.updatedAt = Date.now();
}

export function noteRelationships(
  ledger: PeopleLedger,
  relationships: LiteRelationship[],
): void {
  for (const relationship of relationships) {
    const evidence = ledger[relationship.id];
    if (!evidence) continue;
    evidence.followsMe = relationship.followed_by;
    if (relationship.following && relationship.followed_by) evidence.everMutual = true;
    evidence.updatedAt = Date.now();
  }
}

export function noteNotifications(ledger: PeopleLedger, notifications: LiteNotification[]): void {
  for (const notification of notifications) {
    noteAccount(ledger, notification.account);
    const evidence = ledger[notification.account.id];
    evidence.snapshot = thinAccount(notification.account);
    if (notification.type === 'mention') evidence.everMentionedMe = true;
    if (notification.type === 'favourite') evidence.everFavouritedMe = true;
    if (notification.type === 'reblog') evidence.everBoostedMe = true;
    if (notification.type === 'status') evidence.everStatusNotified = true;
    if (notification.type === 'follow') evidence.followsMe = true;
    // A mention or status alert means they posted something at that moment.
    if (notification.type === 'mention' || notification.type === 'status') {
      if (!evidence.lastStatusAt || notification.created_at > evidence.lastStatusAt) {
        evidence.lastStatusAt = notification.created_at;
      }
    }
  }
}

/** Record which accounts I have replied to, from my own recent statuses. */
export function noteOwnStatuses(
  ledger: PeopleLedger,
  statuses: LiteStatus[],
  myAccountId: string,
): void {
  for (const status of statuses) {
    if (status.account.id !== myAccountId || status.reblog) continue;
    const target = status.in_reply_to_account_id;
    if (!target || target === myAccountId) continue;
    const evidence = ledger[target];
    if (!evidence) continue;
    evidence.iRepliedToThem = true;
    evidence.updatedAt = Date.now();
  }
}

/**
 * Sample posts seen in any loaded window (home feed, a person's page) to
 * build up a per-person reply ratio. Only people already in the ledger are
 * sampled, so strangers boosted into the feed do not grow storage.
 */
export function noteObservedStatuses(ledger: PeopleLedger, statuses: LiteStatus[]): void {
  for (const wrapper of statuses) {
    const status = wrapper.reblog ?? wrapper;
    const evidence = ledger[status.account.id];
    if (!evidence) continue;
    if (evidence.sampledStatusIds.includes(status.id)) continue;
    evidence.sampledStatusIds.push(status.id);
    if (evidence.sampledStatusIds.length > PEOPLE_THRESHOLDS.sampledStatusIdCap) {
      evidence.sampledStatusIds.shift();
    }
    if (status.in_reply_to_id) evidence.sampledReplies += 1;
    else evidence.sampledPosts += 1;
    if (!evidence.lastStatusAt || status.created_at > evidence.lastStatusAt) {
      evidence.lastStatusAt = status.created_at;
    }
    noteAccount(ledger, status.account);
  }
}

export function matchesPeopleFilter(
  filter: LitePeopleFilter,
  account: LiteAccount,
  evidence: PersonEvidence | undefined,
): boolean {
  const mutual = evidence ? evidence.everMutual || evidence.followsMe === true : false;
  const inbound = evidence
    ? evidence.everMentionedMe ||
      evidence.everFavouritedMe ||
      evidence.everBoostedMe ||
      evidence.everStatusNotified
    : false;
  const bot = account.bot ?? evidence?.bot ?? false;
  const lastStatusAt = account.last_status_at ?? evidence?.lastStatusAt ?? null;
  const followers = Math.max(account.followers_count, evidence?.followersCount ?? 0);
  const sampled = evidence ? evidence.sampledPosts + evidence.sampledReplies : 0;
  const replyRatio = sampled > 0 ? (evidence?.sampledReplies ?? 0) / sampled : 0;
  const enoughSample = sampled >= PEOPLE_THRESHOLDS.minSampledStatuses;
  const lively = withinDays(lastStatusAt, PEOPLE_THRESHOLDS.livelyDays);

  switch (filter) {
    case 'all':
      return true;
    case 'mutuals':
      return mutual;
    case 'top_friends':
      return mutual && inbound;
    case 'readers':
      return evidence?.everBoostedMe ?? false;
    case 'chatty':
      return (
        (evidence?.everMentionedMe ?? false) ||
        (enoughSample && replyRatio > PEOPLE_THRESHOLDS.chattyMinReplyRatio)
      );
    case 'broadcasters':
      return (
        enoughSample &&
        replyRatio < PEOPLE_THRESHOLDS.broadcasterMaxReplyRatio &&
        account.statuses_count > PEOPLE_THRESHOLDS.broadcasterMinStatuses
      );
    case 'idols':
      return !mutual && (evidence?.iRepliedToThem ?? false) && !inbound;
    case 'bots':
      return bot;
    case 'lively':
      return lively;
    case 'graveyard':
      return !withinDays(lastStatusAt, PEOPLE_THRESHOLDS.graveyardDays);
    case 'parasocials':
      return !mutual && followers > PEOPLE_THRESHOLDS.parasocialFollowersMin;
    case 'other':
      return !mutual && !bot && !lively && !inbound && !(evidence?.iRepliedToThem ?? false);
  }
}

/**
 * Sort parity with the server blog roll: most filters newest-post-first,
 * graveyard oldest-first with never-seen at the top, parasocials by
 * follower count descending.
 */
export function sortPeople(
  filter: LitePeopleFilter,
  people: LiteAccount[],
  ledger: PeopleLedger,
): LiteAccount[] {
  const lastStatus = (account: LiteAccount): string =>
    account.last_status_at ?? ledger[account.id]?.lastStatusAt ?? '';
  if (filter === 'parasocials') {
    return [...people].sort((a, b) => b.followers_count - a.followers_count);
  }
  if (filter === 'graveyard') {
    return [...people].sort((a, b) => lastStatus(a).localeCompare(lastStatus(b)));
  }
  return [...people].sort((a, b) => lastStatus(b).localeCompare(lastStatus(a)));
}

/**
 * Drop ledger entries for people we no longer track: not in the current
 * following list, no now-and-forever facts, and untouched for 90 days.
 * Keeps localStorage bounded as follows and notification pages churn.
 */
export function pruneLedger(
  ledger: PeopleLedger,
  keepIds: Set<string>,
  now: number = Date.now(),
): void {
  for (const [id, evidence] of Object.entries(ledger)) {
    if (keepIds.has(id)) continue;
    const sticky =
      evidence.everMutual ||
      evidence.everMentionedMe ||
      evidence.everFavouritedMe ||
      evidence.everBoostedMe ||
      evidence.everStatusNotified ||
      evidence.iRepliedToThem;
    if (sticky) continue;
    if (now - evidence.updatedAt > PEOPLE_THRESHOLDS.graveyardDays * 86_400_000) {
      delete ledger[id];
    }
  }
}

function withinDays(iso: string | null, days: number): boolean {
  if (!iso) return false;
  const timestamp = new Date(iso).getTime();
  if (Number.isNaN(timestamp)) return false;
  return Date.now() - timestamp <= days * 86_400_000;
}

function thinAccount(account: LiteAccount): LiteAccount {
  return {
    id: account.id,
    username: account.username,
    acct: account.acct,
    display_name: account.display_name,
    avatar: account.avatar,
    note: '',
    url: account.url,
    followers_count: account.followers_count,
    following_count: account.following_count,
    statuses_count: account.statuses_count,
    bot: account.bot ?? false,
    last_status_at: account.last_status_at ?? null,
  };
}
