// web/src/app/content-hub-tabs.component.ts
// Text and Jobs tab components — only meaningful when a hashtag group is selected.
import { Component, OnInit, OnDestroy, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { ApiService } from './api.service';
import { ContentHubStateService } from './content-hub-state.service';
import { ContentHubPost } from './mastodon';
import { combineLatest, Subscription } from 'rxjs';
import { ContentFeedPost, contentFeedFilters, ContentFeedFilter, getPopularityScore, sortContentPosts } from './content-feed.utils';

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

const TAB_STYLES = `
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
  .post-card { margin-bottom: 20px; padding-bottom: 18px; border-bottom: 1px solid #eee; }
  .signal-row { display: flex; flex-wrap: wrap; gap: 8px; margin-left: auto; }
  .signal-pill {
    background: #eef2ff; color: #4338ca;
    border-radius: 999px; padding: 4px 10px;
    font-size: 0.8rem; font-weight: 600; white-space: nowrap;
  }
  .no-group {
    padding: 40px 20px; text-align: center; color: #9ca3af;
  }
`;

// ---------------------------------------------------------------------------
// Text tab — all posts in the selected group, newest-first or by popularity
// ---------------------------------------------------------------------------

@Component({
  selector: 'app-content-hub-text',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="card">
      @if (!groupName) {
        <div class="no-group">
          <p>Select a hashtag group from the sidebar to see posts here.</p>
        </div>
      } @else {
        <div class="filter-bar">
          <div>
            <h2 style="margin: 0;">{{ groupName }} — Text</h2>
            <p class="muted" style="margin: 6px 0 0;">All posts in this group.</p>
          </div>
          <div class="filter-buttons">
            @for (filter of filters; track filter) {
              <button [class.active]="currentFilter === filter.value" (click)="setFilter(filter.value)" class="filter-btn">
                {{ filter.label }}
              </button>
            }
          </div>
        </div>

        @if (loading) { <div class="muted">Loading...</div> }
        @if (!loading && posts.length === 0) { <div class="muted">No posts found in this group.</div> }

        @for (post of posts; track post.id) {
          <div class="post-card">
            <div class="row" style="gap: 8px; align-items: center; margin-bottom: 6px;">
              @if (post.author_avatar) {
                <img [src]="post.author_avatar" alt="" style="width: 26px; height: 26px; border-radius: 50%;">
              }
              <strong style="font-size: 0.9rem;">{{ post.author_display_name || post.author_acct }}</strong>
              <span class="muted" style="font-size: 0.8rem; margin-left: auto;">{{ post.created_at | date: 'short' }}</span>
              <div class="signal-row" style="margin-left: 0;">
                <span class="signal-pill">❤️ {{ post.counts.likes }}</span>
                <span class="signal-pill">💬 {{ post.counts.replies }}</span>
              </div>
            </div>
            <div [innerHTML]="post.content" style="margin: 8px 0; font-size: 0.92rem;"></div>
            <button (click)="viewPost(post.id)" class="secondary" style="font-size: 0.8rem;">View</button>
          </div>
        }
      }
    </div>
  `,
  styles: [TAB_STYLES],
})
export class ContentHubTextComponent implements OnInit, OnDestroy {
  private api = inject(ApiService);
  private router = inject(Router);
  private hubState = inject(ContentHubStateService);

  posts: ContentFeedPost[] = [];
  loading = false;
  groupName: string | null = null;
  currentFilter: ContentFeedFilter = 'recent';
  readonly filters = contentFeedFilters;

  private sub?: Subscription;

  ngOnInit(): void {
    this.sub = combineLatest([this.api.identityId$, this.hubState.activeGroup$]).subscribe(
      ([identityId, group]) => {
        this.groupName = group?.name ?? null;
        if (identityId && group) this.load(identityId, group.id);
        else this.posts = [];
      },
    );
  }

  ngOnDestroy(): void { this.sub?.unsubscribe(); }

  private load(identityId: number, groupId: number): void {
    this.loading = true;
    this.api.getContentHubGroupPosts(groupId, identityId, 'text', null, 100).subscribe({
      next: (res) => {
        this.posts = sortContentPosts(res.items.map(hubToFeedPost), this.currentFilter);
        this.loading = false;
      },
      error: () => (this.loading = false),
    });
  }

  setFilter(filter: ContentFeedFilter): void {
    this.currentFilter = filter;
    const identityId = this.api.getCurrentIdentityId();
    const group = this.hubState.getActiveGroup();
    if (identityId && group) this.load(identityId, group.id);
  }

  viewPost(id: string): void { this.router.navigate(['/p', id]); }
  getPopularityScore(post: ContentFeedPost): number { return getPopularityScore(post); }
}

// ---------------------------------------------------------------------------
// Jobs tab — posts in the selected group filtered to job-related content
// ---------------------------------------------------------------------------

@Component({
  selector: 'app-content-hub-jobs',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="card">
      @if (!groupName) {
        <div class="no-group">
          <p>Select a hashtag group from the sidebar to see jobs here.</p>
        </div>
      } @else {
        <div class="filter-bar">
          <div>
            <h2 style="margin: 0;">{{ groupName }} — Jobs</h2>
            <p class="muted" style="margin: 6px 0 0;">Job-related posts in this group.</p>
          </div>
          <div class="filter-buttons">
            @for (filter of filters; track filter) {
              <button [class.active]="currentFilter === filter.value" (click)="setFilter(filter.value)" class="filter-btn">
                {{ filter.label }}
              </button>
            }
          </div>
        </div>

        @if (loading) { <div class="muted">Loading...</div> }
        @if (!loading && posts.length === 0) {
          <div class="muted">No job-related posts found in this group.</div>
        }

        @for (post of posts; track post.id) {
          <div class="post-card">
            <div class="row" style="gap: 8px; align-items: center; margin-bottom: 6px;">
              @if (post.author_avatar) {
                <img [src]="post.author_avatar" alt="" style="width: 26px; height: 26px; border-radius: 50%;">
              }
              <strong style="font-size: 0.9rem;">{{ post.author_display_name || post.author_acct }}</strong>
              <span class="muted" style="font-size: 0.8rem; margin-left: auto;">{{ post.created_at | date: 'short' }}</span>
              <div class="signal-row" style="margin-left: 0;">
                <span class="signal-pill">❤️ {{ post.counts.likes }}</span>
                <span class="signal-pill">💬 {{ post.counts.replies }}</span>
              </div>
            </div>
            <div [innerHTML]="post.content" style="margin: 8px 0; font-size: 0.92rem;"></div>
            <button (click)="viewPost(post.id)" class="secondary" style="font-size: 0.8rem;">View</button>
          </div>
        }
      }
    </div>
  `,
  styles: [TAB_STYLES],
})
export class ContentHubJobsComponent implements OnInit, OnDestroy {
  private api = inject(ApiService);
  private router = inject(Router);
  private hubState = inject(ContentHubStateService);

  posts: ContentFeedPost[] = [];
  loading = false;
  groupName: string | null = null;
  currentFilter: ContentFeedFilter = 'recent';
  readonly filters = contentFeedFilters;

  private sub?: Subscription;

  ngOnInit(): void {
    this.sub = combineLatest([this.api.identityId$, this.hubState.activeGroup$]).subscribe(
      ([identityId, group]) => {
        this.groupName = group?.name ?? null;
        if (identityId && group) this.load(identityId, group.id);
        else this.posts = [];
      },
    );
  }

  ngOnDestroy(): void { this.sub?.unsubscribe(); }

  private load(identityId: number, groupId: number): void {
    this.loading = true;
    this.api.getContentHubGroupPosts(groupId, identityId, 'jobs', null, 100).subscribe({
      next: (res) => {
        this.posts = sortContentPosts(res.items.map(hubToFeedPost), this.currentFilter);
        this.loading = false;
      },
      error: () => (this.loading = false),
    });
  }

  setFilter(filter: ContentFeedFilter): void {
    this.currentFilter = filter;
    const identityId = this.api.getCurrentIdentityId();
    const group = this.hubState.getActiveGroup();
    if (identityId && group) this.load(identityId, group.id);
  }

  viewPost(id: string): void { this.router.navigate(['/p', id]); }
  getPopularityScore(post: ContentFeedPost): number { return getPopularityScore(post); }
}
