import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { LITE_LIMITS, LiteRequestBudget } from './lite.limits';
import { LiteAccount, LiteConnection, LiteStatus } from './lite.models';
import { DraftNode } from '../app/mastodon';

@Injectable({ providedIn: 'root' })
export class LiteMastodonService {
  private readonly http = inject(HttpClient);

  home(connection: LiteConnection, budget: LiteRequestBudget): Promise<LiteStatus[]> {
    return this.get<LiteStatus[]>(
      connection,
      `/api/v1/timelines/home?limit=${LITE_LIMITS.pageSize}`,
      budget,
    );
  }

  following(connection: LiteConnection, budget: LiteRequestBudget): Promise<LiteAccount[]> {
    return this.get<LiteAccount[]>(
      connection,
      `/api/v1/accounts/${encodeURIComponent(connection.account.id)}/following?limit=80`,
      budget,
    );
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

  publishNode(
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
    return firstValueFrom(
      this.http.post<LiteStatus>(`${connection.instanceUrl}/api/v1/statuses`, body, {
        headers: {
          Authorization: `Bearer ${connection.accessToken}`,
          'Idempotency-Key': crypto.randomUUID(),
        },
      }),
    );
  }

  private get<T>(connection: LiteConnection, path: string, budget: LiteRequestBudget): Promise<T> {
    budget.spend();
    return firstValueFrom(
      this.http.get<T>(`${connection.instanceUrl}${path}`, {
        headers: { Authorization: `Bearer ${connection.accessToken}` },
      }),
    );
  }
}
