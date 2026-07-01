import { SafeHtml } from '@angular/platform-browser';
import {
  ContentFeedPost,
  RawContentPost,
  extractAllLinkUrls,
  extractFirstDomain,
  getContentUserFilter,
  getPopularityScore,
  groupLinkPosts,
  normalizeContentPost,
  sortContentPosts,
  toFeedViewModel,
} from './content-feed.utils';

function makePost(
  id: string,
  overrides: Partial<ContentFeedPost> = {},
  counts: Partial<ContentFeedPost['counts']> = {},
): ContentFeedPost {
  return {
    id,
    content: `<p>${id}</p>`,
    created_at: '2026-01-01T00:00:00Z',
    author_acct: `${id}@example.com`,
    author_display_name: id,
    author_avatar: '',
    counts: {
      likes: 0,
      replies: 0,
      reposts: 0,
      ...counts,
    },
    ...overrides,
  };
}

describe('content feed utilities', () => {
  it('normalizes counts and author display name', () => {
    const post = normalizeContentPost({
      id: '1',
      created_at: '2026-01-01T00:00:00Z',
      author_acct: 'alice@example.com',
    });

    expect(post.author_display_name).toBe('alice@example.com');
    expect(post.counts).toEqual({ likes: 0, replies: 0, reposts: 0 });
  });

  it('sorts popular posts by engagement score before recency', () => {
    const recent = makePost(
      'recent',
      { created_at: '2026-01-03T00:00:00Z' },
      { likes: 1, replies: 0, reposts: 0 },
    );
    const popular = makePost(
      'popular',
      { created_at: '2026-01-02T00:00:00Z' },
      { likes: 3, replies: 2, reposts: 1 },
    );

    const sorted = sortContentPosts([recent, popular], 'popular');

    expect(sorted.map((post) => post.id)).toEqual(['popular', 'recent']);
    expect(getPopularityScore(popular)).toBeGreaterThan(getPopularityScore(recent));
  });

  it('sorts recent posts by created_at descending', () => {
    const older = makePost('older', { created_at: '2026-01-01T00:00:00Z' });
    const newer = makePost('newer', { created_at: '2026-01-02T00:00:00Z' });

    const sorted = sortContentPosts([older, newer], 'recent');

    expect(sorted.map((post) => post.id)).toEqual(['newer', 'older']);
  });

  it('extracts the first linked domain from HTML content', () => {
    expect(extractFirstDomain('<p>Read <a href="https://www.example.com/story">this</a></p>')).toBe(
      'example.com',
    );
  });

  it('groups links by domain and orders popular domains by combined score', () => {
    const githubLow = makePost(
      'github-low',
      {
        content: '<a href="https://github.com/org/repo">Repo</a>',
        created_at: '2026-01-01T00:00:00Z',
      },
      { likes: 1 },
    );
    const githubHigh = makePost(
      'github-high',
      {
        content: '<a href="https://github.com/org/another">Another</a>',
        created_at: '2026-01-02T00:00:00Z',
      },
      { replies: 2, reposts: 1 },
    );
    const news = makePost(
      'news',
      {
        content: '<a href="https://news.example.com/item">Story</a>',
        created_at: '2026-01-03T00:00:00Z',
      },
      { likes: 2 },
    );

    const groups = groupLinkPosts([githubLow, githubHigh, news], 'popular');

    expect(groups[0].domain).toBe('github.com');
    expect(groups[0].posts.map((post) => post.id)).toEqual(['github-high', 'github-low']);
    expect(groups[1].domain).toBe('news.example.com');
  });

  it('does not mutate the input array when sorting', () => {
    const first = makePost('first', { created_at: '2026-01-01T00:00:00Z' });
    const second = makePost('second', { created_at: '2026-01-02T00:00:00Z' });
    const input = [first, second];

    sortContentPosts(input, 'recent');

    expect(input.map((p) => p.id)).toEqual(['first', 'second']);
  });

  it('breaks popularity ties by recency', () => {
    const older = makePost('older', { created_at: '2026-01-01T00:00:00Z' }, { likes: 5 });
    const newer = makePost('newer', { created_at: '2026-01-02T00:00:00Z' }, { likes: 5 });

    const sorted = sortContentPosts([older, newer], 'popular');

    expect(sorted.map((p) => p.id)).toEqual(['newer', 'older']);
  });

  it('maps only the everyone filter to a user param', () => {
    expect(getContentUserFilter('everyone')).toBe('everyone');
    expect(getContentUserFilter('recent')).toBeUndefined();
    expect(getContentUserFilter('popular')).toBeUndefined();
    expect(getContentUserFilter('following')).toBeUndefined();
  });

  it('falls back to regex domain extraction for bare-text URLs', () => {
    expect(extractFirstDomain('check https://www.blog.example.org/post out')).toBe(
      'blog.example.org',
    );
    expect(extractFirstDomain('no links at all')).toBe('other');
  });
});

