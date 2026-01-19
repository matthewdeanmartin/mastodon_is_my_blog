// src/app/app.component.ts
import {Component, OnDestroy, OnInit} from '@angular/core';
import {CommonModule} from '@angular/common';
import {ActivatedRoute, Router, RouterLink, RouterOutlet} from '@angular/router';
import {ApiService} from './api.service';
import {distinctUntilChanged, map, shareReplay, switchMap, takeUntil, tap, catchError} from 'rxjs/operators';
import {of, Subject, combineLatest} from 'rxjs';

interface SidebarCounts {
  storms: number;
  shorts: number;
  news: number;
  software: number;
  pictures: number;
  videos: number;
  discussions: number;
  links: number;
  questions: number;
  everyone: number;
  reposts: number;
}

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, RouterOutlet, RouterLink],
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

  blogRoll: any[] = [];
  mainUser: any = null; // The "Profile" of the currently connected user
  activeUserInfo: any = null; // The "Profile" of the user we are viewing
  serverDown: boolean = false;
  recentlyViewed: Set<string> = new Set();

  counts: SidebarCounts = {
    storms: 0, shorts: 0, news: 0, software: 0, pictures: 0, videos: 0,
    discussions: 0, links: 0, questions: 0, everyone: 0, reposts: 0
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

    // Subscribe to server status
    this.api.serverDown$.subscribe((isDown) => {
      // this.serverDown = isDown;
    });

    // 1. Fetch Identities & Initialize Context
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

    // 2. React to Identity Changes
    this.api.identityId$.pipe(takeUntil(this.destroy$)).subscribe(id => {
        this.activeIdentityId = id;
        if (id) {
            this.loadBlogRoll();
            this.refreshCounts();
        }
    });

    // 3. Get Main User Info (For "My Blog" default view)
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

    // 5. Active User Info Pipeline
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

  // --- Context Identity Management ---

  setContextIdentity(id: number) {
      this.api.setIdentityId(id);
      // Optional: Navigate to home when context switches to avoid confusion?
      // this.router.navigate(['/']);
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
        this.counts = {
          storms: Number(c.storms || 0),
          shorts: Number(c.shorts || 0),
          news: Number(c.news || 0),
          software: Number(c.software || 0),
          pictures: Number(c.pictures || 0),
          videos: Number(c.videos || 0),
          discussions: Number(c.discussions || 0),
          links: Number(c.links || 0),
          questions: Number(c.questions || 0),
          everyone: Number(c.everyone || 0),
          reposts: Number(c.reposts || 0),
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
