import { HttpClient, HttpErrorResponse, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import {
  AppRegistration,
  LiteAccount,
  LiteConnection,
  PendingOAuth,
  TokenResponse,
} from './lite.models';
import { LiteStorageService } from './lite-storage.service';

const OAUTH_MAX_AGE_MS = 10 * 60 * 1000;

@Injectable({ providedIn: 'root' })
export class LiteOAuthService {
  private readonly http = inject(HttpClient);
  private readonly storage = inject(LiteStorageService);

  hasCallback(): boolean {
    const query = new URLSearchParams(window.location.search);
    return query.has('code') || query.has('error');
  }

  async connect(instanceInput: string): Promise<void> {
    const instanceUrl = normalizeInstanceUrl(instanceInput);
    await firstValueFrom(this.http.get(`${instanceUrl}/api/v2/instance`));

    const redirectUri = callbackUrl();
    const registration = await firstValueFrom(
      this.http.post<AppRegistration>(`${instanceUrl}/api/v1/apps`, {
        client_name: 'Mastodon is My Blog Lite',
        redirect_uris: redirectUri,
        scopes: 'read write:statuses',
        website: window.location.origin,
      }),
    );

    const state = randomUrlSafe(32);
    const verifier = randomUrlSafe(64);
    const challenge = await sha256UrlSafe(verifier);
    const pending: PendingOAuth = {
      version: 1,
      instanceUrl,
      clientId: registration.client_id,
      clientSecret: registration.client_secret,
      redirectUri,
      state,
      verifier,
      createdAt: Date.now(),
    };
    this.storage.savePending(pending);

    const authorize = new URL('/oauth/authorize', instanceUrl);
    authorize.searchParams.set('response_type', 'code');
    authorize.searchParams.set('client_id', pending.clientId);
    authorize.searchParams.set('redirect_uri', redirectUri);
    authorize.searchParams.set('scope', 'read write:statuses');
    authorize.searchParams.set('state', state);
    authorize.searchParams.set('code_challenge', challenge);
    authorize.searchParams.set('code_challenge_method', 'S256');
    window.location.assign(authorize.toString());
  }

  async completeCallback(): Promise<LiteConnection> {
    const query = new URLSearchParams(window.location.search);
    const oauthError = query.get('error');
    const code = query.get('code');
    const state = query.get('state');
    stripCallbackQuery();
    if (oauthError) {
      throw new Error(`Authorization was declined: ${oauthError}`);
    }

    const pending = this.storage.readPending();
    if (!code || !state || !pending || state !== pending.state) {
      throw new Error('The OAuth callback could not be verified. Please connect again.');
    }
    if (Date.now() - pending.createdAt > OAUTH_MAX_AGE_MS) {
      throw new Error('The OAuth request expired. Please connect again.');
    }

    const body = new HttpParams()
      .set('grant_type', 'authorization_code')
      .set('code', code)
      .set('client_id', pending.clientId)
      .set('client_secret', pending.clientSecret)
      .set('redirect_uri', pending.redirectUri)
      .set('code_verifier', pending.verifier);
    const token = await firstValueFrom(
      this.http.post<TokenResponse>(`${pending.instanceUrl}/oauth/token`, body, {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      }),
    );
    const account = await firstValueFrom(
      this.http.get<LiteAccount>(`${pending.instanceUrl}/api/v1/accounts/verify_credentials`, {
        headers: { Authorization: `Bearer ${token.access_token}` },
      }),
    );
    const connection: LiteConnection = {
      version: 1,
      instanceUrl: pending.instanceUrl,
      clientId: pending.clientId,
      clientSecret: pending.clientSecret,
      accessToken: token.access_token,
      scope: token.scope,
      account,
    };
    this.storage.saveConnection(connection);
    this.storage.clearPending();
    return connection;
  }

  async disconnect(): Promise<void> {
    const connection = this.storage.connection();
    if (!connection) return;
    const body = new HttpParams()
      .set('client_id', connection.clientId)
      .set('client_secret', connection.clientSecret)
      .set('token', connection.accessToken);
    try {
      await firstValueFrom(
        this.http.post(`${connection.instanceUrl}/oauth/revoke`, body, {
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        }),
      );
    } catch (error: unknown) {
      if (!(error instanceof HttpErrorResponse)) throw error;
    } finally {
      this.storage.clearConnection();
      this.storage.clearPending();
    }
  }
}

export function normalizeInstanceUrl(input: string): string {
  const trimmed = input.trim();
  if (!trimmed) throw new Error('Enter your Mastodon instance.');
  const withScheme = /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
  const url = new URL(withScheme);
  const localhost = url.hostname === 'localhost' || url.hostname === '127.0.0.1';
  if (url.protocol !== 'https:' && !localhost) throw new Error('The instance must use HTTPS.');
  if (url.username || url.password || url.search || url.hash) {
    throw new Error('Enter only the instance hostname, without credentials or query text.');
  }
  if (url.pathname !== '/' && url.pathname !== '') {
    throw new Error('Enter only the instance hostname, without a path.');
  }
  return url.origin;
}

function callbackUrl(): string {
  const url = new URL(document.baseURI);
  url.search = '';
  url.hash = '';
  return url.toString();
}

function stripCallbackQuery(): void {
  const url = new URL(window.location.href);
  url.searchParams.delete('code');
  url.searchParams.delete('state');
  url.searchParams.delete('error');
  url.searchParams.delete('error_description');
  window.history.replaceState({}, document.title, `${url.pathname}${url.hash}`);
}

function randomUrlSafe(byteCount: number): string {
  const bytes = crypto.getRandomValues(new Uint8Array(byteCount));
  return base64Url(bytes);
}

async function sha256UrlSafe(value: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
  return base64Url(new Uint8Array(digest));
}

function base64Url(bytes: Uint8Array): string {
  let value = '';
  for (const byte of bytes) value += String.fromCharCode(byte);
  return btoa(value).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
