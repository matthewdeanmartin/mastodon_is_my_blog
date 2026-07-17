import { describe, expect, it } from 'vitest';

import {
  buildHeatmap,
  engagementSummary,
  hashtagUsage,
  mergeArchive,
  notificationTrends,
  typeMix,
} from './lite-analytics';
import { sampleAccount, sampleStatuses } from './lite-fixtures';
import { LiteNotification, LiteStatus } from './lite.models';

describe('Lite analytics aggregations', () => {
  it('buckets posts into the day-of-week × hour heatmap', () => {
    const when = new Date(2026, 6, 15, 9, 30); // A Wednesday morning, local time.
    const status = { ...makeStatus('heat'), created_at: when.toISOString() };

    const cells = buildHeatmap([status]);
    const hot = cells.filter((cell) => cell.count > 0);

    expect(cells).toHaveLength(7 * 24);
    expect(hot).toEqual([{ dow: 3, hour: 9, count: 1 }]);
  });

  it('excludes boosts from the heatmap', () => {
    const boost = { ...makeStatus('boost'), reblog: makeStatus('original') };

    expect(buildHeatmap([boost]).every((cell) => cell.count === 0)).toBe(true);
  });

  it('tallies hashtag usage most-used first', () => {
    const one = { ...makeStatus('one'), tags: [{ name: 'zebra' }] };
    const two = { ...makeStatus('two'), tags: [{ name: 'apple' }] };
    const three = { ...makeStatus('three'), tags: [{ name: 'apple' }] };

    expect(hashtagUsage([one, two, three])).toEqual([
      { tag: 'apple', count: 2 },
      { tag: 'zebra', count: 1 },
    ]);
  });

  it('summarizes engagement and ranks top posts', () => {
    const modest = { ...makeStatus('modest'), favourites_count: 1 };
    const hit = { ...makeStatus('hit'), favourites_count: 10, reblogs_count: 5, replies_count: 3 };

    const summary = engagementSummary([modest, hit]);

    expect(summary.posts).toBe(2);
    expect(summary.totalFavourites).toBe(11);
    expect(summary.totalBoosts).toBe(5);
    expect(summary.totalReplies).toBe(3);
    expect(summary.top[0].id).toBe('hit');
  });

  it('splits the type mix into posts, replies, and boosts', () => {
    const post = makeStatus('post');
    const reply = { ...makeStatus('reply'), in_reply_to_id: 'root' };
    const boost = { ...makeStatus('boost'), reblog: makeStatus('original') };

    expect(typeMix([post, reply, boost])).toEqual({
      posts: 1,
      replies: 1,
      boosts: 1,
      withMedia: 0,
    });
  });

  it('buckets notifications per local day over the window', () => {
    const now = new Date(2026, 6, 15, 12, 0).getTime();
    const today: LiteNotification = {
      id: 'n1',
      type: 'favourite',
      created_at: new Date(2026, 6, 15, 8, 0).toISOString(),
      account: sampleAccount,
    };
    const lastWeek: LiteNotification = {
      id: 'n2',
      type: 'mention',
      created_at: new Date(2026, 6, 10, 8, 0).toISOString(),
      account: sampleAccount,
    };
    const tooOld: LiteNotification = {
      id: 'n3',
      type: 'follow',
      created_at: new Date(2026, 5, 1, 8, 0).toISOString(),
      account: sampleAccount,
    };

    const rows = notificationTrends([today, lastWeek, tooOld], 14, now);

    expect(rows).toHaveLength(14);
    expect(rows[rows.length - 1].counts.favourite).toBe(1);
    expect(rows.find((row) => row.day === '2026-07-10')?.counts.mention).toBe(1);
    expect(rows.reduce((total, row) => total + row.total, 0)).toBe(2);
  });

  it('merges archives newest first, deduped, and capped', () => {
    const older = { ...makeStatus('older'), created_at: '2026-01-01T00:00:00.000Z' };
    const newer = { ...makeStatus('newer'), created_at: '2026-02-01T00:00:00.000Z' };
    const duplicate = { ...newer, favourites_count: 99 };

    const merged = mergeArchive([older, newer], [duplicate], 10);
    expect(merged.map((status) => status.id)).toEqual(['newer', 'older']);
    expect(merged[0].favourites_count).toBe(99);

    expect(mergeArchive([older, newer], [], 1)).toHaveLength(1);
  });
});

function makeStatus(id: string): LiteStatus {
  return {
    ...sampleStatuses[0],
    id,
    account: sampleAccount,
    url: `${sampleAccount.url}/${id}`,
    in_reply_to_id: null,
    reblog: null,
    media_attachments: [],
    replies_count: 0,
    reblogs_count: 0,
    favourites_count: 0,
    tags: [],
  };
}
