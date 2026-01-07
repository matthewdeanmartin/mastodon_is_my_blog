// app.component.ts
import {Component, OnInit} from '@angular/core';
import {CommonModule} from '@angular/common';
import {RouterLink, RouterOutlet, Router, ActivatedRoute} from '@angular/router';
import {ApiService} from './api.service';
import {filter} from 'rxjs/operators';

interface SidebarCounts {
  storms: number;
  news: number;
  software: number;
  pictures: number;
  videos: number;
  discussions: number;
  links: number;
  questions: number;
  everyone: number;
}

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, RouterOutlet, RouterLink],
  templateUrl: './app.component.html',
})
export class AppComponent implements OnInit {
  currentFilter: string = 'all';
  currentUser: string | null = null;
  blogRoll: any[] = [];
  mainUser: any = null; // Store the authenticated user's info
  activeUserInfo: any = null; // Store the currently viewed user's info
  serverDown: boolean = false;
  recentlyViewed: Set<string> = new Set();
  counts: SidebarCounts = {
    storms: 0,
    news: 0,
    software: 0,
    pictures: 0,
    videos: 0,
    discussions: 0,
    links: 0,
    questions: 0,
    everyone: 0
  };

  constructor(
    private api: ApiService,
    private router: Router,
    private route: ActivatedRoute,
  ) {
  }

  ngOnInit(): void {
    // Subscribe to server status
    this.api.serverDown$.subscribe((isDown) => {
      this.serverDown = isDown;
    });

    // 1. Fetch Blog Roll
    this.api.getBlogRoll().subscribe((accounts) => {
      this.blogRoll = accounts;
    });

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
      this.currentFilter = params['filter'] || 'all';

      // Track recently viewed accounts
      if (this.currentUser) {
        this.recentlyViewed.add(this.currentUser);
      }

      // Update active user info when user param changes
      if (this.currentUser) {
        this.api.getAccountInfo(this.currentUser).subscribe({
          next: (account) => {
            this.activeUserInfo = account;
            this.refreshCounts(); // Refresh counts when user changes
          },
          error: () => {
            this.activeUserInfo = null;
            this.refreshCounts();
          },
        });
      } else {
        // No user param means we're viewing the main user
        this.activeUserInfo = this.mainUser;
        this.refreshCounts();
      }
    });
  }

  setFilter(filter: string): void {
    this.currentFilter = filter;
    // Use 'merge' to preserve the 'user' param if it exists
    this.router.navigate(['/'], {
      queryParams: {filter: filter},
      queryParamsHandling: 'merge',
    });
  }

  viewMainUser(): void {
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

    // Navigate to next user
    this.router.navigate(['/'], {
      queryParams: {user: nextUser.acct, filter: this.currentFilter},
    });

    // Scroll to top
    window.scrollTo({top: 0, behavior: 'smooth'});
  }

  isViewingMainUser(): boolean {
    return !this.currentUser;
  }

  refreshCounts(): void {
    this.api.getCounts(this.currentUser || '').subscribe({
      next: (c) => {
        this.counts = {
          storms: Number(c.storms || 0),
          news: Number(c.news || 0),
          software: Number(c.software || 0),
          pictures: Number(c.pictures || 0),
          videos: Number(c.videos || 0),
          discussions: Number(c.discussions || 0),
          links: Number(c.links || 0),
          questions: Number(c.questions || 0),
          everyone: Number(c.everyone || 0),
        };
      },
      error: () => {
        // If counts fail, keep UI stable.
      },
    });
  }

  isRecentlyViewed(acct: string): boolean {
    return this.recentlyViewed.has(acct);
  }

  isActiveUser(acct: string): boolean {
    return this.currentUser === acct;
  }
}
