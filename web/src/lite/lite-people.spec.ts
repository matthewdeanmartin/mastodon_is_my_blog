import { describe, expect, it } from 'vitest';

import {
  PEOPLE_THRESHOLDS,
  PeopleLedger,
  ensureEvidence,
  matchesPeopleFilter,
  noteAccount,
  noteNotifications,
  noteObservedStatuses,
  noteOwnStatuses,
  noteRelationships,
  pruneLedger,
  sortPeople,
} from './lite-people';
import { LiteAccount, LiteNotification, LiteStatus } from './lite.models';

function makeAccount(id: string, overrides: Partial<LiteAccount> = {}): LiteAccount {
  return {
    id,
    username: id,
    acct: `${id}@social.example`,
    display_name: id,
    avatar: '',
    note: '',
    url: `https://social.example/@${id}`,
    followers_count: 100,
    following_count: 100,
    statuses_count: 500,
    bot: false,
    last_status_at: new Date().toISOString(),
    ...overrides,
  };
}

function makeStatus(
  id: string,
  account: LiteAccount,
  overrides: Partial<LiteStatus> = {},
): LiteStatus {
  return {
    id,
    content: '<p>hello</p>',
    spoiler_text: '',
    created_at: new Date().toISOString(),
    url: null,
    visibility: 'public',
    in_reply_to_id: null,
    account,
    reblog: null,
    media_attachments: [],
    replies_count: 0,
    reblogs_count: 0,
    favourites_count: 0,
    ...overrides,
  };
}

function makeNotification(
  id: string,
  type: LiteNotification['type'],
  account: LiteAccount,
): LiteNotification {
  return { id, type, created_at: new Date().toISOString(), account };
}

