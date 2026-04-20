// src/app/app.component.ts
import { Component, OnDestroy, OnInit, inject } from '@angular/core';

import {
  ActivatedRoute,
  NavigationEnd,
  Router,
  RouterLink,
  RouterLinkActive,
  RouterOutlet,
} from '@angular/router';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { ApiService } from './api.service';
import {
  debounceTime,
  distinctUntilChanged,
  map,
  shareReplay,
  switchMap,
  takeUntil,
  catchError,
  filter,
} from 'rxjs/operators';
import { of, Subject, Subscription, combineLatest, interval } from 'rxjs';
import { AccountCatchupStatus, Identity, MastodonAccount } from './mastodon';

interface CountDetail {
  total: number;
  unseen: number;
}

interface SidebarCounts {
  storms: CountDetail;
  shorts: CountDetail;
  news: CountDetail;
  software: CountDetail;
  pictures: CountDetail;
  videos: CountDetail;
  discussions: CountDetail;
  messages: CountDetail;
  links: CountDetail;
  questions: CountDetail;
  everyone: CountDetail;
  reposts: CountDetail;
}

const emptyCount = () => ({ total: 0, unseen: 0 });

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, RouterLink, RouterLinkActive, CommonModule, FormsModule],
  templateUrl: './app.component.html',
})
export class AppComponent implements OnInit, OnDestroy {
  private api = inject(ApiService);
  private router = inject(Router);
  private route = inject(ActivatedRoute);

  private readonly destroy$ = new Subject<void>();
  currentFilter = 'storms';
  currentBlogFilter = 'top_friends';
  blogRollNameFilter = '';

  // Identities State
  identities: Identity[] = [];
  currentMetaId: string | null = null;
  activeIdentityId: number | null = null; // The ID of the identity currently providing context

  // Navigation State
  currentUser: string | null = null; // The acct string of the user being VIEWED
  viewingEveryone = false;
  currentPage: 'people' | 'content' | 'forum' | 'other' = 'people';

  blogRoll: MastodonAccount[] = [];

  get filteredBlogRoll(): MastodonAccount[] {
    const q = this.blogRollNameFilter.trim().toLowerCase();
    if (!q) return this.blogRoll;
    return this.blogRoll.filter(
      (a) =>
        a.acct.toLowerCase().includes(q) ||
        (a.display_name ?? '').toLowerCase().includes(q),
    );
  }
  mainUser: MastodonAccount | null = null; // The "Profile" of the currently connected user
  activeUserInfo: MastodonAccount | null = null; // The "Profile" of the user we are viewing
  activeUserCatchup: AccountCatchupStatus | null = null;
  activeUserCatchupError: string | null = null;
  serverDown = false;
  recentlyViewed: Set<string> = new Set<string>();
  private activeUserCatchupPollSub?: Subscription;

  // Inside AppComponent class
  counts: SidebarCounts = {
    storms: emptyCount(),
    shorts: emptyCount(),
    news: emptyCount(),
    software: emptyCount(),
    pictures: emptyCount(),
    videos: emptyCount(),
    discussions: emptyCount(),
    messages: emptyCount(),
    links: emptyCount(),
    questions: emptyCount(),
    everyone: emptyCount(),
    reposts: emptyCount(),
  };

  ngOnDestroy(): void {
    this.stopActiveUserCatchupPolling();
    this.destroy$.next();
    this.destroy$.complete();
  }

