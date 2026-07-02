import { describe, expect, it } from 'vitest';

import { sampleAccount, sampleFollowing, sampleStatuses } from './lite-fixtures';
import { LiteStatus } from './lite.models';
import { buildLiteStorms } from './lite-storms';

describe('buildLiteStorms', () => {
  it('requires a top-level post followed by a same-author reply', () => {
    const root = { ...sampleStatuses[0], account: sampleAccount, in_reply_to_id: null };
    const selfReply = {
      ...sampleStatuses[1],
      id: 'self-reply',
      account: sampleAccount,
      in_reply_to_id: root.id,
    };
    const outsiderReply = {
      ...sampleStatuses[2],
      id: 'outsider-reply',
      account: sampleFollowing[0],
      in_reply_to_id: root.id,
    };
    const replyToOther = {
      ...sampleStatuses[3],
      id: 'reply-to-other',
      account: sampleAccount,
      in_reply_to_id: 'missing-other-root',
    };

    expect(buildLiteStorms([root, outsiderReply, selfReply, replyToOther])).toEqual([
      { root, replies: [selfReply] },
    ]);
  });

  it('keeps a chained self-reply branch in chronological order', () => {
    const root = { ...sampleStatuses[0], account: sampleAccount, in_reply_to_id: null };
    const first: LiteStatus = {
      ...sampleStatuses[1],
      id: 'first',
      account: sampleAccount,
      created_at: '2026-01-01T01:00:00Z',
      in_reply_to_id: root.id,
    };
    const second: LiteStatus = {
      ...sampleStatuses[2],
      id: 'second',
      account: sampleAccount,
      created_at: '2026-01-01T02:00:00Z',
      in_reply_to_id: first.id,
    };

    expect(buildLiteStorms([second, root, first])[0].replies).toEqual([first, second]);
  });
});
