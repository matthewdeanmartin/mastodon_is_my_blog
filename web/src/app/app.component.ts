// src/app/app.component.ts
import {Component, OnDestroy, OnInit} from '@angular/core';
import {CommonModule} from '@angular/common';
import {ActivatedRoute, NavigationEnd, Router, RouterLink,RouterLinkActive, RouterOutlet} from '@angular/router';

import {ApiService} from './api.service';
import {distinctUntilChanged, map, shareReplay, switchMap, takeUntil, tap, catchError, filter} from 'rxjs/operators';
import {of, Subject, combineLatest} from 'rxjs';

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
  links: CountDetail;
  questions: CountDetail;
  everyone: CountDetail;
  reposts: CountDetail;
}

const emptyCount = () => ({ total: 0, unseen: 0 });

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, RouterOutlet, RouterLink, RouterLinkActive],
  templateUrl: './app.component.html',
})
export class AppComponent implements OnInit, OnDestroy {
  private readonly destroy$ = new Subject<void>();
  currentFilter: string = 'storms';
  currentBlogFilter: string = 'all';

  // Identities State
  identities: any[] = [];
  currentMetaId: string | null = null;
  activeIdentityId: number | null = null; // The ID of the identity currently providing context

  // Navigation State
  currentUser: string | null = null; // The acct string of the user being VIEWED
  viewingEveryone: boolean = false;
  currentPage: 'people' | 'content' | 'forum' = 'people';

  blogRoll: any[] = [];
  mainUser: any = null; // The "Profile" of the currently connected user
  activeUserInfo: any = null; // The "Profile" of the user we are viewing
  serverDown: boolean = false;
  recentlyViewed: Set<string> = new Set();



  // Inside AppComponent class
  counts: SidebarCounts = {
    storms: emptyCount(), shorts: emptyCount(), news: emptyCount(),
    software: emptyCount(), pictures: emptyCount(), videos: emptyCount(),
    discussions: emptyCount(), links: emptyCount(), questions: emptyCount(),
    everyone: emptyCount(), reposts: emptyCount()
  };

  constructor(
    private api: ApiService,
    private router: Router,
    private route: ActivatedRoute,
  ) {
  }


  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  ngOnInit(): void {
    this.currentMetaId = this.api.getMetaAccountId();

    // Track current page for conditional sidebar display
    this.router.events.pipe(
      filter(event => event instanceof NavigationEnd),
      takeUntil(this.destroy$)
    ).subscribe(() => {
      const url = this.router.url;
      if (url.startsWith('/content')) {
        this.currentPage = 'content';
      } else if (url.startsWith('/forum')) {
        this.currentPage = 'forum';
      } else {
        this.currentPage = 'people';
      }
    });

    // Subscribe to server status
    this.api.serverDown$.subscribe((isDown) => {
      // this.serverDown = isDown;
    });

    // Listen for data refreshes (syncs/writes) to keep counts consistent
    this.api.refreshNeeded$.pipe(takeUntil(this.destroy$)).subscribe(() => {
      this.refreshCounts();
    });

    // Fetch Identities & Initialize Context
    this.api.getIdentities().pipe(takeUntil(this.destroy$)).subscribe({
      next: (ids) => {
        this.identities = ids;

        // Auto-select identity if none selected or invalid
        const storedId = this.api.getStoredIdentityId();
        const validStored = storedId && ids.find(i => i.id === storedId);

        if (validStored) {
          this.setContextIdentity(storedId!);
        } else if (ids.length > 0) {
          this.setContextIdentity(ids[0].id);
        }
      },
      error: (e) => console.log('Could not fetch identities', e)
    });

    // React to Identity Changes
    this.api.identityId$.pipe(takeUntil(this.destroy$)).subscribe(id => {
      this.activeIdentityId = id;
      if (id) {
        this.loadBlogRoll();
        this.refreshCounts();
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
      map(params => {
        const user = (params['user'] as string | undefined) ?? null;
        const filter = (params['filter'] as string | undefined) ?? 'storms';
        const blogFilter = (params['blog_filter'] as string | undefined) ?? this.currentBlogFilter;

        const scope = user === 'everyone'
          ? ({kind: 'everyone'} as const)
          : user
            ? ({kind: 'user', acct: user} as const)
            : ({kind: 'main'} as const);

        return {scope, filter, blogFilter};
      }),
      distinctUntilChanged((a, b) =>
        JSON.stringify(a) === JSON.stringify(b)
      ),
      shareReplay(1)
    );

    selection$.pipe(takeUntil(this.destroy$)).subscribe(sel => {
      this.currentFilter = sel.filter;
      if (sel.blogFilter !== this.currentBlogFilter) {
        this.currentBlogFilter = sel.blogFilter;
        this.loadBlogRoll();
      }

      this.viewingEveryone = sel.scope.kind === 'everyone';
      this.currentUser = sel.scope.kind === 'user' ? sel.scope.acct : (sel.scope.kind === 'everyone' ? 'everyone' : null);

      if (sel.scope.kind === 'user') {
        this.recentlyViewed.add(sel.scope.acct);
      }
    });

    // Active User Info Pipeline
    combineLatest([selection$, this.api.identityId$]).pipe(
      takeUntil(this.destroy$),
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
      })
    ).subscribe(active => {
      this.activeUserInfo = active;
      this.refreshCounts();
    });
  }

