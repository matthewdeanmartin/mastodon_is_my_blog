import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

import { sampleAccount, sampleFollowing, sampleStatuses } from './lite-fixtures';
import { LITE_LIMITS, LiteRequestBudget } from './lite.limits';
import { LiteMastodonService } from './lite-mastodon.service';
import { LiteOAuthService } from './lite-oauth.service';
import { LiteStorageService } from './lite-storage.service';
import { LiteAccount, LiteConnection, LiteFilter, LitePage, LiteStatus } from './lite.models';
import { filterLiteStatuses } from './lite-filters';

@Component({
  selector: 'app-lite-root',
  imports: [CommonModule, FormsModule],
  templateUrl: './lite-app.component.html',
  styleUrl: './lite-app.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LiteAppComponent implements OnInit {
  private readonly oauth = inject(LiteOAuthService);
  private readonly storage = inject(LiteStorageService);
  private readonly mastodon = inject(LiteMastodonService);

  readonly connection = this.storage.connection;
  readonly account = signal<LiteAccount | null>(null);
  readonly statuses = signal<LiteStatus[]>([]);
  readonly following = signal<LiteAccount[]>([]);
  readonly page = signal<LitePage>('people');
  readonly filter = signal<LiteFilter>('storms');
  readonly selectedAccount = signal<LiteAccount | null>(null);
  readonly loading = signal(false);
  readonly connecting = signal(false);
  readonly sampleMode = signal(false);
  readonly error = signal<string | null>(null);
  readonly callsUsed = signal(0);

  instance = '';

  readonly connected = computed(() => this.sampleMode() || this.connection() !== null);
  readonly composeUrl = computed(() => {
    const connection = this.connection();
    return connection ? `${connection.instanceUrl}/publish` : null;
  });
  readonly filterLabel = computed(() => {
    const labels: Record<LiteFilter, string> = {
      storms: 'Storms',
      shorts: 'Short text',
      replies: 'Discussions',
      media: 'Media',
      links: 'Links',
      boosts: 'Boosts',
    };
    return labels[this.filter()];
  });
  readonly visibleStatuses = computed(() => {
    if (this.page() === 'people') return this.statuses().filter((status) => status.reblog === null);
    return filterLiteStatuses(this.statuses(), this.filter());
  });

  async ngOnInit(): Promise<void> {
    document.title = 'Mastodon is My Blog Lite';
    if (this.oauth.hasCallback()) {
      this.connecting.set(true);
      try {
        const connection = await this.oauth.completeCallback();
        this.account.set(connection.account);
        await this.loadInitial();
      } catch (error: unknown) {
        this.error.set(errorMessage(error));
      } finally {
        this.connecting.set(false);
      }
      return;
    }

    const connection = this.connection();
    if (connection) {
      this.account.set(connection.account);
      this.restoreCache(connection);
      await this.loadInitial();
    }
  }

  async connect(): Promise<void> {
    this.error.set(null);
    this.connecting.set(true);
    try {
      await this.oauth.connect(this.instance);
    } catch (error: unknown) {
      this.error.set(errorMessage(error));
      this.connecting.set(false);
    }
  }

  useSampleData(): void {
    this.sampleMode.set(true);
    this.account.set(sampleAccount);
    this.following.set(sampleFollowing);
    this.statuses.set(sampleStatuses);
    this.page.set('people');
    this.filter.set('storms');
    this.selectedAccount.set(sampleAccount);
    this.callsUsed.set(0);
    this.error.set(null);
  }

  async navigate(page: LitePage): Promise<void> {
    this.page.set(page);
    if (page === 'write') return;
    if (page === 'forums') this.filter.set('replies');
    if (page === 'people' || (page === 'content' && this.filter() === 'replies')) {
      this.filter.set('storms');
    }
    await this.loadAccount(this.selectedAccount() ?? this.account());
  }

  setFilter(filter: LiteFilter): void {
    this.filter.set(filter);
    this.page.set(filter === 'replies' ? 'forums' : 'content');
  }

  async selectFollowing(account: LiteAccount): Promise<void> {
    this.selectedAccount.set(account);
    this.page.set('people');
    this.filter.set('storms');
    await this.loadAccount(account);
  }

  async refresh(): Promise<void> {
    if (this.selectedAccount()) {
      await this.loadAccount(this.selectedAccount());
    } else {
      await this.loadAccount(this.account());
    }
  }

  async disconnect(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      if (!this.sampleMode()) await this.oauth.disconnect();
    } catch (error: unknown) {
      this.error.set(errorMessage(error));
    } finally {
      this.sampleMode.set(false);
      this.account.set(null);
      this.statuses.set([]);
      this.following.set([]);
      this.selectedAccount.set(null);
      this.loading.set(false);
    }
  }

  displayStatus(status: LiteStatus): LiteStatus {
    return status.reblog ?? status;
  }

  initials(account: LiteAccount): string {
    const name = account.display_name.trim() || account.username;
    return name.slice(0, 1).toUpperCase();
  }

  relativeDate(iso: string): string {
    const seconds = Math.max(1, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
  }

  private async loadInitial(): Promise<void> {
    const connection = this.connection();
    if (!connection) return;
    this.loading.set(true);
    this.error.set(null);
    const budget = new LiteRequestBudget();
    try {
      const [statuses, following] = await Promise.all([
        this.mastodon.accountStatuses(connection, connection.account.id, budget),
        this.mastodon.following(connection, budget),
      ]);
      this.statuses.set(statuses.slice(0, LITE_LIMITS.maxCachedOwnStatuses));
      this.selectedAccount.set(connection.account);
      this.following.set(following.slice(0, LITE_LIMITS.maxCachedFollowing));
      this.storage.writeCache(connection, 'own-statuses', this.statuses());
      this.storage.writeCache(connection, 'following', this.following());
      this.callsUsed.set(budget.callsUsed);
    } catch (error: unknown) {
      this.error.set(errorMessage(error));
      this.callsUsed.set(budget.callsUsed);
    } finally {
      this.loading.set(false);
    }
  }

  private async loadAccount(account: LiteAccount | null): Promise<void> {
    if (!account) return;
    if (this.sampleMode()) {
      this.statuses.set(sampleStatuses.filter((status) => status.account.id === account.id));
      return;
    }
    const connection = this.connection();
    if (!connection) return;
    await this.runOperation((budget) =>
      this.mastodon.accountStatuses(connection, account.id, budget),
    );
  }

  private async runOperation(
    operation: (budget: LiteRequestBudget) => Promise<LiteStatus[]>,
  ): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    const budget = new LiteRequestBudget();
    try {
      const statuses = await operation(budget);
      this.statuses.set(statuses.slice(0, LITE_LIMITS.maxCachedStatusesPerAccount));
      const connection = this.connection();
      if (connection) this.storage.writeCache(connection, 'last-statuses', this.statuses());
      this.callsUsed.set(budget.callsUsed);
    } catch (error: unknown) {
      this.error.set(errorMessage(error));
      this.callsUsed.set(budget.callsUsed);
    } finally {
      this.loading.set(false);
    }
  }

  private restoreCache(connection: LiteConnection): void {
    const ownStatuses = this.storage.readCache<LiteStatus[]>(connection, 'own-statuses');
    const following = this.storage.readCache<LiteAccount[]>(connection, 'following');
    if (ownStatuses) {
      this.statuses.set(ownStatuses.slice(0, LITE_LIMITS.maxCachedOwnStatuses));
      this.selectedAccount.set(connection.account);
    }
    if (following) this.following.set(following.slice(0, LITE_LIMITS.maxCachedFollowing));
  }
}

function errorMessage(error: unknown): string {
  if (error instanceof HttpErrorResponse) {
    if (error.status === 0) {
      return 'The instance did not allow this browser request. Check the domain or try another instance.';
    }
    if (error.status === 401)
      return 'This connection is no longer authorized. Disconnect and connect again.';
    if (error.status === 429)
      return 'The instance asked Lite to slow down. Please wait before refreshing.';
    return `The instance returned HTTP ${error.status}.`;
  }
  if (error instanceof DOMException && error.name === 'QuotaExceededError') {
    return 'Browser storage is full. Lite showed the live result but could not cache it.';
  }
  return error instanceof Error ? error.message : 'Something unexpected happened.';
}
