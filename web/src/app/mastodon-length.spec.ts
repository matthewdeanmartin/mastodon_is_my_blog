import { mastodonLength } from './mastodon-length';

describe('mastodonLength', () => {
  it('counts plain text by character length', () => {
    expect(mastodonLength('hello world')).toBe(11);
    expect(mastodonLength('')).toBe(0);
  });

  it('counts any URL as exactly 23 characters', () => {
    const longUrl = 'https://example.com/a/very/long/path/that/keeps/going/and/going?with=query';
    expect(mastodonLength(longUrl)).toBe(23);
  });

  it('inflates short URLs up to 23 characters', () => {
    // "https://x.io" is 12 chars but Mastodon still counts 23.
    expect(mastodonLength('https://x.io')).toBe(23);
  });

  it('handles text surrounding a URL', () => {
    const text = 'look: https://example.com/some/long/path/here !';
    // "look: " (6) + 23 + " !" (2)
    expect(mastodonLength(text)).toBe(31);
  });

  it('counts multiple URLs independently', () => {
    const text =
      'https://example.com/aaaaaaaaaaaaaaaaaaaaaaaaaaa https://example.com/bbbbbbbbbbbbbbbbbbbbbbbbbbbb';
    expect(mastodonLength(text)).toBe(23 + 1 + 23);
  });
});
