import { Injectable, signal } from '@angular/core';
import { LiteConnection, PendingOAuth } from './lite.models';

const CONNECTION_KEY = 'mimb:lite:v1:connection';
const PENDING_KEY = 'mimb:lite:v1:oauth-pending';
const CACHE_PREFIX = 'mimb:lite:v1:cache:';

interface CacheEnvelope<T> {
  fetchedAt: number;
  value: T;
}

@Injectable({ providedIn: 'root' })
export class LiteStorageService {
  readonly connection = signal<LiteConnection | null>(this.readConnection());

  saveConnection(connection: LiteConnection): void {
    localStorage.setItem(CONNECTION_KEY, JSON.stringify(connection));
    this.connection.set(connection);
  }

  clearConnection(): void {
    localStorage.removeItem(CONNECTION_KEY);
    this.clearCaches();
    this.connection.set(null);
  }

  writeCache<T>(connection: LiteConnection, name: string, value: T): void {
    const envelope: CacheEnvelope<T> = { fetchedAt: Date.now(), value };
    localStorage.setItem(this.cacheKey(connection, name), JSON.stringify(envelope));
  }

  readCache<T>(connection: LiteConnection, name: string): T | null {
    const raw = localStorage.getItem(this.cacheKey(connection, name));
    if (!raw) return null;
    try {
      return (JSON.parse(raw) as CacheEnvelope<T>).value;
    } catch (error: unknown) {
      if (error instanceof SyntaxError) {
        localStorage.removeItem(this.cacheKey(connection, name));
        return null;
      }
      throw error;
    }
  }

  savePending(pending: PendingOAuth): void {
    sessionStorage.setItem(PENDING_KEY, JSON.stringify(pending));
  }

  readPending(): PendingOAuth | null {
    const value = sessionStorage.getItem(PENDING_KEY);
    if (!value) return null;
    try {
      const pending = JSON.parse(value) as PendingOAuth;
      return pending.version === 1 ? pending : null;
    } catch (error: unknown) {
      if (error instanceof SyntaxError) {
        sessionStorage.removeItem(PENDING_KEY);
        return null;
      }
      throw error;
    }
  }

  clearPending(): void {
    sessionStorage.removeItem(PENDING_KEY);
  }

  private clearCaches(): void {
    const keys: string[] = [];
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index);
      if (key?.startsWith(CACHE_PREFIX)) keys.push(key);
    }
    for (const key of keys) localStorage.removeItem(key);
  }

  private cacheKey(connection: LiteConnection, name: string): string {
    const host = new URL(connection.instanceUrl).host;
    return `${CACHE_PREFIX}${host}:${connection.account.id}:${name}`;
  }

  private readConnection(): LiteConnection | null {
    const value = localStorage.getItem(CONNECTION_KEY);
    if (!value) return null;
    try {
      const connection = JSON.parse(value) as LiteConnection;
      return connection.version === 1 ? connection : null;
    } catch (error: unknown) {
      if (error instanceof SyntaxError) {
        localStorage.removeItem(CONNECTION_KEY);
        return null;
      }
      throw error;
    }
  }
}
