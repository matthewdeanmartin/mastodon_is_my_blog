import { describe, expect, it } from 'vitest';
import { normalizeInstanceUrl } from './lite-oauth.service';

describe('normalizeInstanceUrl', () => {
  it('adds HTTPS and strips a trailing slash', () => {
    expect(normalizeInstanceUrl(' mastodon.social/ ')).toBe('https://mastodon.social');
  });

  it('allows HTTPS instance URLs', () => {
    expect(normalizeInstanceUrl('https://example.social')).toBe('https://example.social');
  });

  it.each([
    'http://example.social',
    'https://user:password@example.social',
    'https://example.social/a/path',
    'https://example.social?token=nope',
    'https://example.social/#fragment',
  ])('rejects unsafe or ambiguous input: %s', (value: string) => {
    expect(() => normalizeInstanceUrl(value)).toThrow();
  });
});
