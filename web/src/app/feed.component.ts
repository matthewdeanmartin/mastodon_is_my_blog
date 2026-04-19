// web/src/app/feed.component.ts

import {
  Component,
  OnInit,
  OnDestroy,
  ElementRef,
  ViewChildren,
  ViewChild,
  QueryList,
  AfterViewInit,
  inject,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
} from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { ApiService, FeedPage } from './api.service';
import { CommonModule } from '@angular/common';
import { DomSanitizer } from '@angular/platform-browser';
import { LinkPreviewComponent, LinkFaviconsComponent } from './link.component';
import { combineLatest, Subscription } from 'rxjs';
import { HttpErrorResponse } from '@angular/common/http';
import { FeedViewModel, RawContentPost, toFeedViewModel } from './content-feed.utils';
import { Storm } from './api.service';

@Component({
  selector: 'app-public-feed',
  standalone: true,
  imports: [CommonModule, RouterLink, LinkPreviewComponent, LinkFaviconsComponent],
  templateUrl: 'feed.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PublicFeedComponent implements OnInit, OnDestroy, AfterViewInit {
  private route = inject(ActivatedRoute);
  private api = inject(ApiService);
  private sanitizer = inject(DomSanitizer);
  private cdr = inject(ChangeDetectorRef);

  @ViewChildren('postItem') postItems!: QueryList<ElementRef>;
  @ViewChild('loadMoreSentinel') loadMoreSentinel?: ElementRef<HTMLElement>;

  items: (RawContentPost | Storm)[] = [];
  viewModels = new Map<string, FeedViewModel>();
  loading = true;
  loadingMore = false;
  nextCursor: string | null = null;
  isStormView = false;
  currentFilter = 'storms';
  currentUser: string | undefined;
  unreadCount = 0;

  currentIdentityId: number | null = null;
  seenPostIds = new Set<string>();

  private scrollSubscription?: Subscription;
  private refreshSubscription?: Subscription;
  private observer?: IntersectionObserver;
  private loadMoreObserver?: IntersectionObserver;

  private pendingSeenPosts = new Set<string>();
  private batchTimer: number | null = null;
  private readonly BATCH_DELAY_MS = 5000;

  private hoverTimers = new Map<string, number>();
  private readonly HOVER_DELAY_MS = 500;

  private viewportTimers = new Map<string, number>();
  private readonly VIEWPORT_THRESHOLD_MS = 1500;

  private readonly isTouchDevice: boolean;

  constructor() {
    this.isTouchDevice = typeof navigator !== 'undefined' && navigator.maxTouchPoints > 0;
  }

  get stormFeedItems(): Storm[] {
    return this.items.filter((item): item is Storm => 'root' in item);
  }

  get flatFeedItems(): RawContentPost[] {
    return this.items.filter((item): item is RawContentPost => !('root' in item));
  }

  postTemplateContext(post: RawContentPost): { $implicit: RawContentPost } {
    return { $implicit: post };
  }

  ngOnInit(): void {
    // Combine Route Params with Identity State
    combineLatest([this.route.queryParams, this.api.identityId$]).subscribe(
      ([params, identityId]) => {
        const prevIdentityId = this.currentIdentityId;
        this.currentIdentityId = identityId;

        if (!identityId) {
          this.loading = true; // Wait for identity
          return;
        }

        const newFilter = params['filter'] || 'storms';
        const newUser = params['user'] || undefined; // "everyone" passes through as string here

        // Reload only if filter/user changed or identity actually changed
        const identityChanged = prevIdentityId !== identityId;
        const filterChanged = newFilter !== this.currentFilter;
        const userChanged = newUser !== this.currentUser;

        if (filterChanged || userChanged || identityChanged) {
          this.currentFilter = newFilter;
          this.currentUser = newUser;
          this.load(this.currentFilter, this.currentUser, identityId);
        }
      },
    );

    this.refreshSubscription = this.api.refreshNeeded$.subscribe(() => {
      if (this.currentIdentityId) {
        this.load(this.currentFilter, this.currentUser, this.currentIdentityId);
      }
    });
  }

  load(filter: string, user: string | undefined, identityId: number): void {
    this.loading = true;
    this.items = [];
    this.viewModels = new Map();
    this.nextCursor = null;
    this.loadingMore = false;

    // Capture the base URL now, before any async work, so all view models
    // built from this load use the correct instance even if the user switches
    // identity while the request is in flight.
    const localBaseUrl = this.api.getIdentityBaseUrl();

    // Define the success handler to reuse
    const handleSuccess = (page: FeedPage<RawContentPost | Storm>) => {
      this.loading = false;
      const data = page.items;
      this.items = data;
      this.nextCursor = page.next_cursor;
      this.trackSeenPosts(data, localBaseUrl);
      this.updateUnreadCount();
      this.cdr.markForCheck();
      // Observe the load-more sentinel after the first page lands.
      // Defer so the DOM has rendered the sentinel.
      setTimeout(() => this.setupLoadMoreObserver(), 0);
    };

    const handleError = (error: HttpErrorResponse) => {
      console.error(`Error loading posts (Status: ${error.status}):`, error);
      this.loading = false;
    };

    // If 'storms' (or legacy 'all'), use the Storms endpoint for the threaded view
    if (filter === 'storms' || filter === 'all') {
      this.isStormView = true;
      this.api.getStorms(identityId, user).subscribe({
        next: (page) => handleSuccess(page as FeedPage<RawContentPost | Storm>),
        error: handleError,
      });
    }
    // If 'shorts', use the new Shorts endpoint for flat view
    else if (filter === 'shorts') {
      this.isStormView = false;
      this.api.getShorts(identityId, user).subscribe({
        next: (page) => handleSuccess(page as FeedPage<RawContentPost | Storm>),
        error: handleError,
      });
    } else {
      // Otherwise use the standard flat list with the specific filter
      this.isStormView = false;
      this.api.getPublicPosts(identityId, filter, user).subscribe({
        next: (page) => handleSuccess(page as FeedPage<RawContentPost | Storm>),
        error: handleError,
      });
    }
  }

  loadMore(): void {
    if (this.loadingMore || !this.nextCursor || !this.currentIdentityId) return;
    this.loadingMore = true;
    const identityId = this.currentIdentityId;
    const filter = this.currentFilter;
    const user = this.currentUser;
    const cursor = this.nextCursor;
    const localBaseUrl = this.api.getIdentityBaseUrl();

    const handleMore = (page: FeedPage<RawContentPost | Storm>) => {
      this.items = [...this.items, ...page.items];
      this.nextCursor = page.next_cursor;
      this.loadingMore = false;
      this.trackSeenPosts(page.items, localBaseUrl);
      this.updateUnreadCount();
      this.cdr.markForCheck();
      if (this.nextCursor) {
        setTimeout(() => this.setupLoadMoreObserver(), 0);
      } else {
        this.loadMoreObserver?.disconnect();
      }
    };

    const handleErr = (err: HttpErrorResponse) => {
      console.error('Load more failed:', err);
      this.loadingMore = false;
    };

    if (filter === 'storms' || filter === 'all') {
      this.api.getStorms(identityId, user, cursor).subscribe({
        next: (page) => handleMore(page as FeedPage<RawContentPost | Storm>),
        error: handleErr,
      });
    } else if (filter === 'shorts') {
      this.api.getShorts(identityId, user, cursor).subscribe({
        next: (page) => handleMore(page as FeedPage<RawContentPost | Storm>),
        error: handleErr,
      });
    } else {
      this.api.getPublicPosts(identityId, filter, user, cursor).subscribe({
        next: (page) => handleMore(page as FeedPage<RawContentPost | Storm>),
        error: handleErr,
      });
    }
  }

  private setupLoadMoreObserver(): void {
    if (typeof IntersectionObserver === 'undefined') return;
    if (!this.loadMoreSentinel || !this.nextCursor) return;

    this.loadMoreObserver?.disconnect();
    this.loadMoreObserver = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        if (entry.isIntersecting) {
          this.loadMore();
        }
      },
      { rootMargin: '400px' },
    );
    this.loadMoreObserver.observe(this.loadMoreSentinel.nativeElement);
  }

  trackById(_index: number, item: RawContentPost | Storm): string {
    if ('root' in item) return item.root.id;
    return item.id;
  }

  trackByBranchId(_index: number, item: RawContentPost): string {
    return item.id;
  }

  vm(postId: string): FeedViewModel | undefined {
    return this.viewModels.get(postId);
  }

  getQueryParams() {
    const params: Record<string, string> = { filter: this.currentFilter };
    if (this.currentUser) {
      params['user'] = this.currentUser;
    }
    return params;
  }

  private buildViewModels(data: (RawContentPost | Storm)[], localBaseUrl: string | null): void {
    const sanitize = (html: string) => this.sanitizer.bypassSecurityTrustHtml(html);
    for (const item of data) {
      if ('root' in item) {
        this.viewModels.set(
          item.root.id,
          toFeedViewModel(item.root, sanitize, this.seenPostIds, localBaseUrl),
        );
        for (const branch of item.branches ?? []) {
          this.viewModels.set(
            branch.id,
            toFeedViewModel(branch, sanitize, this.seenPostIds, localBaseUrl),
          );
        }
      } else {
        this.viewModels.set(
          item.id,
          toFeedViewModel(item, sanitize, this.seenPostIds, localBaseUrl),
        );
      }
    }
  }

  private rebuildReadState(): void {
    for (const [id, model] of this.viewModels) {
      if (!model.isRead && this.seenPostIds.has(id)) {
        this.viewModels.set(id, { ...model, isRead: true });
      }
    }
  }

  ngAfterViewInit(): void {
    this.setupScrollTracking();
  }

  ngOnDestroy(): void {
    this.refreshSubscription?.unsubscribe();
    this.scrollSubscription?.unsubscribe();
    this.observer?.disconnect();
    this.loadMoreObserver?.disconnect();
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
      { threshold: 0.5 },
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
      error: (err: unknown) => {
        console.error('Failed to mark posts as seen', err);
      },
    });
  }

  private updateUnreadCount(): void {
    this.unreadCount = this.items.length - this.seenPostIds.size;
  }

  private trackSeenPosts(data: (RawContentPost | Storm)[], localBaseUrl: string | null): void {
    const postIds: string[] = [];

    for (const item of data) {
      if (this.isStormView && 'root' in item) {
        postIds.push(item.root.id);
        for (const branch of item.branches || []) {
          postIds.push(branch.id);
        }
      } else if ('id' in item) {
        postIds.push((item as RawContentPost).id);
      }
    }

    // Build view models now (before seen state arrives, isRead = false for new items).
    this.buildViewModels(data, localBaseUrl);

    this.api.getSeenPosts(postIds).subscribe({
      next: (res) => {
        this.seenPostIds = new Set<string>(res.seen);
        this.rebuildReadState();
        this.updateUnreadCount();
        this.cdr.markForCheck();
      },
      error: (err: unknown) => {
        console.error('Failed to get seen posts', err);
      },
    });
  }

  isPostRead(postId: string): boolean {
    return this.seenPostIds.has(postId);
  }
}
