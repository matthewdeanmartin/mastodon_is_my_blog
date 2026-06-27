import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';
import { sampleAccount } from './lite-fixtures';
import { LiteStorageService } from './lite-storage.service';
import { LiteConnection, PendingOAuth } from './lite.models';

describe('LiteStorageService', () => {
  let service: LiteStorageService;

  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    TestBed.resetTestingModule();
    service = TestBed.inject(LiteStorageService);
  });

  it('persists and clears a versioned connection', () => {
    const connection: LiteConnection = {
      version: 1,
      instanceUrl: 'https://example.social',
      clientId: 'client',
      clientSecret: 'secret',
      accessToken: 'token',
      scope: 'read',
      account: sampleAccount,
    };

    service.saveConnection(connection);
    expect(service.connection()).toEqual(connection);

    service.clearConnection();
    expect(service.connection()).toBeNull();
  });

  it('keeps pending OAuth data in session storage', () => {
    const pending: PendingOAuth = {
      version: 1,
      instanceUrl: 'https://example.social',
      clientId: 'client',
      clientSecret: 'secret',
      redirectUri: 'https://lite.example/',
      state: 'state',
      verifier: 'verifier',
      createdAt: Date.now(),
    };

    service.savePending(pending);
    expect(service.readPending()).toEqual(pending);
    expect(localStorage.getItem('mimb:lite:v1:oauth-pending')).toBeNull();
  });

  it('isolates cached data and erases it on disconnect', () => {
    const connection: LiteConnection = {
      version: 1,
      instanceUrl: 'https://example.social',
      clientId: 'client',
      clientSecret: 'secret',
      accessToken: 'token',
      scope: 'read',
      account: sampleAccount,
    };

    service.saveConnection(connection);
    service.writeCache(connection, 'home', [{ id: 'opaque-id' }]);
    expect(service.readCache(connection, 'home')).toEqual([{ id: 'opaque-id' }]);

    service.clearConnection();
    expect(service.readCache(connection, 'home')).toBeNull();
  });
});
