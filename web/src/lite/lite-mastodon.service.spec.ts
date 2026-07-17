import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { DraftNode } from '../app/mastodon';
import { sampleAccount } from './lite-fixtures';
import { LiteMastodonService, parseNextLink } from './lite-mastodon.service';
import { LITE_LIMITS, LiteRequestBudget } from './lite.limits';
import { LiteConnection } from './lite.models';

describe('LiteMastodonService publishing', () => {
  let service: LiteMastodonService;
  let http: HttpTestingController;
  const connection: LiteConnection = {
    version: 1,
    instanceUrl: 'https://example.social',
    clientId: 'client',
    clientSecret: 'secret',
    accessToken: 'token',
    scope: 'read write:statuses',
    account: sampleAccount,
  };

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(LiteMastodonService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('publishes a draft node as a reply with its per-post options', async () => {
    const node: DraftNode = {
      client_id: '00000000-0000-4000-8000-000000000002',
      parent_client_id: '00000000-0000-4000-8000-000000000001',
      mode: 'manual',
      body: 'Second post',
      spoiler_text: 'A warning',
      visibility: 'unlisted',
    };
    const result = service.publishNode(connection, node, 'en', 'status-1');
    const request = http.expectOne('https://example.social/api/v1/statuses');

    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({
      status: 'Second post',
      visibility: 'unlisted',
      spoiler_text: 'A warning',
      language: 'en',
      in_reply_to_id: 'status-1',
    });
    expect(request.request.headers.get('Authorization')).toBe('Bearer token');
    expect(request.request.headers.has('Idempotency-Key')).toBe(true);
    request.flush({ id: 'status-2' });
    await expect(result).resolves.toMatchObject({ id: 'status-2' });
  });

  it('follows the Link header for a second following page and returns the cursor', async () => {
    const budget = new LiteRequestBudget();
    const result = service.following(connection, budget);

    const first = http.expectOne(
      `https://example.social/api/v1/accounts/${sampleAccount.id}/following?limit=80`,
    );
    first.flush([{ id: 'a1' }], {
      headers: {
        Link: '<https://example.social/api/v1/accounts/sample-me/following?limit=80&max_id=9>; rel="next"',
      },
    });
    await settle();
    const second = http.expectOne(
      'https://example.social/api/v1/accounts/sample-me/following?limit=80&max_id=9',
    );
    second.flush([{ id: 'a2' }], {
      headers: { Link: '<https://example.social/next-again>; rel="next"' },
    });

    await expect(result).resolves.toMatchObject({
      accounts: [{ id: 'a1' }, { id: 'a2' }],
      next: 'https://example.social/next-again',
    });
    expect(budget.callsUsed).toBe(LITE_LIMITS.followingPages);
  });

  it('resumes the following crawl from a stored cursor after a fresh first page', async () => {
    const budget = new LiteRequestBudget();
    const result = service.following(connection, budget, 'https://example.social/deep-cursor');

    const first = http.expectOne(
      `https://example.social/api/v1/accounts/${sampleAccount.id}/following?limit=80`,
    );
    first.flush([{ id: 'a1' }], {
      headers: { Link: '<https://example.social/page-2>; rel="next"' },
    });
    await settle();
    // The second call goes to the stored cursor, not back to page 2.
    const deep = http.expectOne('https://example.social/deep-cursor');
    deep.flush([{ id: 'z9' }]);

    await expect(result).resolves.toMatchObject({
      accounts: [{ id: 'a1' }, { id: 'z9' }],
      next: null,
    });
  });

  it('chunks relationship lookups', async () => {
    const budget = new LiteRequestBudget();
    const ids = Array.from({ length: LITE_LIMITS.relationshipChunk + 1 }, (_, i) => `id${i}`);
    const result = service.relationships(connection, ids, budget);

    const first = http.expectOne((request) =>
      request.url.startsWith('https://example.social/api/v1/accounts/relationships'),
    );
    first.flush([{ id: 'id0', following: true, followed_by: true }]);
    await settle();
    const second = http.expectOne((request) =>
      request.url.startsWith('https://example.social/api/v1/accounts/relationships'),
    );
    second.flush([
      { id: `id${LITE_LIMITS.relationshipChunk}`, following: true, followed_by: false },
    ]);

    await expect(result).resolves.toHaveLength(2);
    expect(budget.callsUsed).toBe(2);
  });
});

/** Let the awaited page-fetch continuation run before expecting the next request. */
function settle(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

describe('parseNextLink', () => {
  it('extracts the rel=next URL', () => {
    const header =
      '<https://example.social/api/v1/notifications?max_id=5>; rel="next", ' +
      '<https://example.social/api/v1/notifications?since_id=9>; rel="prev"';
    expect(parseNextLink(header)).toBe('https://example.social/api/v1/notifications?max_id=5');
  });

  it('returns null when there is no next page', () => {
    expect(parseNextLink(null)).toBeNull();
    expect(parseNextLink('<https://example.social/x>; rel="prev"')).toBeNull();
  });
});
