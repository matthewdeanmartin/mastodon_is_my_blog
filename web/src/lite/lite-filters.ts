import { LiteFilter, LiteStatus } from './lite.models';
import { buildLiteStorms } from './lite-storms';

export function filterLiteStatuses(statuses: LiteStatus[], filter: LiteFilter): LiteStatus[] {
  if (filter === 'boosts') return statuses.filter((status) => status.reblog !== null);

  const originalPosts = statuses.filter((status) => status.reblog === null);
  if (filter === 'storms') {
    return buildLiteStorms(originalPosts).flatMap((storm) => [storm.root, ...storm.replies]);
  }

  return originalPosts.filter((status) => {
    if (filter === 'shorts') return textLength(status.content) < 500 && !hasExternalLink(status);
    if (filter === 'replies') return status.in_reply_to_id !== null;
    if (filter === 'media') return status.media_attachments.length > 0;
    return hasExternalLink(status);
  });
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
  const element = document.createElement('div');
  element.innerHTML = html;
  return (element.textContent ?? '').trim().length;
}
