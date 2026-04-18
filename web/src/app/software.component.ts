import { Component, OnInit, OnDestroy, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ApiService } from './api.service';
import { Router } from '@angular/router';
import { ContentHubStateService } from './content-hub-state.service';
import { ContentHubPost } from './mastodon';
import { combineLatest, Subscription } from 'rxjs';
import {
  ContentFeedFilter,
  ContentFeedPost,
  contentFeedFilters,
  getContentUserFilter,
  getPopularityScore,
  groupLinkPosts,
  normalizeContentPost,
  sortContentPosts,
  ContentFeedGroup,
} from './content-feed.utils';

// ---------------------------------------------------------------------------
// Shared styles (must be declared before any @Component that references it)
// ---------------------------------------------------------------------------

const SHARED_STYLES = `
  .filter-bar {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 16px;
    margin-bottom: 20px;
    padding-bottom: 16px;
    border-bottom: 1px solid #e5e7eb;
    flex-wrap: wrap;
  }
  .filter-buttons { display: flex; flex-wrap: wrap; gap: 8px; }
  .filter-btn {
    padding: 6px 14px;
    background: white;
    border: 1px solid #d1d5db;
    border-radius: 999px;
    font-size: 0.85rem;
    cursor: pointer;
    color: #374151;
    transition: all 0.2s;
  }
  .filter-btn:hover { background: #f9fafb; border-color: #6366f1; }
  .filter-btn.active { background: #6366f1; color: white; border-color: #6366f1; }
  .content-card { margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #eee; }
  .signal-row { display: flex; flex-wrap: wrap; gap: 8px; margin-left: auto; }
  .signal-pill {
    background: #eef2ff;
    color: #4338ca;
    border-radius: 999px;
    padding: 4px 10px;
    font-size: 0.8rem;
    font-weight: 600;
    white-space: nowrap;
  }
`;

// ---------------------------------------------------------------------------
// Shared helper: convert a ContentHubPost to ContentFeedPost
// ---------------------------------------------------------------------------
function hubToFeedPost(p: ContentHubPost): ContentFeedPost {
  return {
    id: p.id,
    content: p.content,
    created_at: p.created_at,
    author_acct: p.author_acct,
    author_display_name: p.author_display_name,
    author_avatar: p.author_avatar,
    counts: { likes: p.counts.likes, replies: p.counts.replies, reposts: p.counts.reblogs },
  };
}

// ---------------------------------------------------------------------------
// Software
// ---------------------------------------------------------------------------

