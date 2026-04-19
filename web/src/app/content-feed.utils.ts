import { MastodonMediaAttachment } from './mastodon';
import { SafeHtml } from '@angular/platform-browser';

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

export interface RawContentPost {
  id: string;
  content?: string;
  created_at: string;
  author_acct: string;
  author_display_name?: string;
  author_avatar?: string;
  counts?: Partial<ContentCounts>;
  media_attachments?: MastodonMediaAttachment[];
  is_reblog?: boolean;
  is_reply?: boolean;
  // media field used in storms response
  media?: MastodonMediaAttachment[];
}

/**
 * Precomputed view model for a feed post.
 * Computed once when data arrives; templates read fields directly.
 */
export interface FeedViewModel {
  id: string;
  created_at: string;
  safeContentHtml: SafeHtml;
  firstLinkUrl: string | null;
  allLinkUrls: string[];
  images: MastodonMediaAttachment[];
  videos: MastodonMediaAttachment[];
  originalUrl: string | null;
  isRead: boolean;
  counts?: Partial<ContentCounts>;
  is_reblog?: boolean;
  is_reply?: boolean;
  author_acct: string;
  author_display_name: string;
  author_avatar: string;
}

const IGNORED_LINK_DOMAINS = ['mastodon.social', 'appdot.net'];

function extractFirstLinkUrl(html: string): string | null {
  if (typeof DOMParser === 'undefined') return null;
  const doc = new DOMParser().parseFromString(html, 'text/html');
  const anchors = Array.from(doc.querySelectorAll('a[href]')) as HTMLAnchorElement[];
  for (const anchor of anchors) {
    if (anchor.classList.contains('hashtag') || anchor.classList.contains('mention')) continue;
    const href = anchor.getAttribute('href');
    if (!href || (!href.startsWith('http://') && !href.startsWith('https://'))) continue;
    if (IGNORED_LINK_DOMAINS.some((d) => href.includes(d))) continue;
    return href;
  }
  return null;
}

export function extractAllLinkUrls(html: string): string[] {
  if (typeof DOMParser === 'undefined') return [];
  const doc = new DOMParser().parseFromString(html, 'text/html');
  const anchors = Array.from(doc.querySelectorAll('a[href]')) as HTMLAnchorElement[];
  const seen = new Set<string>();
  const urls: string[] = [];
  for (const anchor of anchors) {
    if (anchor.classList.contains('hashtag') || anchor.classList.contains('mention')) continue;
    const href = anchor.getAttribute('href');
    if (!href || (!href.startsWith('http://') && !href.startsWith('https://'))) continue;
    if (IGNORED_LINK_DOMAINS.some((d) => href.includes(d))) continue;
    if (!seen.has(href)) {
      seen.add(href);
      urls.push(href);
    }
  }
  return urls;
}

function buildOriginalUrl(
  acct: string,
  postId: string,
  localBaseUrl?: string | null,
): string | null {
  // Always route through the active identity's home instance so the user can
  // reply/boost/fav while signed in. If we don't know the active base URL,
  // we refuse to fabricate one — callers must hide the link.
  if (!acct) return null;
  const base = localBaseUrl?.replace(/\/$/, '');
  if (!base) return null;
  const parts = acct.split('@');
  const username = parts[0];
  const remoteInstance = parts[1];
  if (remoteInstance) {
    return `${base}/@${username}@${remoteInstance}/${postId}`;
  }
  return `${base}/@${username}/${postId}`;
}

export function toFeedViewModel(
  post: RawContentPost,
  sanitize: (html: string) => SafeHtml,
  seenIds: ReadonlySet<string>,
  localBaseUrl?: string | null,
): FeedViewModel {
  const html = post.content ?? '';
  const media = post.media_attachments ?? post.media ?? [];
  return {
    id: post.id,
    created_at: post.created_at,
    safeContentHtml: sanitize(html),
    firstLinkUrl: extractFirstLinkUrl(html),
    allLinkUrls: extractAllLinkUrls(html),
    images: media.filter((m) => m.type === 'image'),
    videos: media.filter((m) => m.type === 'video' || m.type === 'gifv'),
    originalUrl: buildOriginalUrl(post.author_acct, post.id, localBaseUrl),
    isRead: seenIds.has(post.id),
    counts: post.counts,
    is_reblog: post.is_reblog,
    is_reply: post.is_reply,
    author_acct: post.author_acct,
    author_display_name: post.author_display_name || post.author_acct,
    author_avatar: post.author_avatar || '',
  };
}

export const contentFeedFilters: { value: ContentFeedFilter; label: string }[] = [
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

  const urlMatch = content.match(/https?:\/\/([^/\s"'<>]+)/i);
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
