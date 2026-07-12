import { describe, expect, it } from 'vitest';

import { sampleAccount, sampleStatuses } from './lite-fixtures';
import { filterLiteStatuses, hasExternalLink } from './lite-filters';
import { LiteStatus } from './lite.models';

describe('Lite content filters', () => {
  it('does not treat mentions or hashtags as links', () => {
    const status = makeStatus(
      '<p><a class="u-url mention" href="https://example.social/@ada">@ada</a> ' +
        '<a class="mention hashtag" href="https://example.social/tags/books">#books</a></p>',
    );

    expect(hasExternalLink(status)).toBe(false);
  });

  it('recognizes a link to a web page', () => {
    const status = makeStatus('<p>Read <a href="https://example.com/essay">the essay</a>.</p>');

    expect(hasExternalLink(status)).toBe(true);
  });

  it.each(['storms', 'shorts', 'replies', 'media', 'links'] as const)(
    'never includes boosts in the %s view',
    (filter) => {
      const original = makeStatus('<p>A short original post.</p>');
      const boost = { ...makeStatus('<p>Wrapper</p>'), id: 'boost', reblog: original };

      expect(filterLiteStatuses([boost], filter)).toEqual([]);
    },
  );

  it('keeps boosts available only in their explicit view', () => {
    const original = makeStatus('<p>A short original post.</p>');
    const boost = { ...makeStatus('<p>Wrapper</p>'), id: 'boost', reblog: original };

    expect(filterLiteStatuses([original, boost], 'boosts')).toEqual([boost]);
  });
});

function makeStatus(content: string): LiteStatus {
  return {
    ...sampleStatuses[0],
    id: 'test-status',
    account: sampleAccount,
    content,
    url: 'https://example.social/@writer/test-status',
    in_reply_to_id: null,
    reblog: null,
    media_attachments: [],
  };
}