@Component({
  selector: 'app-software-feed',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="card">
      <div class="filter-bar">
        <div>
          <h2 style="margin: 0;">
            {{ groupName ? groupName + ' — ' : '' }}Cool Software Recommendations
          </h2>
          <p class="muted" style="margin: 6px 0 0;">
            Rank recommendations by community engagement or switch between your follows and the wider network.
          </p>
        </div>
        <div class="filter-buttons">
          @for (filter of filters; track filter) {
            <button
              [class.active]="currentFilter === filter.value"
              (click)="setFilter(filter.value)"
              class="filter-btn">
              {{ filter.label }}
            </button>
          }
          @if (groupId !== null) {
            <button (click)="fetchNew()" class="filter-btn" [disabled]="loading || refreshing">
              {{ refreshing ? 'Fetching...' : 'Fetch New' }}
            </button>
          }
        </div>
      </div>

      @if (loading) { <div class="muted">Loading software posts...</div> }

      @if (!loading && posts.length === 0) {
        <div class="muted">No software recommendations found.</div>
      }

      @for (post of posts; track post) {
        <div class="content-card">
          <div class="row" style="gap: 12px; align-items: flex-start;">
            <div>
              <strong>{{ post.author_display_name || post.author_acct }}</strong>
              <div class="muted" style="margin-top: 4px;">{{ post.created_at | date: 'short' }}</div>
            </div>
            <div class="signal-row">
              <span class="signal-pill">Score {{ getPopularityScore(post) }}</span>
              <span class="signal-pill">❤️ {{ post.counts.likes }}</span>
              <span class="signal-pill">💬 {{ post.counts.replies }}</span>
              <span class="signal-pill">🔁 {{ post.counts.reposts }}</span>
            </div>
          </div>
          <div [innerHTML]="post.content" style="margin: 12px 0;"></div>
          <button (click)="viewPost(post.id)" class="secondary">View Details</button>
        </div>
      }
    </div>
    `,
  styles: [SHARED_STYLES]
})
export class SoftwareFeedComponent implements OnInit, OnDestroy {
  private api = inject(ApiService);
  private router = inject(Router);
  private hubState = inject(ContentHubStateService);

  posts: ContentFeedPost[] = [];
  loading = true;
  refreshing = false;
  currentFilter: ContentFeedFilter = 'recent';
  groupName: string | null = null;
  groupId: number | null = null;
  readonly filters = contentFeedFilters;

  private sub?: Subscription;

  ngOnInit(): void {
    this.sub = combineLatest([this.api.identityId$, this.hubState.activeGroup$]).subscribe(
      ([identityId, group]) => {
        this.groupId = group?.id ?? null;
        if (identityId) this.load(identityId, group?.id ?? null, group?.name ?? null);
      },
    );
  }

  ngOnDestroy(): void { this.sub?.unsubscribe(); }

  private load(identityId: number, groupId: number | null, groupName: string | null): void {
    this.loading = true;
    this.groupName = groupName;

    if (groupId !== null) {
      this.api.getContentHubGroupPosts(groupId, identityId, 'software', null, 100).subscribe({
        next: (res) => {
          this.posts = sortContentPosts(res.items.map(hubToFeedPost), this.currentFilter);
          this.loading = false;
        },
        error: () => (this.loading = false),
      });
    } else {
      const userFilter = getContentUserFilter(this.currentFilter);
      this.api.getPublicPosts(identityId, 'software', userFilter).subscribe({
        next: (page) => {
          this.posts = sortContentPosts(page.items.map(normalizeContentPost), this.currentFilter);
          this.loading = false;
        },
        error: () => (this.loading = false),
      });
    }
  }

  setFilter(filter: ContentFeedFilter): void {
    this.currentFilter = filter;
    const identityId = this.api.getCurrentIdentityId();
    const group = this.hubState.getActiveGroup();
    if (identityId) this.load(identityId, group?.id ?? null, group?.name ?? null);
  }

  fetchNew(): void {
    const identityId = this.api.getCurrentIdentityId();
    const group = this.hubState.getActiveGroup();
    if (!identityId || !group) return;
    this.refreshing = true;
    this.api.refreshContentHubGroup(group.id, identityId).subscribe({
      next: () => { this.refreshing = false; this.load(identityId, group.id, group.name); },
      error: () => (this.refreshing = false),
    });
  }

  getPopularityScore(post: ContentFeedPost): number { return getPopularityScore(post); }
  viewPost(id: string): void { this.router.navigate(['/p', id]); }
}

// ---------------------------------------------------------------------------
// Links
// ---------------------------------------------------------------------------

@Component({
  selector: 'app-links-feed',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="card">
      <div class="filter-bar">
        <div>
          <h2 style="margin: 0;">{{ groupName ? groupName + ' — ' : '' }}Shared Links</h2>
          <p class="muted" style="margin: 6px 0 0;">
            Spot the domains your network keeps endorsing, or flip back to the freshest shares.
          </p>
        </div>
        <div class="filter-buttons">
          @for (filter of filters; track filter) {
            <button
              [class.active]="currentFilter === filter.value"
              (click)="setFilter(filter.value)"
              class="filter-btn">
              {{ filter.label }}
            </button>
          }
          @if (groupId !== null) {
            <button (click)="fetchNew()" class="filter-btn" [disabled]="loading || refreshing">
              {{ refreshing ? 'Fetching...' : 'Fetch New' }}
            </button>
          }
        </div>
      </div>

      @if (loading) { <div class="muted">Loading links...</div> }

      @if (!loading && groups.length === 0) {
        <div class="muted">No links found.</div>
      }

      @for (group of groups; track group) {
        <div style="margin-bottom: 30px;">
          <div class="row" style="align-items: center; gap: 12px; margin-bottom: 12px;">
            <h3 style="color: #6366f1; font-size: 1.1rem; margin: 0;">{{ group.domain }}</h3>
            <span class="signal-pill">{{ group.posts.length }} mentions</span>
            <span class="signal-pill">Score {{ group.totalScore }}</span>
          </div>
          @for (post of group.posts; track post) {
            <div style="margin: 15px 0; padding-left: 15px; border-left: 3px solid #e5e7eb;">
              <div class="row" style="gap: 10px; align-items: center;">
                <div class="muted">
                  {{ post.author_display_name || post.author_acct }} • {{ post.created_at | date: 'short' }}
                </div>
                <div class="signal-row">
                  <span class="signal-pill">Score {{ getPopularityScore(post) }}</span>
                  <span class="signal-pill">❤️ {{ post.counts.likes }}</span>
                  <span class="signal-pill">💬 {{ post.counts.replies }}</span>
                  <span class="signal-pill">🔁 {{ post.counts.reposts }}</span>
                </div>
              </div>
              <div [innerHTML]="post.content" style="margin: 5px 0;"></div>
              <button (click)="viewPost(post.id)" class="secondary" style="margin-top: 8px;">View</button>
            </div>
          }
        </div>
      }
    </div>
    `,
  styles: [SHARED_STYLES]
})
export class LinksFeedComponent implements OnInit, OnDestroy {
  private api = inject(ApiService);
  private router = inject(Router);
  private hubState = inject(ContentHubStateService);

