import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { DraftNode } from '../app/mastodon';
import { sampleAccount } from './lite-fixtures';
import { LiteMastodonService } from './lite-mastodon.service';
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
});
