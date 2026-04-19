import {
  ContentFeedPost,
  extractFirstDomain,
  getPopularityScore,
  groupLinkPosts,
  normalizeContentPost,
  sortContentPosts,
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
});