  ngOnInit(): void {
    this.currentMetaId = this.api.getMetaAccountId();

    // Track current page for conditional sidebar display
    this.router.events
      .pipe(
        filter((event) => event instanceof NavigationEnd),
        takeUntil(this.destroy$),
      )
      .subscribe(() => {
        const url = this.router.url;
        const path = url.split('?')[0];
        if (path.startsWith('/content')) {
          this.currentPage = 'content';
        } else if (path.startsWith('/forum')) {
          this.currentPage = 'forum';
        } else if (path === '/' || path === '') {
          this.currentPage = 'people';
        } else {
          // /p/:id, /write, /admin, /login — no sidebar
          this.currentPage = 'other';
        }
      });

    // Subscribe to server status
    this.api.serverDown$.subscribe(() => {
      // this.serverDown = isDown;
    });

    // Listen for data refreshes (syncs/writes) to keep counts consistent
    this.api.refreshNeeded$.pipe(takeUntil(this.destroy$)).subscribe(() => {
      this.refreshCounts();
      this.refreshActiveUserContext();
    });

    // Fetch Identities & Initialize Context
    this.api
      .getIdentities()
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (ids) => {
          this.identities = ids;

          // Auto-select identity if none selected or invalid
          const storedId = this.api.getStoredIdentityId();
          const validStored = storedId && ids.find((i) => i.id === storedId);

          if (validStored) {
            const identity = ids.find((i) => i.id === storedId)!;
            this.setContextIdentity(storedId!, identity.base_url);
          } else if (ids.length > 0) {
            this.setContextIdentity(ids[0].id, ids[0].base_url);
          }
        },
        error: (e: unknown) => console.log('Could not fetch identities', e),
      });

    // React to Identity Changes
    this.api.identityId$.pipe(takeUntil(this.destroy$)).subscribe((id) => {
      this.activeIdentityId = id;
      if (id) {
        this.loadBlogRoll();
      }
    });

    // Get Main User Info (For "My Blog" default view)
    this.api.getAdminStatus().subscribe((status) => {
      if (status.connected && status.current_user) {
        this.mainUser = status.current_user;
        // Set active user to main user by default
        if (!this.currentUser) {
          this.activeUserInfo = this.mainUser;
        }
        // this.refreshCounts();
      }
    });

    const selection$ = this.route.queryParams.pipe(
      map((params) => {
        const user = (params['user'] as string | undefined) ?? null;
        const filter = (params['filter'] as string | undefined) ?? 'storms';
        const blogFilter = (params['blog_filter'] as string | undefined) ?? this.currentBlogFilter;

        const scope =
          user === 'everyone'
            ? ({ kind: 'everyone' } as const)
            : user
              ? ({ kind: 'user', acct: user } as const)
              : ({ kind: 'main' } as const);

        return { scope, filter, blogFilter };
      }),
      distinctUntilChanged((a, b) => JSON.stringify(a) === JSON.stringify(b)),
      shareReplay(1),
    );

    selection$.pipe(takeUntil(this.destroy$)).subscribe((sel) => {
      this.currentFilter = sel.filter;
      if (sel.blogFilter !== this.currentBlogFilter) {
        this.currentBlogFilter = sel.blogFilter;
        this.loadBlogRoll();
      }

      this.viewingEveryone = sel.scope.kind === 'everyone';
      this.currentUser =
        sel.scope.kind === 'user'
          ? sel.scope.acct
          : sel.scope.kind === 'everyone'
            ? 'everyone'
            : null;

      if (sel.scope.kind === 'user') {
        this.recentlyViewed.add(sel.scope.acct);
        this.activeUserCatchup = null;
        this.activeUserCatchupError = null;
        this.stopActiveUserCatchupPolling();
      } else {
        this.activeUserCatchup = null;
        this.activeUserCatchupError = null;
        this.stopActiveUserCatchupPolling();
      }
    });

    // Active User Info Pipeline
    // Debounce rapid click-through in the blog roll so we don't stack
    // /api/accounts/{acct} + /api/posts/counts calls per intermediate user.
    combineLatest([selection$, this.api.identityId$])
      .pipe(
        takeUntil(this.destroy$),
        debounceTime(150),
        switchMap(([sel, identityId]) => {
          if (!identityId) return of(null);

          if (sel.scope.kind === 'everyone') {
            return of(null);
          }
          if (sel.scope.kind === 'main') {
            return of(this.mainUser);
          }

          // kind === 'user'
          const acct = sel.scope.acct;
          return this.fetchActiveUserInfo$(acct, identityId);
        }),
      )
      .subscribe((active) => {
        this.activeUserInfo = active;
        this.refreshCounts();
        if (this.currentUser && this.currentUser !== 'everyone' && this.activeIdentityId) {
          this.loadActiveUserCatchupStatus(this.currentUser, this.activeIdentityId);
        }
      });
  }

  // --- Helper Methods ---

  isPeoplePage(): boolean {
    return this.currentPage === 'people';
  }

  isOtherPage(): boolean {
    return this.currentPage === 'other';
  }

  setContextIdentity(id: number, baseUrl: string) {
    this.api.setIdentityId(id, baseUrl);
    const identity = this.identities.find((i) => i.id === id);
    this.router.navigate(['/'], {
      queryParams: { user: identity?.acct ?? null, filter: 'storms', blog_filter: 'top_friends' },
    });
  }

  // --- Data Fetching ---

  private fetchActiveUserInfo$(acct: string, identityId: number) {
    return this.api.getAccountInfo(acct, identityId).pipe(catchError(() => of(null)));
  }

  private refreshActiveUserContext(): void {
    if (!this.currentUser || this.currentUser === 'everyone' || !this.activeIdentityId) return;

    this.fetchActiveUserInfo$(this.currentUser, this.activeIdentityId).subscribe((active) => {
      this.activeUserInfo = active;
    });
    this.loadActiveUserCatchupStatus(this.currentUser, this.activeIdentityId);
  }

  loadBlogRoll(): void {
    if (!this.activeIdentityId) return;
    this.api.getBlogRoll(this.activeIdentityId, this.currentBlogFilter).subscribe((accounts) => {
      this.blogRoll = accounts;
    });
  }

  refreshCounts(): void {
    if (!this.activeIdentityId) return;

    let userForCounts = this.currentUser;

    if (!userForCounts && this.mainUser && !this.viewingEveryone) {
      userForCounts = this.mainUser.acct; // Default to filtering by self
    }

    // API expects "everyone" string if we want full feed
    const effectiveUser = this.viewingEveryone ? 'everyone' : userForCounts;

    this.api.getCounts(this.activeIdentityId, effectiveUser || undefined).subscribe({
      next: (response: unknown) => {
        const c = response as Record<string, { total?: number; unseen?: number }>;
        // Helper to extract nested counts safely
        const mapCount = (data?: { total?: number; unseen?: number }): CountDetail => ({
          total: Number(data?.total || 0),
          unseen: Number(data?.unseen || 0),
        });
        this.counts = {
          storms: mapCount(c['storms']),
          shorts: mapCount(c['shorts']),
          news: mapCount(c['news']),
          software: mapCount(c['software']),
          pictures: mapCount(c['pictures']),
          videos: mapCount(c['videos']),
          discussions: mapCount(c['discussions']),
          messages: mapCount(c['messages']),
          links: mapCount(c['links']),
          questions: mapCount(c['questions']),
          everyone: mapCount(c['everyone']),
          reposts: mapCount(c['reposts']),
        };
      },
      error: (e: unknown) => console.log(e),
    });
  }

  // --- Actions ---

  selectIdentity(acct: string) {
    // NOTE: This legacy method selected a user to VIEW.
    // We now prefer clicking the chip to set CONTEXT.
    // But if we want to "view this identity's blog" specifically:
    this.router.navigate(['/'], {
      queryParams: { user: acct, filter: 'storms' },
    });
  }

  /**
   * Updates the 'Meta Account' context.
   * In a real app, this would be a login screen.
   * For dev/testing, we prompt for the ID integer.
   */
  switchMetaAccount() {
    const current = this.api.getMetaAccountId() || '';
    const newId = prompt('Enter Meta Account ID (integer) to switch context:', current);

    if (newId !== null && newId !== current) {
      if (newId.trim() === '') {
        this.api.logout();
      } else {
        this.api.setMetaAccountId(newId);
        window.location.reload();
      }
    }
  }

  // --- Navigation Actions ---
  setFilter(filter: string): void {
    this.router.navigate(['/'], {
      queryParams: { filter },
      queryParamsHandling: 'merge',
    });
  }

  setBlogFilter(filter: string): void {
    this.currentBlogFilter = filter;
    this.loadBlogRoll();
    // Optional: Add to URL so refresh works
    this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { blog_filter: filter },
      queryParamsHandling: 'merge',
    });
  }

  viewEveryone(): void {
    this.router.navigate(['/'], {
      queryParams: { user: 'everyone', filter: 'storms' },
    });
  }

  viewMainUser(): void {
    const identity = this.identities.find((i) => i.id === this.activeIdentityId);
    this.router.navigate(['/'], {
      queryParams: { user: identity?.acct ?? null, filter: 'storms' },
    });
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  // Logic to jump to next blogroll user (requires context identity)
  viewNextBlogrollUser(): void {
    if (this.blogRoll.length === 0 || !this.activeIdentityId) return;

    // Find current index
    const currentIndex = this.currentUser
      ? this.blogRoll.findIndex((acc) => acc.acct === this.currentUser)
      : -1;

    // Get next index (wrap around to 0 if at end)
    const nextIndex = (currentIndex + 1) % this.blogRoll.length;
    const nextUser = this.blogRoll[nextIndex];

    // Navigate to next user
    this.router.navigate(['/'], {
      queryParams: { user: nextUser.acct, filter: this.currentFilter },
    });

    // Scroll to top
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  isViewingMainUser(): boolean {
    if (this.viewingEveryone) return false;
    const identity = this.identities.find((i) => i.id === this.activeIdentityId);
    return !!identity && this.currentUser === identity.acct;
  }

  isRecentlyViewed(acct: string): boolean {
    return this.recentlyViewed.has(acct);
  }

  isActiveUser(acct: string): boolean {
    return this.currentUser === acct;
  }

  activeUserProfileUrl(): string | null {
    return this.activeUserInfo?.url ?? null;
  }

  mainUserProfileUrl(): string | null {
    return this.mainUser?.url ?? null;
  }

  showPeopleCatchupControls(): boolean {
    return (
      this.isPeoplePage() &&
      !!this.currentUser &&
      this.currentUser !== 'everyone' &&
      !!this.activeUserInfo
    );
  }

  activeUserCacheMessage(): string {
    const cacheState = this.activeUserInfo?.cache_state;
    if (!cacheState) {
      return 'This page is showing cached data only.';
    }

    const filterLabel = this.currentFilterLabel();
    const cachedCount = this.currentFilterCount();
    const latest = cacheState.latest_cached_post_at
      ? new Date(cacheState.latest_cached_post_at).toLocaleDateString()
      : null;

    if (cacheState.stale_reason === 'no_cached_posts') {
      return `Showing cached data only. There are no cached posts for this account yet, and ${cachedCount} cached ${filterLabel} posts for the current filter.`;
    }

    if (cacheState.is_stale) {
      return `Showing ${cachedCount} cached ${filterLabel} posts. Cache looks stale; newest cached post is from ${latest ?? 'an older sync'}.`;
    }

    return `Showing ${cachedCount} cached ${filterLabel} posts. Newest cached post is from ${latest ?? 'a recent sync'}.`;
  }

  currentFilterLabel(): string {
    switch (this.currentFilter) {
      case 'storms':
      case 'all':
        return 'storms';
      case 'shorts':
        return 'shorts';
      case 'news':
        return 'news posts';
      case 'software':
        return 'software posts';
      case 'pictures':
        return 'pictures';
      case 'videos':
        return 'videos';
      case 'discussions':
        return 'discussions';
      case 'messages':
        return 'messages';
      case 'links':
        return 'links';
      case 'questions':
        return 'questions';
      case 'reposts':
        return 'reposts';
      default:
        return 'posts';
    }
  }

  currentFilterCount(): number {
    switch (this.currentFilter) {
      case 'storms':
      case 'all':
        return this.counts.storms.total;
      case 'shorts':
        return this.counts.shorts.total;
      case 'news':
        return this.counts.news.total;
      case 'software':
        return this.counts.software.total;
      case 'pictures':
        return this.counts.pictures.total;
      case 'videos':
        return this.counts.videos.total;
      case 'discussions':
        return this.counts.discussions.total;
      case 'messages':
        return this.counts.messages.total;
      case 'links':
        return this.counts.links.total;
      case 'questions':
        return this.counts.questions.total;
      case 'reposts':
        return this.counts.reposts.total;
      default:
        return 0;
    }
  }

  startActiveUserCatchup(mode: 'recent' | 'deep'): void {
    if (!this.currentUser || !this.activeIdentityId) return;

    this.activeUserCatchupError = null;
    this.api.startAccountCatchup(this.currentUser, this.activeIdentityId, mode).subscribe({
      next: (status) => {
        this.activeUserCatchup = status;
        if (status.running) {
          this.startActiveUserCatchupPolling(this.currentUser!, this.activeIdentityId!);
        }
      },
      error: (err) => {
        this.activeUserCatchupError = err?.error?.detail ?? 'Failed to start catch-up';
      },
    });
  }

  stopActiveUserCatchup(): void {
    if (!this.currentUser || !this.activeIdentityId) return;

    this.api.cancelAccountCatchup(this.currentUser, this.activeIdentityId).subscribe({
      next: () => this.loadActiveUserCatchupStatus(this.currentUser!, this.activeIdentityId!),
      error: (err) => {
        this.activeUserCatchupError = err?.error?.detail ?? 'Failed to stop catch-up';
      },
    });
  }

  private loadActiveUserCatchupStatus(acct: string, identityId: number): void {
    this.api.getAccountCatchupStatus(acct, identityId).subscribe({
      next: (status) => {
        if (this.currentUser !== acct) return;
        this.activeUserCatchup = status;
        this.activeUserCatchupError = status.error;
        if (status.running) {
          this.startActiveUserCatchupPolling(acct, identityId);
        } else {
          this.stopActiveUserCatchupPolling();
        }
      },
      error: (err) => {
        if (this.currentUser !== acct) return;
        if (err?.status === 404) {
          this.activeUserCatchup = null;
          this.activeUserCatchupError = null;
        } else {
          this.activeUserCatchupError = err?.error?.detail ?? 'Failed to load catch-up status';
        }
      },
    });
  }

  private startActiveUserCatchupPolling(acct: string, identityId: number): void {
    this.stopActiveUserCatchupPolling();
    this.activeUserCatchupPollSub = interval(2000)
      .pipe(switchMap(() => this.api.getAccountCatchupStatus(acct, identityId)))
      .subscribe({
        next: (status) => {
          if (this.currentUser !== acct) {
            this.stopActiveUserCatchupPolling();
            return;
          }

          this.activeUserCatchup = status;
          this.activeUserCatchupError = status.error;
          if (!status.running) {
            this.stopActiveUserCatchupPolling();
            this.api.refreshNeeded$.next();
          }
        },
        error: () => this.stopActiveUserCatchupPolling(),
      });
  }

  private stopActiveUserCatchupPolling(): void {
    this.activeUserCatchupPollSub?.unsubscribe();
    this.activeUserCatchupPollSub = undefined;
  }
}
