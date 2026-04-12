import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ApiService } from './api.service';
import { Router } from '@angular/router';
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

@Component({
  selector: 'app-software-feed',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="card">
      <div class="filter-bar">
        <div>
          <h2 style="margin: 0;">Cool Software Recommendations</h2>
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
        </div>
      </div>
    
      @if (loading) {
        <div class="muted">Loading software posts...</div>
      }
    
      @if (!loading && posts.length === 0) {
        <div class="muted">
          No software recommendations found.
        </div>
      }
    
      @for (post of posts; track post) {
        <div
          class="content-card">
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
  styles: [`
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

    .filter-buttons {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }

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

    .filter-btn:hover {
      background: #f9fafb;
      border-color: #6366f1;
    }

    .filter-btn.active {
      background: #6366f1;
      color: white;
      border-color: #6366f1;
    }

    .content-card {
      margin-bottom: 24px;
      padding-bottom: 20px;
      border-bottom: 1px solid #eee;
    }

    .signal-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-left: auto;
    }

    .signal-pill {
      background: #eef2ff;
      color: #4338ca;
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 0.8rem;
      font-weight: 600;
      white-space: nowrap;
    }
  `]
})
export class SoftwareFeedComponent implements OnInit {
  private api = inject(ApiService);
  private router = inject(Router);

  posts: ContentFeedPost[] = [];
  loading = true;
  currentFilter: ContentFeedFilter = 'recent';
  readonly filters = contentFeedFilters;

  ngOnInit(): void {
    this.api.identityId$.subscribe((identityId) => {
      if (identityId) {
        this.loadPosts();
      }
    });
  }

  loadPosts(): void {
    const identityId = this.api.getCurrentIdentityId();
    if (!identityId) {
      this.loading = false;
      return;
    }

    this.loading = true;
    const userFilter = getContentUserFilter(this.currentFilter);

    this.api.getPublicPosts(identityId, 'software', userFilter).subscribe({
      next: (page) => {
        this.posts = sortContentPosts(
          page.items.map((post) => normalizeContentPost(post)),
          this.currentFilter,
        );
        this.loading = false;
      },
      error: () => (this.loading = false),
    });
  }

  setFilter(filter: ContentFeedFilter): void {
    this.currentFilter = filter;
    this.loadPosts();
  }

  getPopularityScore(post: ContentFeedPost): number {
    return getPopularityScore(post);
  }

  viewPost(id: string): void {
    this.router.navigate(['/p', id]);
  }
}

// src/app/links-feed.component.ts
@Component({
  selector: 'app-links-feed',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="card">
      <div class="filter-bar">
        <div>
          <h2 style="margin: 0;">Shared Links</h2>
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
        </div>
      </div>
    
      @if (loading) {
        <div class="muted">Loading links...</div>
      }
    
      @if (!loading && groups.length === 0) {
        <div class="muted">
          No links found.
        </div>
      }
    
      @for (group of groups; track group) {
        <div style="margin-bottom: 30px;">
          <div class="row" style="align-items: center; gap: 12px; margin-bottom: 12px;">
            <h3 style="color: #6366f1; font-size: 1.1rem; margin: 0;">{{ group.domain }}</h3>
            <span class="signal-pill">{{ group.posts.length }} mentions</span>
            <span class="signal-pill">Score {{ group.totalScore }}</span>
          </div>
          @for (post of group.posts; track post) {
            <div
              style="margin: 15px 0; padding-left: 15px; border-left: 3px solid #e5e7eb;">
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
  styles: [`
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

    .filter-buttons {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }

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

    .filter-btn:hover {
      background: #f9fafb;
      border-color: #6366f1;
    }

    .filter-btn.active {
      background: #6366f1;
      color: white;
      border-color: #6366f1;
    }

    .signal-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-left: auto;
    }

    .signal-pill {
      background: #eef2ff;
      color: #4338ca;
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 0.8rem;
      font-weight: 600;
      white-space: nowrap;
    }
  `]
})
export class LinksFeedComponent implements OnInit {
  private api = inject(ApiService);
  private router = inject(Router);

  groups: ContentFeedGroup[] = [];
  loading = true;
  currentFilter: ContentFeedFilter = 'recent';
  readonly filters = contentFeedFilters;

  ngOnInit(): void {
    this.api.identityId$.subscribe((identityId) => {
      if (identityId) {
        this.loadPosts();
      }
    });
  }

  loadPosts(): void {
    const identityId = this.api.getCurrentIdentityId();
    if (!identityId) {
      this.loading = false;
      return;
    }

    this.loading = true;
    const userFilter = getContentUserFilter(this.currentFilter);

    this.api.getPublicPosts(identityId, 'links', userFilter).subscribe({
      next: (page) => {
        const sortedPosts = sortContentPosts(
          page.items.map((post) => normalizeContentPost(post)),
          this.currentFilter,
        );
        this.groups = groupLinkPosts(sortedPosts, this.currentFilter);
        this.loading = false;
      },
      error: () => (this.loading = false),
    });
  }

  setFilter(filter: ContentFeedFilter): void {
    this.currentFilter = filter;
    this.loadPosts();
  }

  getPopularityScore(post: ContentFeedPost): number {
    return getPopularityScore(post);
  }

  viewPost(id: string): void {
    this.router.navigate(['/p', id]);
  }
}

// src/app/news-feed.component.ts
@Component({
  selector: 'app-news-feed',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="card">
      <div class="filter-bar">
        <div>
          <h2 style="margin: 0;">News Feed</h2>
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
        </div>
      </div>
    
      @if (loading) {
        <div class="muted">Loading news...</div>
      }
    
      @if (!loading && posts.length === 0) {
        <div class="muted">
          No news articles found.
        </div>
      }
    
      @for (post of posts; track post) {
        <div style="margin-bottom: 25px; padding: 15px; background: #f9fafb; border-radius: 8px;">
          <div class="row" style="margin-bottom: 10px;">
            <div style="display: flex; align-items: center; gap: 8px;">
              @if (post.author_avatar) {
                <img
                  [src]="post.author_avatar"
                  alt=""
                  style="width: 32px; height: 32px; border-radius: 50%;">
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
  styles: [`
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

    .filter-buttons {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }

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

    .filter-btn:hover {
      background: #f9fafb;
      border-color: #6366f1;
    }

    .filter-btn.active {
      background: #6366f1;
      color: white;
      border-color: #6366f1;
    }

    .signal-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      justify-content: flex-end;
      margin-left: auto;
    }

    .signal-pill {
      background: #eef2ff;
      color: #4338ca;
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 0.8rem;
      font-weight: 600;
      white-space: nowrap;
    }
  `]
})
export class NewsFeedComponent implements OnInit {
  private api = inject(ApiService);
  private router = inject(Router);

  posts: ContentFeedPost[] = [];
  loading = true;
  currentFilter: ContentFeedFilter = 'recent';
  readonly filters = contentFeedFilters;

  ngOnInit(): void {
    this.api.identityId$.subscribe((identityId) => {
      if (identityId) {
        this.loadPosts();
      }
    });
  }

  loadPosts(): void {
    const identityId = this.api.getCurrentIdentityId();
    if (!identityId) {
      this.loading = false;
      return;
    }

    this.loading = true;
    const userFilter = getContentUserFilter(this.currentFilter);

    this.api.getPublicPosts(identityId, 'news', userFilter).subscribe({
      next: (page) => {
        this.posts = sortContentPosts(
          page.items.map((post) => normalizeContentPost(post)),
          this.currentFilter,
        );
        this.loading = false;
      },
      error: () => (this.loading = false),
    });
  }

  setFilter(filter: ContentFeedFilter): void {
    this.currentFilter = filter;
    this.loadPosts();
  }

  getPopularityScore(post: ContentFeedPost): number {
    return getPopularityScore(post);
  }

  viewPost(id: string): void {
    this.router.navigate(['/p', id]);
  }
}
