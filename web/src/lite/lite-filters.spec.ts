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

  it.each([
    'posts',
    'storms',
    'shorts',
    'replies',
    'questions',
    'media',
    'links',
    'software',
    'news',
  ] as const)('never includes boosts in the %s view', (filter) => {
    const original = makeStatus('<p>A short original post.</p>');
    const boost = { ...makeStatus('<p>Wrapper</p>'), id: 'boost', reblog: original };

    expect(filterLiteStatuses([boost], filter)).toEqual([]);
  });

  it('keeps boosts available only in their explicit view', () => {
    const original = makeStatus('<p>A short original post.</p>');
    const boost = { ...makeStatus('<p>Wrapper</p>'), id: 'boost', reblog: original };

    expect(filterLiteStatuses([original, boost], 'boosts')).toEqual([boost]);
  });

  it('separates questions from replies', () => {
    const question = makeStatus('<p>What should humane software feel like?</p>');
    const reply = { ...makeStatus('<p>I think it should feel calm.</p>'), in_reply_to_id: 'root' };

    expect(filterLiteStatuses([question, reply], 'questions')).toEqual([question]);
    expect(filterLiteStatuses([question, reply], 'replies')).toEqual([reply]);
  });

  it('recognizes common software project links', () => {
    const software = makeStatus('<p><a href="https://codeberg.org/example/tool">A tool</a></p>');

    expect(filterLiteStatuses([software], 'software')).toEqual([software]);
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
