export type ContentFeedFilter = 'recent' | 'popular' | 'following' | 'everyone';

export interface ContentCounts {
  likes: number;
  replies: number;
  reposts: number;
}

export interface ContentFeedPost {
  id: string;
  content: string;
  created_at: string;
  author_acct: string;
  author_display_name: string;
  author_avatar: string;
  counts: ContentCounts;
}

export interface ContentFeedGroup {
  domain: string;
  posts: ContentFeedPost[];
  latestAt: number;
  totalScore: number;
}

interface RawContentPost {
  id: string;
  content?: string;
  created_at: string;
  author_acct: string;
  author_display_name?: string;
  author_avatar?: string;
  counts?: Partial<ContentCounts>;
}

export const contentFeedFilters: Array<{ value: ContentFeedFilter; label: string }> = [
  { value: 'recent', label: 'Recent' },
  { value: 'popular', label: 'Popular' },
  { value: 'following', label: 'Following' },
  { value: 'everyone', label: 'Everyone' },
];

export function normalizeContentPost(post: RawContentPost): ContentFeedPost {
  return {
    id: post.id,
    content: post.content || '',
    created_at: post.created_at,
    author_acct: post.author_acct,
    author_display_name: post.author_display_name || post.author_acct,
    author_avatar: post.author_avatar || '',
    counts: {
      likes: post.counts?.likes ?? 0,
      replies: post.counts?.replies ?? 0,
      reposts: post.counts?.reposts ?? 0,
    },
  };
}

export function getContentUserFilter(filter: ContentFeedFilter): string | undefined {
  return filter === 'everyone' ? 'everyone' : undefined;
}

export function getPopularityScore(post: Pick<ContentFeedPost, 'counts'>): number {
  return post.counts.likes + post.counts.replies * 2 + post.counts.reposts * 3;
}

export function sortContentPosts(
  posts: ContentFeedPost[],
  filter: ContentFeedFilter,
): ContentFeedPost[] {
  return [...posts].sort((left, right) => {
    if (filter === 'popular') {
      const scoreDelta = getPopularityScore(right) - getPopularityScore(left);
      if (scoreDelta !== 0) {
        return scoreDelta;
      }
    }

    return new Date(right.created_at).getTime() - new Date(left.created_at).getTime();
  });
}

export function extractFirstDomain(content: string): string {
  if (typeof DOMParser !== 'undefined') {
    const doc = new DOMParser().parseFromString(content, 'text/html');
    const href = doc.querySelector('a[href]')?.getAttribute('href');
    if (href) {
      try {
        return new URL(href).hostname.replace(/^www\./, '');
      } catch {
        // Fall through to regex extraction below.
      }
    }
  }

  const urlMatch = content.match(/https?:\/\/([^\/\s"'<>]+)/i);
  return urlMatch?.[1]?.replace(/^www\./, '') || 'other';
}

export function groupLinkPosts(
  posts: ContentFeedPost[],
  filter: ContentFeedFilter,
): ContentFeedGroup[] {
  const groups = new Map<string, ContentFeedGroup>();

  for (const post of posts) {
    const domain = extractFirstDomain(post.content);
    const existing = groups.get(domain);
    const score = getPopularityScore(post);
    const createdAt = new Date(post.created_at).getTime();

    if (existing) {
      existing.posts.push(post);
      existing.totalScore += score;
      existing.latestAt = Math.max(existing.latestAt, createdAt);
      continue;
    }

    groups.set(domain, {
      domain,
      posts: [post],
      totalScore: score,
      latestAt: createdAt,
    });
  }

  const groupedPosts = Array.from(groups.values()).map((group) => ({
    ...group,
    posts: sortContentPosts(group.posts, filter),
  }));

  return groupedPosts.sort((left, right) => {
    if (filter === 'popular') {
      const scoreDelta = right.totalScore - left.totalScore;
      if (scoreDelta !== 0) {
        return scoreDelta;
      }

      const mentionsDelta = right.posts.length - left.posts.length;
      if (mentionsDelta !== 0) {
        return mentionsDelta;
      }
    }

    return right.latestAt - left.latestAt;
  });
}
