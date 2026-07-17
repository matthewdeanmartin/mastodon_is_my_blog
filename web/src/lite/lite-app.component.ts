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

import { sampleAccount, sampleFollowing, sampleLedger, sampleStatuses } from './lite-fixtures';
import { LITE_LIMITS, LiteRequestBudget } from './lite.limits';
import { LiteMastodonService } from './lite-mastodon.service';
import { LiteOAuthService } from './lite-oauth.service';
import { LiteStorageService } from './lite-storage.service';
import {
  LiteAccount,
  LiteConnection,
  LiteContext,
  LiteFilter,
  LiteForumFilter,
  LitePage,
  LitePeopleFilter,
  LiteStatus,
} from './lite.models';
import { countLiteFilters, filterLiteStatuses } from './lite-filters';
import {
  FORUM_FILTER_LABELS,
  LiteThread,
  buildLiteThreads,
  countLiteThreadFilters,
  filterLiteThreads,
  threadHashtagFacets,
} from './lite-forums';
import {
  PEOPLE_FILTER_LABELS,
  PeopleLedger,
  countPeopleFilters,
  matchesPeopleFilter,
  noteAccount,
  noteNotifications,
  noteObservedStatuses,
  noteOwnStatuses,
  noteRelationships,
  pruneLedger,
  sortPeople,
} from './lite-people';
import { featureFlag } from '../app/feature-flags';
import { LiteAnalyticsComponent } from './lite-analytics.component';
import { LiteObservabilityComponent } from './lite-observability.component';
import { LiteWriteComponent } from './lite-write.component';

const FILTER_LABELS: Record<LiteFilter, string> = {
  posts: 'Posts',
  storms: 'Storms',
  shorts: 'Short text',
  replies: 'Discussions',
  questions: 'Questions',
  media: 'Pictures',
  links: 'Links',
  software: 'Software',
  news: 'News',
  boosts: 'Boosts',
};

const PEOPLE_VIEW_FILTERS: readonly LiteFilter[] = [
  'posts',
  'storms',
  'shorts',
  'replies',
  'media',
  'links',
  'boosts',
];
const CONTENT_VIEW_FILTERS: readonly LiteFilter[] = ['media', 'links', 'software', 'news'];

