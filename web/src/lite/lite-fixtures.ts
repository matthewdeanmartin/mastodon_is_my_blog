import { LiteAccount, LiteStatus } from './lite.models';
import { PeopleLedger, ensureEvidence, noteObservedStatuses } from './lite-people';

export const sampleAccount: LiteAccount = {
  id: 'sample-me',
  username: 'writer',
  acct: 'writer@social.example',
  display_name: 'A Small Internet Writer',
  avatar: '',
  note: '<p>Writing from the humane corner of the fediverse.</p>',
  url: 'https://social.example/@writer',
  followers_count: 428,
  following_count: 173,
  statuses_count: 2901,
};

export const sampleFollowing: LiteAccount[] = [
  {
    ...sampleAccount,
    id: 'sample-river',
    username: 'river',
    acct: 'river@forest.example',
    display_name: 'River Chen',
    avatar: '',
    url: 'https://forest.example/@river',
  },
  {
    ...sampleAccount,
    id: 'sample-ada',
    username: 'ada',
    acct: 'ada@tech.example',
    display_name: 'Ada Builds Things',
    avatar: '',
    url: 'https://tech.example/@ada',
  },
];

export const sampleStatuses: LiteStatus[] = [
  makeStatus(
    'sample-1',
    sampleFollowing[0],
    '<p>The good web is still here. It is just distributed in small rooms with excellent weirdos.</p>',
    18,
    5,
  ),
  makeStatus(
    'sample-2',
    sampleFollowing[1],
    '<p>I wrote up a tiny guide to designing software that can be left alone for a weekend. <a href="https://example.com/calm-software">Read it here</a>.</p>',
    31,
    12,
  ),
  {
    ...makeStatus(
      'sample-3',
      sampleAccount,
      '<p>A blog can be a place you tend instead of a stream you feed.</p>',
      44,
      9,
    ),
    media_attachments: [
      {
        id: 'sample-image',
        type: 'image',
        url: 'lite-sample.svg',
        preview_url: 'lite-sample.svg',
        description: 'A card reading Your Mastodon, as a blog',
      },
    ],
  },
  {
    ...makeStatus(
      'sample-4',
      sampleFollowing[0],
      '<p>And here is the second thought in the thread: slow software can still make fast humans.</p>',
      7,
      1,
    ),
    in_reply_to_id: 'sample-1',
  },
];

export function sampleLedger(): PeopleLedger {
  const ledger: PeopleLedger = {};
  const river = ensureEvidence(ledger, sampleFollowing[0]);
  river.everMutual = true;
  river.followsMe = true;
  river.everMentionedMe = true;
  river.lastStatusAt = new Date().toISOString();
  const ada = ensureEvidence(ledger, sampleFollowing[1]);
  ada.followsMe = false;
  ada.iRepliedToThem = true;
  ada.lastStatusAt = new Date().toISOString();
  noteObservedStatuses(ledger, sampleStatuses);
  return ledger;
}

function makeStatus(
  id: string,
  account: LiteAccount,
  content: string,
  favourites: number,
  boosts: number,
): LiteStatus {
  return {
    id,
    content,
    spoiler_text: '',
    created_at: new Date(Date.now() - Number(id.slice(-1)) * 3_600_000).toISOString(),
    url: `${account.url}/${id}`,
    visibility: 'public',
    in_reply_to_id: null,
    account,
    reblog: null,
    media_attachments: [],
    replies_count: id === 'sample-1' ? 3 : 1,
    reblogs_count: boosts,
    favourites_count: favourites,
  };
}