  // --- Helper Methods ---

  isPeoplePage(): boolean {
    return this.currentPage === 'people';
  }

  setContextIdentity(id: number) {
    this.api.setIdentityId(id);
    // UPDATED: Navigate to home (My Blog/Storms) when context switches to ensure clean state
    this.router.navigate(['/'], {
      queryParams: {user: null, filter: 'storms'}
    });
  }

  // --- Data Fetching ---

  private fetchActiveUserInfo$(acct: string, identityId: number) {
    return this.api.getAccountInfo(acct, identityId).pipe(
      catchError(() =>
        this.api.syncAccountDedup(acct, identityId).pipe(
          switchMap(() => this.api.getAccountInfo(acct, identityId)),
          catchError(() => of(null))
        )
      )
    );
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

      next: (c) => {
        // Helper to extract nested counts safely
        const mapCount = (data: any): CountDetail => ({
          total: Number(data?.total || 0),
          unseen: Number(data?.unseen || 0)
        });
        this.counts = {
          storms: mapCount(c.storms),
          shorts: mapCount(c.shorts),
          news: mapCount(c.news),
          software: mapCount(c.software),
          pictures: mapCount(c.pictures),
          videos: mapCount(c.videos),
          discussions: mapCount(c.discussions),
          links: mapCount(c.links),
          questions: mapCount(c.questions),
          everyone: mapCount(c.everyone),
          reposts: mapCount(c.reposts),
        };
      },
      error: (e) => console.log(e),
    });
  }

  // --- Actions ---

  selectIdentity(acct: string) {
    // NOTE: This legacy method selected a user to VIEW.
    // We now prefer clicking the chip to set CONTEXT.
    // But if we want to "view this identity's blog" specifically:
    this.router.navigate(['/'], {
      queryParams: {user: acct, filter: 'storms'}
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
      queryParams: {filter},
      queryParamsHandling: 'merge',
    });
  }

  setBlogFilter(filter: string): void {
    this.currentBlogFilter = filter;
    this.loadBlogRoll();
    // Optional: Add to URL so refresh works
    this.router.navigate([], {
      relativeTo: this.route,
      queryParams: {blog_filter: filter},
      queryParamsHandling: 'merge',
    });
  }

  viewEveryone(): void {
    this.router.navigate(['/'], {
      queryParams: {user: 'everyone', filter: 'storms'},
    });
  }


  viewMainUser(): void {
    this.router.navigate(['/'], {
      queryParams: {user: null},
      queryParamsHandling: 'merge',
    });
    window.scrollTo({top: 0, behavior: 'smooth'});
  }

  // Logic to jump to next blogroll user (requires context identity)
  viewNextBlogrollUser(): void {
    if (this.blogRoll.length === 0 || !this.activeIdentityId) return;

    // Find current index
    const currentIndex = this.currentUser
      ? this.blogRoll.findIndex(acc => acc.acct === this.currentUser)
      : -1;

    // Get next index (wrap around to 0 if at end)
    const nextIndex = (currentIndex + 1) % this.blogRoll.length;
    const nextUser = this.blogRoll[nextIndex];

    // Trigger prefetch for the user AFTER the one we are about to navigate to
    this.prefetchNextBlogrollUser(nextUser.acct);

    // Navigate to next user
    this.router.navigate(['/'], {
      queryParams: {user: nextUser.acct, filter: this.currentFilter},
    });

    // Scroll to top
    window.scrollTo({top: 0, behavior: 'smooth'});
  }

  /**
   * Finds the user immediately following the 'currentAcct' in the blogroll
   * and triggers a background sync to populate their posts.
   */
  prefetchNextBlogrollUser(currentAcct: string): void {
    if (this.blogRoll.length === 0 || !this.activeIdentityId) return;

    const currentIndex = this.blogRoll.findIndex(acc => acc.acct === currentAcct);
    if (currentIndex === -1) return;

    const nextIndex = (currentIndex + 1) % this.blogRoll.length;
    const userToPrefetch = this.blogRoll[nextIndex];

    if (userToPrefetch) {
      this.api.syncAccount(userToPrefetch.acct, this.activeIdentityId).subscribe({
        next: () => console.log(`Prefetch complete for ${userToPrefetch.acct}`),
        error: (err) => console.error(`Prefetch failed for ${userToPrefetch.acct}`, err)
      });
    }
  }

  isViewingMainUser(): boolean {
    return !this.currentUser && !this.viewingEveryone;
  }

  isRecentlyViewed(acct: string): boolean {
    return this.recentlyViewed.has(acct);
  }

  isActiveUser(acct: string): boolean {
    return this.currentUser === acct;
  }
}