@Component({
  selector: 'app-lite-root',
  imports: [
    CommonModule,
    FormsModule,
    LiteAnalyticsComponent,
    LiteObservabilityComponent,
    LiteWriteComponent,
  ],
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
  readonly filter = signal<LiteFilter>('posts');
  readonly peopleFilter = signal<LitePeopleFilter>('all');
  readonly forumFilter = signal<LiteForumFilter>('all');
  readonly forumHashtags = signal<ReadonlySet<string>>(new Set());
  readonly ledger = signal<PeopleLedger>({});
  readonly selectedAccount = signal<LiteAccount | null>(null);
  readonly loading = signal(false);
  readonly connecting = signal(false);
  readonly sampleMode = signal(false);
  readonly error = signal<string | null>(null);
  readonly callsUsed = signal(0);

  // Thread view: anchor post plus its fetched context, overlaid on the feed.
  readonly threadAnchor = signal<LiteStatus | null>(null);
  readonly threadContext = signal<LiteContext | null>(null);
  readonly threadLoading = signal(false);

  instance = '';

  readonly filterLabels = FILTER_LABELS;
  readonly forumFilterLabels = FORUM_FILTER_LABELS;
  readonly blogRollDropdown = featureFlag('blogRollDropdown');
  readonly heavyUrl = localHeavyUrl();
  readonly connected = computed(() => this.sampleMode() || this.connection() !== null);
  readonly filterLabel = computed(() => FILTER_LABELS[this.filter()]);
  readonly viewFilters = computed(() =>
    this.page() === 'content' ? CONTENT_VIEW_FILTERS : PEOPLE_VIEW_FILTERS,
  );
  readonly visibleStatuses = computed(() => {
    return filterLiteStatuses(this.statuses(), this.filter());
  });
  readonly filterCounts = computed(() => countLiteFilters(this.statuses()));
  readonly peopleFilterEntries = Object.entries(PEOPLE_FILTER_LABELS) as [
    LitePeopleFilter,
    string,
  ][];
  readonly forumFilterEntries = Object.entries(FORUM_FILTER_LABELS) as [LiteForumFilter, string][];
  readonly peopleFilterCounts = computed(() =>
    countPeopleFilters(this.following(), this.ledger(), this.account()?.id ?? null),
  );
  readonly followingIds = computed(
    () => new Set(this.following().map((person) => person.id)) as ReadonlySet<string>,
  );
  readonly threads = computed(() => buildLiteThreads(this.statuses()));
  readonly visibleThreads = computed(() =>
    filterLiteThreads(
      this.threads(),
      this.forumFilter(),
      this.followingIds(),
      this.account()?.id ?? null,
      this.forumHashtags(),
    ),
  );
  readonly forumFilterCounts = computed(() =>
    countLiteThreadFilters(this.threads(), this.followingIds(), this.account()?.id ?? null),
  );
  readonly forumFacets = computed(() => threadHashtagFacets(this.threads()).slice(0, 12));
  readonly visiblePeople = computed(() => {
    const filter = this.peopleFilter();
    const ledger = this.ledger();
    const people = this.following().filter((person) =>
      matchesPeopleFilter(filter, person, ledger[person.id]),
    );
    if (filter === 'readers') {
      // Readers drop the "people I follow" gate, matching the server filter:
      // anyone who boosted me belongs here even if I never followed back.
      const known = new Set(this.following().map((person) => person.id));
      known.add(this.account()?.id ?? '');
      for (const evidence of Object.values(ledger)) {
        if (known.has(evidence.accountId) || !evidence.snapshot) continue;
        if (matchesPeopleFilter('readers', evidence.snapshot, evidence)) {
          people.push(evidence.snapshot);
        }
      }
    }
    return sortPeople(filter, people, ledger);
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
    this.filter.set('posts');
    this.peopleFilter.set('all');
    this.ledger.set(sampleLedger());
    this.selectedAccount.set(sampleAccount);
    this.callsUsed.set(0);
    this.error.set(null);
  }

  async navigate(page: LitePage): Promise<void> {
    this.page.set(page);
    this.closeThread();
    if (page === 'write' || page === 'analytics' || page === 'observability') return;
    if (page === 'people') {
      this.filter.set('posts');
      await this.loadAccount(this.selectedAccount() ?? this.account());
      return;
    }
    if (page === 'content') this.filter.set('media');
    await this.loadNetwork();
  }

  setFilter(filter: LiteFilter): void {
    this.filter.set(filter);
    this.closeThread();
  }

  setPeopleFilter(filter: LitePeopleFilter): void {
    this.peopleFilter.set(filter);
  }

  setForumFilter(filter: LiteForumFilter): void {
    this.forumFilter.set(filter);
    this.closeThread();
  }

  toggleForumHashtag(tag: string): void {
    const next = new Set(this.forumHashtags());
    if (next.has(tag)) next.delete(tag);
    else next.add(tag);
    this.forumHashtags.set(next);
    this.closeThread();
  }

  async selectFollowing(account: LiteAccount): Promise<void> {
    this.selectedAccount.set(account);
    this.page.set('people');
    this.filter.set('posts');
    this.closeThread();
    await this.loadAccount(account);
  }

  /**
   * Open the full discussion for a status: one context call returns the
   * ancestors up to the root and every descendant. In sample mode the
   * context is assembled from the loaded window instead.
   */
  async openThread(status: LiteStatus): Promise<void> {
    const anchor = status.reblog ?? status;
    this.threadAnchor.set(anchor);
    if (this.sampleMode()) {
      this.threadContext.set(sampleContext(anchor, this.statuses()));
      return;
    }
    const connection = this.connection();
    if (!connection) return;
    this.threadLoading.set(true);
    this.error.set(null);
    const budget = new LiteRequestBudget();
    try {
      this.threadContext.set(await this.mastodon.context(connection, anchor.id, budget));
    } catch (error: unknown) {
      this.error.set(errorMessage(error));
    } finally {
      this.callsUsed.set(budget.callsUsed);
      this.threadLoading.set(false);
    }
  }

  async openThreadRoot(thread: LiteThread): Promise<void> {
    // Anchor on the root when we have it; a partial thread anchors on its
    // earliest known reply, whose ancestors the context call fills in.
    await this.openThread(thread.root ?? thread.replies[0]);
  }

  closeThread(): void {
    this.threadAnchor.set(null);
    this.threadContext.set(null);
    this.threadLoading.set(false);
  }

  /** Re-run evidence gathering on demand with a fresh request budget. */
  async reclassify(): Promise<void> {
    const connection = this.connection();
    if (!connection || this.sampleMode()) return;
    this.loading.set(true);
    this.error.set(null);
    const budget = new LiteRequestBudget();
    try {
      await this.gatherPeopleEvidence(connection, budget);
      this.callsUsed.set(budget.callsUsed);
    } finally {
      this.loading.set(false);
    }
  }

  async refresh(): Promise<void> {
    this.closeThread();
    if (this.page() === 'content' || this.page() === 'forums') {
      await this.loadNetwork();
    } else if (this.selectedAccount()) {
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
      this.closeThread();
      this.loading.set(false);
    }
  }

  displayStatus(status: LiteStatus): LiteStatus {
    return status.reblog ?? status;
  }

  hasThread(status: LiteStatus): boolean {
    const post = status.reblog ?? status;
    return post.in_reply_to_id !== null || post.replies_count > 0;
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

  threadRepliers(thread: LiteThread): LiteAccount[] {
    const seen = new Set<string>();
    const repliers: LiteAccount[] = [];
    for (const reply of thread.replies) {
      if (seen.has(reply.account.id)) continue;
      seen.add(reply.account.id);
      repliers.push(reply.account);
    }
    return repliers.slice(0, 5);
  }

  private async loadInitial(): Promise<void> {
    const connection = this.connection();
    if (!connection) return;
    this.loading.set(true);
    this.error.set(null);
    const budget = new LiteRequestBudget();
    try {
      const cursor = this.storage.readCache<string | null>(connection, 'following-cursor');
      const [statuses, followingResult] = await Promise.all([
        this.mastodon.accountStatuses(connection, connection.account.id, budget),
        this.mastodon.following(connection, budget, cursor ?? null),
      ]);
      this.statuses.set(statuses.slice(0, LITE_LIMITS.maxCachedOwnStatuses));
      this.selectedAccount.set(connection.account);
      // Merge fresh pages over what earlier sessions collected: the crawl
      // cursor walks deeper into a big following list a couple of pages per
      // visit, so coverage grows without ever loading everyone at once.
      const cached = this.storage.readCache<LiteAccount[]>(connection, 'following') ?? [];
      this.following.set(
        mergeAccounts(followingResult.accounts, cached).slice(0, LITE_LIMITS.maxCachedFollowing),
      );
      this.storage.writeCache(connection, 'own-statuses', this.statuses());
      this.storage.writeCache(connection, 'following', this.following());
      this.storage.writeCache(connection, 'following-cursor', followingResult.next);
      await this.gatherPeopleEvidence(connection, budget);
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

  private async loadNetwork(): Promise<void> {
    if (this.sampleMode()) {
      this.statuses.set(sampleStatuses);
      return;
    }
    const connection = this.connection();
    if (!connection) return;
    await this.runOperation((budget) => this.mastodon.home(connection, budget));
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
      if (connection) {
        this.storage.writeCache(connection, 'last-statuses', this.statuses());
        this.absorbObservedStatuses(connection, this.statuses());
      }
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
    const ledger = this.storage.readCache<PeopleLedger>(connection, 'people-ledger');
    if (ownStatuses) {
      this.statuses.set(ownStatuses.slice(0, LITE_LIMITS.maxCachedOwnStatuses));
      this.selectedAccount.set(connection.account);
    }
    if (following) this.following.set(following.slice(0, LITE_LIMITS.maxCachedFollowing));
    if (ledger) this.ledger.set(ledger);
  }

  /**
   * Build up the blog roll evidence ledger from a handful of extra API calls:
   * relationships (mutuals) and recent notifications (readers, top friends,
   * chatty). Best effort — a partial ledger is kept when the request budget
   * or the network gives out, and now-and-forever facts persist across
   * sessions in local storage.
   */
  private async gatherPeopleEvidence(
    connection: LiteConnection,
    budget: LiteRequestBudget,
  ): Promise<void> {
    const ledger: PeopleLedger = {
      ...(this.storage.readCache<PeopleLedger>(connection, 'people-ledger') ?? {}),
    };
    for (const person of this.following()) noteAccount(ledger, person);
    noteOwnStatuses(ledger, this.statuses(), connection.account.id);
    try {
      if (budget.remaining >= LITE_LIMITS.notificationPages) {
        noteNotifications(ledger, await this.mastodon.notifications(connection, budget));
      }
      const ids = this.following().map((person) => person.id);
      const chunksNeeded = Math.ceil(ids.length / LITE_LIMITS.relationshipChunk);
      if (ids.length > 0 && budget.remaining >= chunksNeeded) {
        noteRelationships(ledger, await this.mastodon.relationships(connection, ids, budget));
      }
    } catch {
      // Keep whatever evidence was gathered before the failure.
    }
    pruneLedger(ledger, new Set(this.following().map((person) => person.id)));
    this.ledger.set(ledger);
    this.storage.writeCache(connection, 'people-ledger', ledger);
  }

  private absorbObservedStatuses(connection: LiteConnection, statuses: LiteStatus[]): void {
    const ledger = { ...this.ledger() };
    noteObservedStatuses(ledger, statuses);
    noteOwnStatuses(ledger, statuses, connection.account.id);
    this.ledger.set(ledger);
    try {
      this.storage.writeCache(connection, 'people-ledger', ledger);
    } catch {
      // Storage quota — the in-memory ledger still works for this session.
    }
  }
}

function mergeAccounts(fresh: LiteAccount[], cached: LiteAccount[]): LiteAccount[] {
  const merged = [...fresh];
  const seen = new Set(fresh.map((account) => account.id));
  for (const account of cached) {
    if (seen.has(account.id)) continue;
    seen.add(account.id);
    merged.push(account);
  }
  return merged;
}

/** Assemble a thread context from the loaded window (sample mode only). */
function sampleContext(anchor: LiteStatus, statuses: LiteStatus[]): LiteContext {
  const byId = new Map(statuses.map((status) => [status.id, status]));
  const ancestors: LiteStatus[] = [];
  let cursor = anchor;
  while (cursor.in_reply_to_id) {
    const parent = byId.get(cursor.in_reply_to_id);
    if (!parent) break;
    ancestors.unshift(parent);
    cursor = parent;
  }
  const descendants: LiteStatus[] = [];
  const queue = [anchor.id];
  while (queue.length > 0) {
    const parentId = queue.shift();
    for (const status of statuses) {
      if (status.in_reply_to_id === parentId) {
        descendants.push(status);
        queue.push(status.id);
      }
    }
  }
  return { ancestors, descendants };
}

function localHeavyUrl(): string | null {
  const host = location.hostname;
  if (host !== 'localhost' && host !== '127.0.0.1') return null;
  // Assembled at runtime on purpose: CI fails the Lite build if the bundle
  // contains a literal backend URL.
  return `http://${host}:8100/`;
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