  groups: ContentFeedGroup[] = [];
  loading = true;
  refreshing = false;
  currentFilter: ContentFeedFilter = 'recent';
  groupName: string | null = null;
  groupId: number | null = null;
  readonly filters = contentFeedFilters;

  private sub?: Subscription;

  ngOnInit(): void {
    this.sub = combineLatest([this.api.identityId$, this.hubState.activeGroup$]).subscribe(
      ([identityId, group]) => {
        this.groupId = group?.id ?? null;
        if (identityId) this.load(identityId, group?.id ?? null, group?.name ?? null);
      },
    );
  }

  ngOnDestroy(): void { this.sub?.unsubscribe(); }

  private load(identityId: number, groupId: number | null, groupName: string | null): void {
    this.loading = true;
    this.groupName = groupName;

    if (groupId !== null) {
      this.api.getContentHubGroupPosts(groupId, identityId, 'links', null, 100).subscribe({
        next: (res) => {
          const posts = sortContentPosts(
            res.items.map(hubToFeedPost),
            this.currentFilter,
          );
          this.groups = groupLinkPosts(posts, this.currentFilter);
          this.loading = false;
        },
        error: () => (this.loading = false),
      });
    } else {
      const userFilter = getContentUserFilter(this.currentFilter);
      this.api.getPublicPosts(identityId, 'links', userFilter).subscribe({
        next: (page) => {
          const posts = sortContentPosts(page.items.map(normalizeContentPost), this.currentFilter);
          this.groups = groupLinkPosts(posts, this.currentFilter);
          this.loading = false;
        },
        error: () => (this.loading = false),
      });
    }
  }

  setFilter(filter: ContentFeedFilter): void {
    this.currentFilter = filter;
    const identityId = this.api.getCurrentIdentityId();
    const group = this.hubState.getActiveGroup();
    if (identityId) this.load(identityId, group?.id ?? null, group?.name ?? null);
  }

  fetchNew(): void {
    const identityId = this.api.getCurrentIdentityId();
    const group = this.hubState.getActiveGroup();
    if (!identityId || !group) return;
    this.refreshing = true;
    this.api.refreshContentHubGroup(group.id, identityId).subscribe({
      next: () => { this.refreshing = false; this.load(identityId, group.id, group.name); },
      error: () => (this.refreshing = false),
    });
  }

  getPopularityScore(post: ContentFeedPost): number { return getPopularityScore(post); }
  viewPost(id: string): void { this.router.navigate(['/p', id]); }
}

// ---------------------------------------------------------------------------
// News
// ---------------------------------------------------------------------------

