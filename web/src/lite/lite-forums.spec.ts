import { describe, expect, it } from 'vitest';

import { sampleAccount, sampleFollowing, sampleStatuses } from './lite-fixtures';
import {
  buildLiteThreads,
  countLiteThreadFilters,
  filterLiteThreads,
  statusHashtags,
  threadHashtagFacets,
} from './lite-forums';
import { LiteAccount, LiteStatus } from './lite.models';

const me = sampleAccount;
const river = sampleFollowing[0];
const ada = sampleFollowing[1];

describe('Lite forum thread grouping', () => {
  it('groups a root and its replies into one thread', () => {
    const root = makeStatus('root', river, '<p>What is the best small web tool?</p>');
    const reply = makeReply('reply-1', ada, root.id);
    const deeper = makeReply('reply-2', me, 'reply-1');

    const threads = buildLiteThreads([root, reply, deeper]);

    expect(threads).toHaveLength(1);
    expect(threads[0].rootId).toBe('root');
    expect(threads[0].root?.id).toBe('root');
    expect(threads[0].replies.map((status) => status.id)).toEqual(['reply-1', 'reply-2']);
    expect(threads[0].hasQuestion).toBe(true);
  });

  it('excludes monologues with no observed or reported replies', () => {
    const lonely = { ...makeStatus('lonely', river, '<p>Just a post.</p>'), replies_count: 0 };

    expect(buildLiteThreads([lonely])).toEqual([]);
  });

  it('keeps a post with server-reported replies as a thread', () => {
    const discussed = { ...makeStatus('discussed', river, '<p>Hot take.</p>'), replies_count: 4 };

    const threads = buildLiteThreads([discussed]);

    expect(threads).toHaveLength(1);
    expect(threads[0].replyCount).toBe(4);
  });

  it('builds a partial thread when the root is outside the window', () => {
    const orphan = makeReply('orphan', ada, 'unseen-root');

    const threads = buildLiteThreads([orphan]);

    expect(threads).toHaveLength(1);
    expect(threads[0].rootId).toBe('unseen-root');
    expect(threads[0].root).toBeNull();
    expect(threads[0].replies.map((status) => status.id)).toEqual(['orphan']);
  });

  it('unwraps boosts so the boosted post can anchor a thread', () => {
    const original = { ...makeStatus('original', river, '<p>Debate me.</p>'), replies_count: 2 };
    const boost: LiteStatus = { ...makeStatus('boost', ada, ''), reblog: original };

    const threads = buildLiteThreads([boost]);

    expect(threads).toHaveLength(1);
    expect(threads[0].rootId).toBe('original');
  });

  it('filters by friends started, mine, and participating', () => {
    const friendRoot = makeStatus('friend-root', river, '<p>Friends thread</p>');
    const friendReply = makeReply('friend-reply', me, friendRoot.id);
    const strangerRoot = makeStatus('stranger-root', strangerAccount(), '<p>Stranger thread</p>');
    const strangerReply = makeReply('stranger-reply', ada, strangerRoot.id);
    const myRoot = makeStatus('my-root', me, '<p>My thread</p>');
    const myReply = makeReply('my-reply', river, myRoot.id);

    const threads = buildLiteThreads([
      friendRoot,
      friendReply,
      strangerRoot,
      strangerReply,
      myRoot,
      myReply,
    ]);
    const followingIds = new Set([river.id, ada.id]);

    const friends = filterLiteThreads(threads, 'friends_started', followingIds, me.id, new Set());
    expect(friends.map((thread) => thread.rootId)).toEqual(['friend-root']);

    const mine = filterLiteThreads(threads, 'mine', followingIds, me.id, new Set());
    expect(mine.map((thread) => thread.rootId)).toEqual(['my-root']);

    const participating = filterLiteThreads(
      threads,
      'participating',
      followingIds,
      me.id,
      new Set(),
    );
    expect(participating.map((thread) => thread.rootId).sort()).toEqual(['friend-root', 'my-root']);
  });

  it('sorts popular by total engagement', () => {
    const quiet = makeStatus('quiet', river, '<p>Quiet</p>');
    const quietReply = makeReply('quiet-reply', ada, quiet.id);
    const loud = {
      ...makeStatus('loud', ada, '<p>Loud</p>'),
      favourites_count: 50,
      reblogs_count: 20,
    };
    const loudReply = makeReply('loud-reply', river, loud.id);

    const threads = buildLiteThreads([quiet, quietReply, loud, loudReply]);
    const popular = filterLiteThreads(threads, 'popular', new Set(), null, new Set());

    expect(popular[0].rootId).toBe('loud');
  });

  it('collects hashtags from the tags field and filters threads by them', () => {
    const tagged = {
      ...makeStatus('tagged', river, '<p>On gardening</p>'),
      replies_count: 1,
      tags: [{ name: 'Gardening' }],
    };
    const plain = { ...makeStatus('plain', ada, '<p>No tags</p>'), replies_count: 1 };

    const threads = buildLiteThreads([tagged, plain]);
    expect(threadHashtagFacets(threads)).toEqual([{ tag: 'gardening', count: 1 }]);

    const filtered = filterLiteThreads(threads, 'all', new Set(), null, new Set(['gardening']));
    expect(filtered.map((thread) => thread.rootId)).toEqual(['tagged']);
  });

  it('parses hashtags out of content anchors when tags are absent', () => {
    const status = makeStatus(
      'anchored',
      river,
      '<p>Hello <a class="mention hashtag" href="https://x/tags/books">#Books</a></p>',
    );

    expect(statusHashtags(status)).toEqual(['books']);
  });

  it('counts threads for every forum filter', () => {
    const root = makeStatus('root', river, '<p>Any questions?</p>');
    const reply = makeReply('reply', me, root.id);

    const counts = countLiteThreadFilters(
      buildLiteThreads([root, reply]),
      new Set([river.id]),
      me.id,
    );

    expect(counts.all).toBe(1);
    expect(counts.questions).toBe(1);
    expect(counts.friends_started).toBe(1);
    expect(counts.participating).toBe(1);
    expect(counts.mine).toBe(0);
  });
});

function makeStatus(id: string, account: LiteAccount, content: string): LiteStatus {
  return {
    ...sampleStatuses[0],
    id,
    account,
    content,
    url: `${account.url}/${id}`,
    created_at: new Date(Date.now() - 3_600_000).toISOString(),
    in_reply_to_id: null,
    reblog: null,
    media_attachments: [],
    replies_count: 0,
    reblogs_count: 0,
    favourites_count: 0,
    tags: [],
  };
}

function makeReply(id: string, account: LiteAccount, parentId: string): LiteStatus {
  return { ...makeStatus(id, account, `<p>Reply ${id}</p>`), in_reply_to_id: parentId };
}

function strangerAccount(): LiteAccount {
  return { ...sampleAccount, id: 'stranger', acct: 'stranger@far.example' };
}
