// src/app/app.component.ts
import {Component, OnInit} from '@angular/core';
import {CommonModule} from '@angular/common';
import {RouterLink, RouterOutlet, Router, ActivatedRoute} from '@angular/router';
import {ApiService} from './api.service';
import {filter} from 'rxjs/operators';

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
export class AppComponent implements OnInit {
  currentFilter: string = 'storms';
  currentBlogFilter: string = 'all';

  // Identities State
  identities: any[] = [];
  currentMetaId: string | null = null;

  // Navigation State
  currentUser: string | null = null;
  viewingEveryone: boolean = false;

  blogRoll: any[] = [];
  mainUser: any = null; // Store the authenticated user's info
  activeUserInfo: any = null; // Store the currently viewed user's info
  serverDown: boolean = false;
  recentlyViewed: Set<string> = new Set();

  counts: SidebarCounts = {
    storms: 0,
    shorts: 0,
    news: 0,
    software: 0,
    pictures: 0,
    videos: 0,
    discussions: 0,
    links: 0,
    questions: 0,
    everyone: 0,
    reposts: 0
  };

  constructor(
    private api: ApiService,
    private router: Router,
    private route: ActivatedRoute,
  ) {
  }

  ngOnInit(): void {
    this.currentMetaId = this.api.getMetaAccountId();

    // Subscribe to server status
    this.api.serverDown$.subscribe((isDown) => {
      // this.serverDown = isDown;
    });

    // 1. Fetch Identities (Top Header) - Scoped to Meta Account
    this.api.getIdentities().subscribe({
      next: (ids) => {
        this.identities = ids;
      },
      error: (e) => console.log('Could not fetch identities', e)
    });

    // 1. Fetch Initial Blog Roll
    this.loadBlogRoll();

    // 2. Get Main User Info
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

    // 3. Listen to query param changes to update active user display
    this.route.queryParams.subscribe((params) => {
      this.currentUser = params['user'] || null;
      this.currentFilter = params['filter'] || 'storms';
      this.viewingEveryone = params['user'] === 'everyone';

      // Check for blog filter in URL (optional, but good for linking)
      // If we want to persist blog filter in URL, we'd read it here.
      // For now, let's keep it simple or read it if present.
      if (params['blog_filter'] && params['blog_filter'] !== this.currentBlogFilter) {
          this.currentBlogFilter = params['blog_filter'];
          this.loadBlogRoll();
      }

      // Track recently viewed accounts
      if (this.currentUser && this.currentUser !== 'everyone') {
        this.recentlyViewed.add(this.currentUser);
        this.fetchActiveUserInfo(this.currentUser);
      } else {
        // Main user or Everyone view
        this.activeUserInfo = this.currentUser === 'everyone' ? null : this.mainUser;
        this.refreshCounts();
      }
    });
  }

  // Updated to handle 404s by attempting to sync
  fetchActiveUserInfo(acct: string, retry: boolean = true) {
    this.api.getAccountInfo(acct).subscribe({
      next: (account) => {
        this.activeUserInfo = account;
        this.refreshCounts();
      },
      error: () => {
        if (retry) {
          console.log(`User ${acct} not found in cache. Attempting sync...`);
          // If we fail to get info, try syncing the account once
          this.api.syncAccount(acct).subscribe({
            next: () => {
              // If sync succeeds, try fetching info again (without retry this time)
              this.fetchActiveUserInfo(acct, false);
            },
            error: (err) => {
              console.error(`Failed to sync user ${acct}`, err);
              this.activeUserInfo = null;
              this.refreshCounts();
            }
          });
        } else {
          // If we already retried and failed, give up
          this.activeUserInfo = null;
          this.refreshCounts();
        }
      },
    });
  }


  loadBlogRoll(): void {
    this.api.getBlogRoll(this.currentBlogFilter).subscribe((accounts) => {
      this.blogRoll = accounts;
    });
  }

  // --- Identity Switching ---

  selectIdentity(acct: string) {
    // Navigate to root with this user selected
    // Note: If acct is the same as mainUser, we might want to clear params?
    // For now, explicit selection is safer.
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

    // Check if user clicked cancel (null) or didn't change anything
    if (newId !== null && newId !== current) {
      if (newId.trim() === '') {
        this.api.logout(); // Clear to default
      } else {
        // 1. Manually set localStorage so the interceptor picks up the NEW id
        localStorage.setItem('meta_account_id', newId);

        // 2. Check status BEFORE forcing a sync
        this.api.getAdminStatus().subscribe({
          next: (status) => {
            // If connected but MISSING user data, we must sync.
            if (status.connected && !status.current_user) {
              console.log('New identity connected but empty. Syncing...');
              this.api.triggerSync(true).subscribe({
                next: () => window.location.reload(),
                error: () => window.location.reload()
              });
            } else {
              // If not connected (needs auth) or already has data, just reload.
              window.location.reload();
            }
          },
          error: (err) => {
            console.error('Sync failed during switch', err);
            // Reload anyway so the user is at least in the new context
            window.location.reload();
          }
        });
      }
    }
  }

  // --- Navigation Actions ---

  setFilter(filter: string): void {
    this.currentFilter = filter;
    // Keep 'everyone' status if it's active, otherwise keep user
    this.router.navigate(['/'], {
      queryParams: {filter: filter},
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
    this.viewingEveryone = true;
    this.currentFilter = 'storms';
    // Navigate with special 'everyone' user to signal server to show all users
    this.router.navigate(['/'], {
      queryParams: {user: 'everyone', filter: this.currentFilter},
    });
  }

  viewMainUser(): void {
    this.viewingEveryone = false;
    // Clear the user param to return to main user's view
    this.router.navigate(['/'], {
      queryParams: {filter: this.currentFilter},
    });
    // Scroll to top
    window.scrollTo({top: 0, behavior: 'smooth'});
  }

  viewNextBlogrollUser(): void {
    if (this.blogRoll.length === 0) return;

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
    if (this.blogRoll.length === 0) return;

    const currentIndex = this.blogRoll.findIndex(acc => acc.acct === currentAcct);
    if (currentIndex === -1) return;

    const nextIndex = (currentIndex + 1) % this.blogRoll.length;
    const userToPrefetch = this.blogRoll[nextIndex];

    if (userToPrefetch) {
      console.log(`Prefetching data for next user: ${userToPrefetch.acct}`);
      // Use syncAccount to ensure the backend actually fetches data from Mastodon
      // if it's missing. getPublicPosts only reads what is already cached.
      this.api.syncAccount(userToPrefetch.acct).subscribe({
        next: () => console.log(`Prefetch complete for ${userToPrefetch.acct}`),
        error: (err) => console.error(`Prefetch failed for ${userToPrefetch.acct}`, err)
      });
    }
  }

  // --- Helpers ---

  isViewingMainUser(): boolean {
    return !this.currentUser && !this.viewingEveryone;
  }

  refreshCounts(): void {
    // Determine which user to get counts for
    let userForCounts = this.currentUser;

    // If no current user (viewing main blog), use main user's acct
    if (!userForCounts && this.mainUser && !this.viewingEveryone) {
      userForCounts = this.mainUser.acct;
    }

    // Pass 'everyone' explicitly if viewing everyone, otherwise the specific user or undefined (for default)
    const effectiveUser = this.viewingEveryone ? 'everyone' : userForCounts;

    this.api.getCounts(effectiveUser || undefined).subscribe({
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

  isRecentlyViewed(acct: string): boolean {
    return this.recentlyViewed.has(acct);
  }

  isActiveUser(acct: string): boolean {
    return this.currentUser === acct;
  }

}