@Component({
  selector: 'app-news-feed',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="card">
      <div class="filter-bar">
        <div>
          <h2 style="margin: 0;">{{ groupName ? groupName + ' — ' : '' }}News Feed</h2>
          <p class="muted" style="margin: 6px 0 0;">
            Browse breaking stories by freshness or let engagement surface the articles your network found worthwhile.
          </p>
        </div>
        <div class="filter-buttons">
          @for (filter of filters; track filter) {
            <button
              [class.active]="currentFilter === filter.value"
              (click)="setFilter(filter.value)"
              class="filter-btn">
              {{ filter.label }}
            </button>
          }
          @if (groupId !== null) {
            <button (click)="fetchNew()" class="filter-btn" [disabled]="loading || refreshing">
              {{ refreshing ? 'Fetching...' : 'Fetch New' }}
            </button>
          }
        </div>
      </div>

      @if (loading) { <div class="muted">Loading news...</div> }

      @if (!loading && posts.length === 0) {
        <div class="muted">No news articles found.</div>
      }

      @for (post of posts; track post) {
        <div style="margin-bottom: 25px; padding: 15px; background: #f9fafb; border-radius: 8px;">
          <div class="row" style="margin-bottom: 10px;">
            <div style="display: flex; align-items: center; gap: 8px;">
              @if (post.author_avatar) {
                <img [src]="post.author_avatar" alt="" style="width: 32px; height: 32px; border-radius: 50%;">
              }
              <strong>{{ post.author_display_name || post.author_acct }}</strong>
            </div>
            <div class="signal-row">
              <span class="signal-pill">{{ post.created_at | date: 'short' }}</span>
              <span class="signal-pill">Score {{ getPopularityScore(post) }}</span>
              <span class="signal-pill">❤️ {{ post.counts.likes }}</span>
              <span class="signal-pill">💬 {{ post.counts.replies }}</span>
              <span class="signal-pill">🔁 {{ post.counts.reposts }}</span>
            </div>
          </div>
          <div [innerHTML]="post.content"></div>
          <button (click)="viewPost(post.id)" class="secondary" style="margin-top: 10px;">Read More</button>
        </div>
      }
    </div>
    `,
  styles: [SHARED_STYLES]
})
export class NewsFeedComponent implements OnInit, OnDestroy {
  private api = inject(ApiService);
  private router = inject(Router);
  private hubState = inject(ContentHubStateService);

  posts: ContentFeedPost[] = [];
  loading = true;
  refreshing = false;
  currentFilter: ContentFeedFilter = 'recent';
  groupName: string | null = null;
  groupId: number | null = null;
  readonly filters = contentFeedFilters;

  private sub?: Subscription;

  ngOnInit(): void {
    this.sub = combineLatest([this.api.identityId$, this.hubState.activeGroup$]).subscribe(
      ([identityId, group]) => {
        this.groupId = group?.id ?? null;
        if (identityId) this.load(identityId, group?.id ?? null, group?.name ?? null);
      },
    );
  }

  ngOnDestroy(): void { this.sub?.unsubscribe(); }

  private load(identityId: number, groupId: number | null, groupName: string | null): void {
    this.loading = true;
    this.groupName = groupName;

    if (groupId !== null) {
      this.api.getContentHubGroupPosts(groupId, identityId, 'news', null, 100).subscribe({
        next: (res) => {
          this.posts = sortContentPosts(res.items.map(hubToFeedPost), this.currentFilter);
          this.loading = false;
        },
        error: () => (this.loading = false),
      });
    } else {
      const userFilter = getContentUserFilter(this.currentFilter);
      this.api.getPublicPosts(identityId, 'news', userFilter).subscribe({
        next: (page) => {
          this.posts = sortContentPosts(page.items.map(normalizeContentPost), this.currentFilter);
          this.loading = false;
        },
        error: () => (this.loading = false),
      });
    }
  }

  setFilter(filter: ContentFeedFilter): void {
    this.currentFilter = filter;
    const identityId = this.api.getCurrentIdentityId();
    const group = this.hubState.getActiveGroup();
    if (identityId) this.load(identityId, group?.id ?? null, group?.name ?? null);
  }

  fetchNew(): void {
    const identityId = this.api.getCurrentIdentityId();
    const group = this.hubState.getActiveGroup();
    if (!identityId || !group) return;
    this.refreshing = true;
    this.api.refreshContentHubGroup(group.id, identityId).subscribe({
      next: () => { this.refreshing = false; this.load(identityId, group.id, group.name); },
      error: () => (this.refreshing = false),
    });
  }

  getPopularityScore(post: ContentFeedPost): number { return getPopularityScore(post); }
  viewPost(id: string): void { this.router.navigate(['/p', id]); }
}

