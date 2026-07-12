import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { LITE_LIMITS, LiteRequestBudget } from './lite.limits';
import { LiteAccount, LiteConnection, LiteStatus } from './lite.models';

@Injectable({ providedIn: 'root' })
export class LiteMastodonService {
  private readonly http = inject(HttpClient);

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

  private get<T>(connection: LiteConnection, path: string, budget: LiteRequestBudget): Promise<T> {
    budget.spend();
    return firstValueFrom(
      this.http.get<T>(`${connection.instanceUrl}${path}`, {
        headers: { Authorization: `Bearer ${connection.accessToken}` },
      }),
    );
  }
}
