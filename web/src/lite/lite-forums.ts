import { LiteForumFilter, LiteStatus } from './lite.models';

export const FORUM_FILTER_LABELS: Record<LiteForumFilter, string> = {
  all: 'All',
  questions: 'Questions?',
  friends_started: 'Friends started',
  popular: 'Popular',
  recent: 'Recent',
  mine: 'Mine',
  participating: 'Participating',
};

export interface LiteThread {
  /** Root status id — the anchor for the context call. */
  rootId: string;
  /** Root post when it is in the loaded window, null for a partial thread. */
  root: LiteStatus | null;
  /** Replies observed in the loaded window, oldest first. */
  replies: LiteStatus[];
  /** Highest reply count reported by the server anywhere in the thread. */
  replyCount: number;
  latestActivity: string;
  hasQuestion: boolean;
  hashtags: string[];
  rootInstance: string | null;
  engagement: number;
  participantIds: string[];
}

export interface ForumFacet {
  tag: string;
  count: number;
}

/**
 * Group the loaded window into discussion threads by root post — the lite
 * cousin of the server-side forum. Boosts contribute their target status.
 * A reply whose ancestors are not in the window still forms a (partial)
 * thread anchored at the nearest known ancestor id, so the context call can
 * fill it in on demand.
 */
export function buildLiteThreads(statuses: LiteStatus[]): LiteThread[] {
  const posts = new Map<string, LiteStatus>();
  for (const wrapper of statuses) {
    const status = wrapper.reblog ?? wrapper;
    if (!posts.has(status.id)) posts.set(status.id, status);
  }

  const rootIdOf = (status: LiteStatus): string => {
    let current = status;
    const seen = new Set<string>([current.id]);
    while (current.in_reply_to_id) {
      const parent = posts.get(current.in_reply_to_id);
      if (!parent || seen.has(parent.id)) return current.in_reply_to_id;
      seen.add(parent.id);
      current = parent;
    }
    return current.id;
  };

  const groups = new Map<string, LiteStatus[]>();
  for (const post of posts.values()) {
    const rootId = rootIdOf(post);
    const members = groups.get(rootId) ?? [];
    members.push(post);
    groups.set(rootId, members);
  }

  const threads: LiteThread[] = [];
  for (const [rootId, members] of groups) {
    const root = posts.get(rootId) ?? null;
    const replies = members
      .filter((member) => member.id !== rootId)
      .sort((left, right) => left.created_at.localeCompare(right.created_at));
    // A lone post with no observed or reported replies is a monologue, not a
    // discussion.
    const replyCount = Math.max(
      replies.length,
      ...members.map((member) => member.replies_count),
      root?.replies_count ?? 0,
    );
    if (replyCount === 0) continue;
    const anchor = root ?? replies[0];
    if (!anchor) continue;
    const participants = new Set(members.map((member) => member.account.id));
    threads.push({
      rootId,
      root,
      replies,
      replyCount,
      latestActivity: members
        .map((member) => member.created_at)
        .reduce((left, right) => (left > right ? left : right)),
      hasQuestion: root ? hasQuestionText(root) : replies.some(hasQuestionText),
      hashtags: uniqueHashtags(members),
      rootInstance: root ? instanceOf(root.account.acct) : null,
      engagement: members.reduce(
        (total, member) =>
          total + member.replies_count + member.reblogs_count + member.favourites_count,
        0,
      ),
      participantIds: [...participants],
    });
  }
  return threads.sort((left, right) => right.latestActivity.localeCompare(left.latestActivity));
}

export function filterLiteThreads(
  threads: LiteThread[],
  filter: LiteForumFilter,
  followingIds: ReadonlySet<string>,
  myAccountId: string | null,
  activeHashtags: ReadonlySet<string>,
): LiteThread[] {
  let result = threads;
  if (activeHashtags.size > 0) {
    result = result.filter((thread) =>
      thread.hashtags.some((hashtag) => activeHashtags.has(hashtag)),
    );
  }
  switch (filter) {
    case 'all':
    case 'recent':
      break;
    case 'questions':
      result = result.filter((thread) => thread.hasQuestion);
      break;
    case 'friends_started':
      result = result.filter((thread) => thread.root && followingIds.has(thread.root.account.id));
      break;
    case 'popular':
      result = [...result].sort((left, right) => right.engagement - left.engagement);
      break;
    case 'mine':
      result = result.filter((thread) => thread.root?.account.id === myAccountId);
      break;
    case 'participating':
      result = result.filter(
        (thread) => myAccountId !== null && thread.participantIds.includes(myAccountId),
      );
      break;
  }
  return result;
}

export function countLiteThreadFilters(
  threads: LiteThread[],
  followingIds: ReadonlySet<string>,
  myAccountId: string | null,
): Record<LiteForumFilter, number> {
  const counts = {} as Record<LiteForumFilter, number>;
  for (const filter of Object.keys(FORUM_FILTER_LABELS) as LiteForumFilter[]) {
    counts[filter] = filterLiteThreads(
      threads,
      filter,
      followingIds,
      myAccountId,
      new Set(),
    ).length;
  }
  return counts;
}

/** Hashtags across all threads with counts, most used first. */
export function threadHashtagFacets(threads: LiteThread[]): ForumFacet[] {
  const counts = new Map<string, number>();
  for (const thread of threads) {
    for (const hashtag of thread.hashtags) {
      counts.set(hashtag, (counts.get(hashtag) ?? 0) + 1);
    }
  }
  return [...counts.entries()]
    .map(([tag, count]) => ({ tag, count }))
    .sort((left, right) => right.count - left.count || left.tag.localeCompare(right.tag));
}

export function statusHashtags(status: LiteStatus): string[] {
  if (status.tags && status.tags.length > 0) {
    return status.tags.map((tag) => tag.name.toLowerCase());
  }
  const element = document.createElement('div');
  element.innerHTML = status.content;
  const names = new Set<string>();
  for (const anchor of element.querySelectorAll('a.hashtag, a.mention.hashtag')) {
    const text = (anchor.textContent ?? '').trim();
    if (text.startsWith('#') && text.length > 1) names.add(text.slice(1).toLowerCase());
  }
  return [...names];
}

function uniqueHashtags(members: LiteStatus[]): string[] {
  const names = new Set<string>();
  for (const member of members) {
    for (const name of statusHashtags(member)) names.add(name);
  }
  return [...names];
}

function hasQuestionText(status: LiteStatus): boolean {
  const element = document.createElement('div');
  element.innerHTML = status.content;
  return /\w+\s*\?/u.test(element.textContent ?? '');
}

function instanceOf(acct: string): string | null {
  const at = acct.indexOf('@');
  return at >= 0 ? acct.slice(at + 1) : null;
}
