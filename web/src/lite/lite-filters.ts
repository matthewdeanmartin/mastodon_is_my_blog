import { LiteFilter, LiteStatus } from './lite.models';
import { buildLiteStorms } from './lite-storms';

export function filterLiteStatuses(statuses: LiteStatus[], filter: LiteFilter): LiteStatus[] {
  if (filter === 'boosts') return statuses.filter((status) => status.reblog !== null);

  const originalPosts = statuses.filter((status) => status.reblog === null);
  if (filter === 'posts') return originalPosts;
  if (filter === 'storms') {
    return buildLiteStorms(originalPosts).flatMap((storm) => [storm.root, ...storm.replies]);
  }

  return originalPosts.filter((status) => {
    if (filter === 'shorts')
      return (
        status.in_reply_to_id === null &&
        textLength(status.content) < 500 &&
        !hasExternalLink(status)
      );
    if (filter === 'replies') return status.in_reply_to_id !== null;
    if (filter === 'questions')
      return status.in_reply_to_id === null && /\w+\?/u.test(text(status.content));
    if (filter === 'media') return status.media_attachments.length > 0;
    if (filter === 'software') return hasDomain(status, SOFTWARE_DOMAINS);
    if (filter === 'news') return hasDomain(status, NEWS_DOMAINS);
    return hasExternalLink(status);
  });
}

const ALL_LITE_FILTERS: readonly LiteFilter[] = [
  'posts',
  'storms',
  'shorts',
  'replies',
  'questions',
  'media',
  'links',
  'software',
  'news',
  'boosts',
];

/**
 * Count matches for every filter over the loaded window so the View buttons
 * can show badges and gray out empty filters. Storms counts distinct storms,
 * not their member statuses.
 */
export function countLiteFilters(statuses: LiteStatus[]): Record<LiteFilter, number> {
  const counts = {} as Record<LiteFilter, number>;
  for (const filter of ALL_LITE_FILTERS) {
    counts[filter] =
      filter === 'storms'
        ? buildLiteStorms(statuses.filter((status) => status.reblog === null)).length
        : filterLiteStatuses(statuses, filter).length;
  }
  return counts;
}

export function hasExternalLink(status: LiteStatus): boolean {
  const element = document.createElement('div');
  element.innerHTML = status.content;
  return Array.from(element.querySelectorAll<HTMLAnchorElement>('a[href]')).some((anchor) => {
    if (anchor.classList.contains('mention') || anchor.classList.contains('hashtag')) return false;
    return anchor.href !== status.url;
  });
}

function textLength(html: string): number {
  return text(html).length;
}

function text(html: string): string {
  const element = document.createElement('div');
  element.innerHTML = html;
  return (element.textContent ?? '').trim();
}

function hasDomain(status: LiteStatus, domains: readonly string[]): boolean {
  const element = document.createElement('div');
  element.innerHTML = status.content;
  return Array.from(element.querySelectorAll<HTMLAnchorElement>('a[href]')).some((anchor) =>
    domains.some((domain) => anchor.hostname === domain || anchor.hostname.endsWith(`.${domain}`)),
  );
}

const SOFTWARE_DOMAINS = ['github.com', 'gitlab.com', 'codeberg.org', 'pypi.org', 'npmjs.com'];
const NEWS_DOMAINS = [
  'apnews.com',
  'bbc.com',
  'bbc.co.uk',
  'npr.org',
  'reuters.com',
  'theguardian.com',
];
