// web/src/app/feed.component.ts

import {Component, OnInit, OnDestroy, ElementRef, ViewChildren, QueryList, AfterViewInit} from '@angular/core';
import {ActivatedRoute, RouterLink} from '@angular/router';
import {ApiService} from './api.service';
import {CommonModule} from '@angular/common';
import {DomSanitizer} from '@angular/platform-browser';
import {LinkPreviewComponent} from './link.component';
import {LinkPreviewService} from './link.service';
import {combineLatest, fromEvent, Subscription} from 'rxjs';
import {debounceTime, filter} from 'rxjs/operators';
import {HttpErrorResponse} from '@angular/common/http';

@Component({
  selector: 'app-public-feed',
  standalone: true,
  imports: [CommonModule, RouterLink, LinkPreviewComponent],
  templateUrl: 'feed.component.html',
})
export class PublicFeedComponent implements OnInit, OnDestroy, AfterViewInit {
  @ViewChildren('postItem') postItems!: QueryList<ElementRef>;
  
  items: any[] = [];
  loading = true;
  isStormView = false;
  currentFilter = 'storms';
  currentUser: string | undefined;
  syncingUser = false;
  unreadCount = 0;

  currentIdentityId: number | null = null;
  seenPostIds = new Set<string>();
  
  private scrollSubscription?: Subscription;
  private observer?: IntersectionObserver;

  private pendingSeenPosts = new Set<string>();
  private batchTimer: number | null = null;
  private readonly BATCH_DELAY_MS = 5000;

  private hoverTimers = new Map<string, number>();
  private readonly HOVER_DELAY_MS = 500;

  private viewportTimers = new Map<string, number>();
  private readonly VIEWPORT_THRESHOLD_MS = 1500;

  private readonly isTouchDevice: boolean;

  constructor(
    private route: ActivatedRoute,
    private api: ApiService,
    private sanitizer: DomSanitizer,
    private linkPreviewService: LinkPreviewService,
  ) {
    this.isTouchDevice = typeof navigator !== 'undefined' && navigator.maxTouchPoints > 0;
  }

  ngOnInit(): void {
    // Combine Route Params with Identity State
    combineLatest([this.route.queryParams, this.api.identityId$])
      .subscribe(([params, identityId]) => {
          this.currentIdentityId = identityId;

          if (!identityId) {
              this.loading = true; // Wait for identity
              return;
          }

          const newFilter = params['filter'] || 'storms';
          const newUser = params['user'] || undefined; // "everyone" passes through as string here

          // Reload if parameters changed or just initialized
          if (newFilter !== this.currentFilter || newUser !== this.currentUser || identityId) {
              this.currentFilter = newFilter;
              this.currentUser = newUser;
              this.syncingUser = false;
              this.load(this.currentFilter, this.currentUser, identityId);
          }
      });
  }

  load(filter: string, user: string | undefined, identityId: number): void {
    this.loading = true;
    this.items = [];

    // Define the success handler to reuse
    const handleSuccess = (data: any[]) => {
      this.loading = false;
      // If we got an empty list for a specific user, try syncing ONCE to see if they exist remotely
      if (data.length === 0 && user && user !== 'everyone' && filter !== 'everyone' && !this.syncingUser) {
        this.attemptUserSync(user, identityId);
      } else {
        this.items = data;
        this.trackSeenPosts(data);
        this.updateUnreadCount();
      }
    };

    const handleError = (error: HttpErrorResponse) => {
      if (error.status === 404 && user && user !== 'everyone' && !this.syncingUser) {
          console.log(`Posts not found (404) for ${user}, attempting JIT sync...`);
          this.attemptUserSync(user, identityId);
      } else {
          console.error(`Error loading posts (Status: ${error.status}):`, error);
          this.loading = false;
      }
    };

    // If 'storms' (or legacy 'all'), use the Storms endpoint for the threaded view
    if (filter === 'storms' || filter === 'all') {
      this.isStormView = true;
      this.api.getStorms(identityId, user).subscribe({ next: handleSuccess, error: handleError });
    }
    // If 'shorts', use the new Shorts endpoint for flat view
    else if (filter === 'shorts') {
      this.isStormView = false;
      this.api.getShorts(identityId, user).subscribe({ next: handleSuccess, error: handleError });
    }
    else {
      // Otherwise use the standard flat list with the specific filter
      this.isStormView = false;
      this.api.getPublicPosts(identityId, filter, user).subscribe({ next: handleSuccess, error: handleError });
    }
  }

  attemptUserSync(acct: string, identityId: number): void {
    this.syncingUser = true;
    this.loading = true;

    // We only try this once per navigation to avoid loops
    this.api.syncAccount(acct, identityId).subscribe({
      next: (res) => {
        // Retry load exactly once
        this.load(this.currentFilter, acct, identityId);
      },
      error: (err) => {
        console.error('Failed to sync user', err);
        this.loading = false;
      },
    });
  }

  stripHtml(html: string) {
    return this.sanitizer.bypassSecurityTrustHtml(html);
    // return (html || '').replace(/<[^>]+>/g, '').trim();
  }