describe('extractAllLinkUrls', () => {
  it('skips hashtag and mention anchors', () => {
    const html =
      '<a class="hashtag" href="https://example.com/tags/x">#x</a>' +
      '<a class="mention" href="https://example.com/@bob">@bob</a>' +
      '<a href="https://real.example.com/article">story</a>';

    expect(extractAllLinkUrls(html)).toEqual(['https://real.example.com/article']);
  });

  it('deduplicates repeated URLs and ignores non-http schemes', () => {
    const html =
      '<a href="https://a.example.com/x">1</a>' +
      '<a href="https://a.example.com/x">again</a>' +
      '<a href="ftp://a.example.com/x">ftp</a>' +
      '<a href="javascript:alert(1)">bad</a>';

    expect(extractAllLinkUrls(html)).toEqual(['https://a.example.com/x']);
  });

  it('filters out ignored home-instance domains', () => {
    const html =
      '<a href="https://mastodon.social/@someone/123">self-link</a>' +
      '<a href="https://blog.example.com/post">real</a>';

    expect(extractAllLinkUrls(html)).toEqual(['https://blog.example.com/post']);
  });
});

describe('toFeedViewModel', () => {
  const sanitize = (html: string): SafeHtml => html as unknown as SafeHtml;

  function makeRaw(overrides: Partial<RawContentPost> = {}): RawContentPost {
    return {
      id: 'p1',
      content: '<p>hello</p>',
      created_at: '2026-01-01T00:00:00Z',
      author_acct: 'alice@remote.social',
      ...overrides,
    };
  }

  it('partitions media into images and videos (gifv counts as video)', () => {
    const vm = toFeedViewModel(
      makeRaw({
        media_attachments: [
          { id: '1', type: 'image', url: 'i.png', preview_url: '' },
          { id: '2', type: 'video', url: 'v.mp4', preview_url: '' },
          { id: '3', type: 'gifv', url: 'g.mp4', preview_url: '' },
        ],
      }),
      sanitize,
      new Set(),
      'https://home.social',
    );

    expect(vm.images.map((m) => m.id)).toEqual(['1']);
    expect(vm.videos.map((m) => m.id)).toEqual(['2', '3']);
  });

  it('falls back to the storms "media" field when media_attachments is absent', () => {
    const vm = toFeedViewModel(
      makeRaw({
        media: [{ id: '9', type: 'image', url: 'i.png', preview_url: '' }],
      }),
      sanitize,
      new Set(),
      null,
    );

    expect(vm.images.map((m) => m.id)).toEqual(['9']);
  });

  it('builds the original URL through the active identity home instance', () => {
    const vm = toFeedViewModel(makeRaw(), sanitize, new Set(), 'https://home.social/');
    expect(vm.originalUrl).toBe('https://home.social/@alice@remote.social/p1');
  });

  it('uses a local-account URL when the acct has no domain part', () => {
    const vm = toFeedViewModel(
      makeRaw({ author_acct: 'me' }),
      sanitize,
      new Set(),
      'https://home.social',
    );
    expect(vm.originalUrl).toBe('https://home.social/@me/p1');
  });

  it('refuses to fabricate an original URL without a base URL', () => {
    const vm = toFeedViewModel(makeRaw(), sanitize, new Set(), null);
    expect(vm.originalUrl).toBeNull();
  });

  it('marks posts read from the seen set and falls back for display name', () => {
    const vm = toFeedViewModel(makeRaw(), sanitize, new Set(['p1']), null);
    expect(vm.isRead).toBe(true);
    expect(vm.author_display_name).toBe('alice@remote.social');
  });
});
