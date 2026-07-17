import { HttpClient, HttpErrorResponse, HttpResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { LITE_LIMITS, LiteRequestBudget } from './lite.limits';
import {
  LiteAccount,
  LiteConnection,
  LiteContext,
  LiteNotification,
  LiteRelationship,
  LiteStatus,
} from './lite.models';
import { DraftNode } from '../app/mastodon';
import { LiteApiStatsService } from './lite-api-stats.service';

/** Extract the rel="next" URL from a Mastodon Link header, if present. */
export function parseNextLink(linkHeader: string | null): string | null {
  if (!linkHeader) return null;
  for (const part of linkHeader.split(',')) {
    const match = /<([^>]+)>\s*;\s*rel="next"/.exec(part);
    if (match) return match[1];
  }
  return null;
}

function headerNumber(response: HttpResponse<unknown>, name: string): number | null {
  const raw = response.headers.get(name);
  if (raw === null) return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

/** Coarse endpoint family for observability — never the full URL. */
export function endpointFamily(url: string): string {
  if (url.includes('/timelines/home')) return 'home timeline';
  if (url.includes('/context')) return 'thread context';
  if (url.includes('/following')) return 'following';
  if (url.includes('/statuses') && url.includes('/accounts/')) return 'account statuses';
  if (url.includes('/notifications')) return 'notifications';
  if (url.includes('/relationships')) return 'relationships';
  if (url.includes('/statuses')) return 'publish';
  return 'other';
}

@Injectable({ providedIn: 'root' })
export class LiteMastodonService {
  private readonly http = inject(HttpClient);
  private readonly apiStats = inject(LiteApiStatsService);

  home(connection: LiteConnection, budget: LiteRequestBudget): Promise<LiteStatus[]> {
    return this.get<LiteStatus[]>(
      connection,
      `/api/v1/timelines/home?limit=${LITE_LIMITS.pageSize}`,
      budget,
    );
  }

  /**
   * Fetch the first following page (so new follows always appear), then one
   * more page — resuming from `cursor` when a previous session left one, so
   * repeat visits gradually cover a large following list without ever
   * loading it all at once. Returns the next cursor, or null when the crawl
   * has wrapped around.
   */
  async following(
    connection: LiteConnection,
    budget: LiteRequestBudget,
    cursor: string | null = null,
  ): Promise<{ accounts: LiteAccount[]; next: string | null }> {
    const firstUrl = `${connection.instanceUrl}/api/v1/accounts/${encodeURIComponent(connection.account.id)}/following?limit=80`;
    const first = await this.getPage<LiteAccount>(connection, firstUrl, budget);
    const accounts = [...first.items];
    let next = cursor ?? first.next;
    for (let page = 1; page < LITE_LIMITS.followingPages && next; page += 1) {
      const deeper = await this.getPage<LiteAccount>(connection, next, budget);
      accounts.push(...deeper.items);
      next = deeper.next;
    }
    return { accounts, next };
  }

  notifications(
    connection: LiteConnection,
    budget: LiteRequestBudget,
  ): Promise<LiteNotification[]> {
    const types = ['mention', 'favourite', 'reblog', 'status', 'follow']
      .map((type) => `types[]=${type}`)
      .join('&');
    return this.getPaginated<LiteNotification>(
      connection,
      `${connection.instanceUrl}/api/v1/notifications?limit=${LITE_LIMITS.pageSize}&${types}`,
      LITE_LIMITS.notificationPages,
      budget,
    );
  }

  async relationships(
    connection: LiteConnection,
    accountIds: string[],
    budget: LiteRequestBudget,
  ): Promise<LiteRelationship[]> {
    const results: LiteRelationship[] = [];
    for (let start = 0; start < accountIds.length; start += LITE_LIMITS.relationshipChunk) {
      const chunk = accountIds.slice(start, start + LITE_LIMITS.relationshipChunk);
      const query = chunk.map((id) => `id[]=${encodeURIComponent(id)}`).join('&');
      results.push(
        ...(await this.get<LiteRelationship[]>(
          connection,
          `/api/v1/accounts/relationships?${query}`,
          budget,
        )),
      );
    }
    return results;
  }

  accountStatuses(
    connection: LiteConnection,
    accountId: string,
    budget: LiteRequestBudget,
  ): Promise<LiteStatus[]> {
    return this.get<LiteStatus[]>(
      connection,
      `/api/v1/accounts/${encodeURIComponent(accountId)}/statuses?limit=${LITE_LIMITS.pageSize}`,
      budget,
    );
  }

  /** One page of the account's statuses older than `maxId` — the analytics crawl. */
  accountStatusesBefore(
    connection: LiteConnection,
    accountId: string,
    maxId: string,
    budget: LiteRequestBudget,
  ): Promise<LiteStatus[]> {
    return this.get<LiteStatus[]>(
      connection,
      `/api/v1/accounts/${encodeURIComponent(accountId)}/statuses?limit=${LITE_LIMITS.pageSize}&max_id=${encodeURIComponent(maxId)}`,
      budget,
    );
  }

  /** Ancestors and descendants of a status — the full discussion thread. */
  context(
    connection: LiteConnection,
    statusId: string,
    budget: LiteRequestBudget,
  ): Promise<LiteContext> {
    return this.get<LiteContext>(
      connection,
      `/api/v1/statuses/${encodeURIComponent(statusId)}/context`,
      budget,
    );
  }

  async publishNode(
    connection: LiteConnection,
    node: DraftNode,
    language: string | null,
    inReplyToId: string | null,
  ): Promise<LiteStatus> {
    const body: Record<string, string> = {
      status: node.body,
      visibility: node.visibility,
    };
    if (node.spoiler_text?.trim()) body['spoiler_text'] = node.spoiler_text.trim();
    if (language?.trim()) body['language'] = language.trim();
    if (inReplyToId) body['in_reply_to_id'] = inReplyToId;
    const url = `${connection.instanceUrl}/api/v1/statuses`;
    return this.observe(url, () =>
      firstValueFrom(
        this.http.post<LiteStatus>(url, body, {
          headers: {
            Authorization: `Bearer ${connection.accessToken}`,
            'Idempotency-Key': crypto.randomUUID(),
          },
        }),
      ),
    );
  }

  private async getPaginated<T>(
    connection: LiteConnection,
    firstUrl: string,
    maxPages: number,
    budget: LiteRequestBudget,
  ): Promise<T[]> {
    const items: T[] = [];
    let url: string | null = firstUrl;
    for (let page = 0; page < maxPages && url; page += 1) {
      const result: { items: T[]; next: string | null } = await this.getPage<T>(
        connection,
        url,
        budget,
      );
      items.push(...result.items);
      url = result.next;
    }
    return items;
  }

  private async getPage<T>(
    connection: LiteConnection,
    url: string,
    budget: LiteRequestBudget,
  ): Promise<{ items: T[]; next: string | null }> {
    budget.spend();
    const response = await this.observeResponse<T[]>(connection, url);
    return { items: response.body ?? [], next: parseNextLink(response.headers.get('Link')) };
  }

  private async get<T>(
    connection: LiteConnection,
    path: string,
    budget: LiteRequestBudget,
  ): Promise<T> {
    budget.spend();
    const response = await this.observeResponse<T>(connection, `${connection.instanceUrl}${path}`);
    return response.body as T;
  }

  private async observeResponse<T>(
    connection: LiteConnection,
    url: string,
  ): Promise<HttpResponse<T>> {
    const started = performance.now();
    try {
      const response = await firstValueFrom(
        this.http.get<T>(url, {
          headers: { Authorization: `Bearer ${connection.accessToken}` },
          observe: 'response',
        }),
      );
      this.apiStats.record({
        endpoint: endpointFamily(url),
        ok: true,
        rateLimited: false,
        durationMs: performance.now() - started,
        rateLimitRemaining: headerNumber(response, 'X-RateLimit-Remaining'),
        rateLimitLimit: headerNumber(response, 'X-RateLimit-Limit'),
      });
      return response;
    } catch (error: unknown) {
      this.recordFailure(url, error, started);
      throw error;
    }
  }

  /** Time a call and fold the outcome into the running API aggregates. */
  private async observe<T>(url: string, run: () => Promise<T>): Promise<T> {
    const started = performance.now();
    try {
      const result = await run();
      this.apiStats.record({
        endpoint: endpointFamily(url),
        ok: true,
        rateLimited: false,
        durationMs: performance.now() - started,
      });
      return result;
    } catch (error: unknown) {
      this.recordFailure(url, error, started);
      throw error;
    }
  }

  private recordFailure(url: string, error: unknown, started: number): void {
    const status = error instanceof HttpErrorResponse ? error.status : 0;
    this.apiStats.record({
      endpoint: endpointFamily(url),
      ok: false,
      rateLimited: status === 429,
      durationMs: performance.now() - started,
    });
  }
}