  getImages(post: any) {
    // Handle storm root vs regular post structure if needed,
    // but the API ensures 'media' or 'media_attachments' exists.
    const media = post.media_attachments || post.media || [];
    return media.filter((m: any) => m.type === 'image');
  }
  getQueryParams() {
    const params: any = { filter: this.currentFilter };
    if (this.currentUser) {
      params.user = this.currentUser;
    }
    return params;
  }

   getOriginalPostUrl(post: any): string {
    const acct = post.author_acct;
    if (!acct) return '#';

    const parts = acct.split('@');
    return `https://${parts[1] || 'mastodon.social'}/@${parts[0]}/${post.id}`;
  }

  getPostUrls(post: any): string[] {
    // Extract URLs from post content for link previews
    return this.linkPreviewService.extractUrls(post.content || '');
  }

  ngAfterViewInit(): void {
    this.setupScrollTracking();
  }

  ngOnDestroy(): void {
    this.scrollSubscription?.unsubscribe();
    this.observer?.disconnect();
    this.flushPendingPosts();
    this.clearAllTimers();
  }

  private clearAllTimers(): void {
    if (this.batchTimer !== null) {
      clearTimeout(this.batchTimer);
      this.batchTimer = null;
    }
    this.hoverTimers.forEach((timer) => clearTimeout(timer));
    this.hoverTimers.clear();
    this.viewportTimers.forEach((timer) => clearTimeout(timer));
    this.viewportTimers.clear();
  }

  private setupScrollTracking(): void {
    if (typeof IntersectionObserver === 'undefined') return;
    if (!this.isTouchDevice) return;

    this.observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          const postId = entry.target.getAttribute('data-post-id');
          if (!postId || this.seenPostIds.has(postId)) return;

          if (entry.isIntersecting) {
            this.startViewportTimer(postId);
          } else {
            this.cancelViewportTimer(postId);
          }
        });
      },
      { threshold: 0.5 }
    );

    this.postItems?.changes.subscribe(() => {
      this.observeNewItems();
    });
    this.observeNewItems();
  }

  private observeNewItems(): void {
    this.observer?.disconnect();
    this.postItems?.forEach((el) => {
      this.observer?.observe(el.nativeElement);
    });
  }

  onPostMouseEnter(postId: string): void {
    if (this.isTouchDevice || this.seenPostIds.has(postId)) return;

    if (this.hoverTimers.has(postId)) return;

    const timer = window.setTimeout(() => {
      this.hoverTimers.delete(postId);
      this.addToPendingSeen(postId);
    }, this.HOVER_DELAY_MS);

    this.hoverTimers.set(postId, timer);
  }

  onPostMouseLeave(postId: string): void {
    const timer = this.hoverTimers.get(postId);
    if (timer !== undefined) {
      clearTimeout(timer);
      this.hoverTimers.delete(postId);
    }
  }

  private startViewportTimer(postId: string): void {
    if (this.viewportTimers.has(postId)) return;

    const timer = window.setTimeout(() => {
      this.viewportTimers.delete(postId);
      this.addToPendingSeen(postId);
    }, this.VIEWPORT_THRESHOLD_MS);

    this.viewportTimers.set(postId, timer);
  }

  private cancelViewportTimer(postId: string): void {
    const timer = this.viewportTimers.get(postId);
    if (timer !== undefined) {
      clearTimeout(timer);
      this.viewportTimers.delete(postId);
    }
  }

  private addToPendingSeen(postId: string): void {
    if (this.seenPostIds.has(postId) || this.pendingSeenPosts.has(postId)) return;

    this.pendingSeenPosts.add(postId);

    if (this.batchTimer === null) {
      this.batchTimer = window.setTimeout(() => {
        this.flushPendingPosts();
      }, this.BATCH_DELAY_MS);
    }
  }

  private flushPendingPosts(): void {
    if (this.batchTimer !== null) {
      clearTimeout(this.batchTimer);
      this.batchTimer = null;
    }

    if (this.pendingSeenPosts.size === 0) return;

    const postIds = Array.from(this.pendingSeenPosts);
    this.pendingSeenPosts.clear();

    postIds.forEach((id) => this.seenPostIds.add(id));
    this.updateUnreadCount();

    this.api.markPostsSeen(postIds).subscribe({
      error: (err) => {
        console.error('Failed to mark posts as seen', err);
      }
    });
  }

  private updateUnreadCount(): void {
    this.unreadCount = this.items.length - this.seenPostIds.size;
  }

  private trackSeenPosts(data: any[]): void {
    const postIds: string[] = [];
    
    for (const item of data) {
      if (this.isStormView && item.root) {
        postIds.push(item.root.id);
        for (const branch of item.branches || []) {
          postIds.push(branch.id);
        }
      } else {
        postIds.push(item.id);
      }
    }

    this.api.getSeenPosts(postIds).subscribe({
      next: (res) => {
        this.seenPostIds = new Set(res.seen);
        this.updateUnreadCount();
      },
      error: (err) => {
        console.error('Failed to get seen posts', err);
      }
    });
  }

  isPostRead(postId: string): boolean {
    return this.seenPostIds.has(postId);
  }
}