describe('blog roll evidence ledger', () => {
  it('marks mutuals from relationships and keeps mutual forever', () => {
    const ledger: PeopleLedger = {};
    const friend = makeAccount('friend');
    noteAccount(ledger, friend);
    noteRelationships(ledger, [{ id: 'friend', following: true, followed_by: true }]);

    expect(matchesPeopleFilter('mutuals', friend, ledger['friend'])).toBe(true);

    // A later observation says they unfollowed — the sticky fact still wins.
    noteRelationships(ledger, [{ id: 'friend', following: true, followed_by: false }]);
    expect(ledger['friend'].followsMe).toBe(false);
    expect(matchesPeopleFilter('mutuals', friend, ledger['friend'])).toBe(true);
  });

  it('classifies a mutual who interacts as a top friend', () => {
    const ledger: PeopleLedger = {};
    const friend = makeAccount('friend');
    noteAccount(ledger, friend);
    noteRelationships(ledger, [{ id: 'friend', following: true, followed_by: true }]);
    expect(matchesPeopleFilter('top_friends', friend, ledger['friend'])).toBe(false);

    noteNotifications(ledger, [makeNotification('n1', 'favourite', friend)]);
    expect(matchesPeopleFilter('top_friends', friend, ledger['friend'])).toBe(true);
  });

  it('classifies anyone who boosted me as a reader, even strangers', () => {
    const ledger: PeopleLedger = {};
    const stranger = makeAccount('stranger');
    noteNotifications(ledger, [makeNotification('n1', 'reblog', stranger)]);

    const evidence = ledger['stranger'];
    expect(evidence.snapshot?.acct).toBe(stranger.acct);
    expect(matchesPeopleFilter('readers', stranger, evidence)).toBe(true);
    expect(matchesPeopleFilter('mutuals', stranger, evidence)).toBe(false);
  });

  it('classifies idols as people I replied to with no inbound interaction', () => {
    const ledger: PeopleLedger = {};
    const idol = makeAccount('idol');
    noteAccount(ledger, idol);
    noteRelationships(ledger, [{ id: 'idol', following: true, followed_by: false }]);
    const myReply = makeStatus('s1', makeAccount('me'), {
      in_reply_to_id: 'x',
      in_reply_to_account_id: 'idol',
    });
    noteOwnStatuses(ledger, [myReply], 'me');

    expect(matchesPeopleFilter('idols', idol, ledger['idol'])).toBe(true);

    // They favourite me back — they graduate out of idols.
    noteNotifications(ledger, [makeNotification('n1', 'favourite', idol)]);
    expect(matchesPeopleFilter('idols', idol, ledger['idol'])).toBe(false);
  });

  it('separates chatty and broadcasters by observed reply ratio', () => {
    const ledger: PeopleLedger = {};
    const chatty = makeAccount('chatty');
    const broadcaster = makeAccount('broadcaster', { statuses_count: 5000 });
    noteAccount(ledger, chatty);
    noteAccount(ledger, broadcaster);

    const statuses: LiteStatus[] = [];
    for (let index = 0; index < 6; index += 1) {
      statuses.push(makeStatus(`c${index}`, chatty, { in_reply_to_id: 'x' }));
      statuses.push(makeStatus(`b${index}`, broadcaster));
    }
    noteObservedStatuses(ledger, statuses);

    expect(matchesPeopleFilter('chatty', chatty, ledger['chatty'])).toBe(true);
    expect(matchesPeopleFilter('broadcasters', chatty, ledger['chatty'])).toBe(false);
    expect(matchesPeopleFilter('broadcasters', broadcaster, ledger['broadcaster'])).toBe(true);
    expect(matchesPeopleFilter('chatty', broadcaster, ledger['broadcaster'])).toBe(false);
  });

  it('does not double count a status seen in two loads', () => {
    const ledger: PeopleLedger = {};
    const person = makeAccount('person');
    noteAccount(ledger, person);
    const status = makeStatus('s1', person);
    noteObservedStatuses(ledger, [status]);
    noteObservedStatuses(ledger, [status]);

    expect(ledger['person'].sampledPosts).toBe(1);
  });

  it('sorts people into lively and graveyard by last status date', () => {
    const fresh = makeAccount('fresh');
    const quiet = makeAccount('quiet', {
      last_status_at: new Date(Date.now() - 200 * 86_400_000).toISOString(),
    });
    const silent = makeAccount('silent', { last_status_at: null });

    expect(matchesPeopleFilter('lively', fresh, undefined)).toBe(true);
    expect(matchesPeopleFilter('graveyard', fresh, undefined)).toBe(false);
    expect(matchesPeopleFilter('graveyard', quiet, undefined)).toBe(true);
    expect(matchesPeopleFilter('graveyard', silent, undefined)).toBe(true);
    expect(matchesPeopleFilter('lively', silent, undefined)).toBe(false);
  });

  it('classifies big non-followers as parasocials', () => {
    const ledger: PeopleLedger = {};
    const celebrity = makeAccount('celebrity', {
      followers_count: PEOPLE_THRESHOLDS.parasocialFollowersMin + 1,
    });
    noteAccount(ledger, celebrity);
    noteRelationships(ledger, [{ id: 'celebrity', following: true, followed_by: false }]);

    expect(matchesPeopleFilter('parasocials', celebrity, ledger['celebrity'])).toBe(true);

    noteRelationships(ledger, [{ id: 'celebrity', following: true, followed_by: true }]);
    expect(matchesPeopleFilter('parasocials', celebrity, ledger['celebrity'])).toBe(false);
  });

  it('puts uncategorized quiet follows in other', () => {
    const ledger: PeopleLedger = {};
    const quiet = makeAccount('quiet', {
      last_status_at: new Date(Date.now() - 60 * 86_400_000).toISOString(),
    });
    noteAccount(ledger, quiet);
    noteRelationships(ledger, [{ id: 'quiet', following: true, followed_by: false }]);

    expect(matchesPeopleFilter('other', quiet, ledger['quiet'])).toBe(true);
    expect(matchesPeopleFilter('lively', quiet, ledger['quiet'])).toBe(false);
    expect(matchesPeopleFilter('graveyard', quiet, ledger['quiet'])).toBe(false);
  });

  it('freshens last status date from mention and status notifications', () => {
    const ledger: PeopleLedger = {};
    const stale = new Date(Date.now() - 200 * 86_400_000).toISOString();
    const person = makeAccount('person', { last_status_at: stale });
    noteAccount(ledger, person);
    expect(matchesPeopleFilter('lively', person, ledger['person'])).toBe(false);

    noteNotifications(ledger, [
      makeNotification('n1', 'mention', { ...person, last_status_at: null }),
    ]);
    // account.last_status_at is stale, but the ledger knows better now
    expect(
      matchesPeopleFilter('lively', { ...person, last_status_at: null }, ledger['person']),
    ).toBe(true);
  });

  it('sorts newest-first by default, oldest-first for graveyard, by followers for parasocials', () => {
    const ledger: PeopleLedger = {};
    const old = makeAccount('old', {
      last_status_at: '2020-01-01T00:00:00Z',
      followers_count: 50_000,
    });
    const fresh = makeAccount('fresh', { followers_count: 10 });
    const never = makeAccount('never', { last_status_at: null, followers_count: 200 });

    expect(sortPeople('all', [old, fresh, never], ledger).map((a) => a.id)).toEqual([
      'fresh',
      'old',
      'never',
    ]);
    expect(sortPeople('graveyard', [old, fresh, never], ledger).map((a) => a.id)).toEqual([
      'never',
      'old',
      'fresh',
    ]);
    expect(sortPeople('parasocials', [old, fresh, never], ledger).map((a) => a.id)).toEqual([
      'old',
      'never',
      'fresh',
    ]);
  });

  it('prunes stale strangers but keeps follows and sticky facts', () => {
    const ledger: PeopleLedger = {};
    const followed = makeAccount('followed');
    const reader = makeAccount('reader');
    const stranger = makeAccount('stranger');
    noteAccount(ledger, followed);
    noteNotifications(ledger, [makeNotification('n1', 'reblog', reader)]);
    noteAccount(ledger, stranger);

    const future = Date.now() + (PEOPLE_THRESHOLDS.graveyardDays + 1) * 86_400_000;
    pruneLedger(ledger, new Set(['followed']), future);

    expect(ledger['followed']).toBeDefined();
    expect(ledger['reader']).toBeDefined();
    expect(ledger['stranger']).toBeUndefined();
  });

  it('caps the sampled status id list', () => {
    const ledger: PeopleLedger = {};
    const person = makeAccount('person');
    ensureEvidence(ledger, person);
    const statuses = Array.from({ length: PEOPLE_THRESHOLDS.sampledStatusIdCap + 20 }, (_, i) =>
      makeStatus(`s${i}`, person),
    );
    noteObservedStatuses(ledger, statuses);

    expect(ledger['person'].sampledStatusIds.length).toBe(PEOPLE_THRESHOLDS.sampledStatusIdCap);
    expect(ledger['person'].sampledPosts).toBe(PEOPLE_THRESHOLDS.sampledStatusIdCap + 20);
  });
});
