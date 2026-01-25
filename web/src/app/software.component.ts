// src/app/software-feed.component.ts
import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ApiService } from './api.service';
import { Router } from '@angular/router';

@Component({
  selector: 'app-software-feed',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="card">
      <h2>Cool Software Recommendations</h2>
      <p class="muted">Sorted by GitHub stars and community engagement</p>

      <div *ngIf="loading" class="muted">Loading software posts...</div>

      <div *ngIf="!loading && posts.length === 0" class="muted">
        No software recommendations found.
      </div>

      <div *ngFor="let post of posts" style="margin-bottom: 30px; padding-bottom: 20px; border-bottom: 1px solid #eee;">
        <div class="row">
          <strong>{{ post.author_display_name || post.author_acct }}</strong>
          <span class="muted">{{ post.created_at | date: 'short' }}</span>
        </div>
        <div [innerHTML]="post.content" style="margin: 10px 0;"></div>
        <button (click)="viewPost(post.id)" class="secondary">View Details</button>
      </div>
    </div>
  `
})
export class SoftwareFeedComponent implements OnInit {
  posts: any[] = [];
  loading = true;

  constructor(private api: ApiService, private router: Router) {}

  ngOnInit(): void {
    const identityId = this.api.getCurrentIdentityId();
    if (!identityId) return;

    this.api.getPublicPosts(identityId, 'software', undefined).subscribe({
      next: (posts) => {
        this.posts = posts;
        this.loading = false;
      },
      error: () => this.loading = false
    });
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
      <h2>Shared Links</h2>
      <p class="muted">Grouped by domain</p>

      <div *ngIf="loading" class="muted">Loading links...</div>

      <div *ngIf="!loading && Object.keys(linksByDomain).length === 0" class="muted">
        No links found.
      </div>

      <div *ngFor="let domain of Object.keys(linksByDomain)" style="margin-bottom: 30px;">
        <h3 style="color: #6366f1; font-size: 1.1rem;">{{ domain }} ({{ linksByDomain[domain].length }})</h3>
        <div *ngFor="let post of linksByDomain[domain]" style="margin: 15px 0; padding-left: 15px; border-left: 3px solid #e5e7eb;">
          <div class="muted">{{ post.author_display_name || post.author_acct }} • {{ post.created_at | date: 'short' }}</div>
          <div [innerHTML]="post.content" style="margin: 5px 0;"></div>
          <button (click)="viewPost(post.id)" class="secondary" style="margin-top: 8px;">View</button>
        </div>
      </div>
    </div>
  `
})
export class LinksFeedComponent implements OnInit {
  linksByDomain: { [domain: string]: any[] } = {};
  loading = true;

  constructor(private api: ApiService, private router: Router) {}

  ngOnInit(): void {
    const identityId = this.api.getCurrentIdentityId();
    if (!identityId) return;

    this.api.getPublicPosts(identityId, 'links', undefined).subscribe({
      next: (posts) => {
        // Group by domain (simplified - you'd extract domain from URLs in content)
        this.linksByDomain = posts.reduce((acc, post) => {
          const domain = this.extractDomain(post.content) || 'other';
          if (!acc[domain]) acc[domain] = [];
          acc[domain].push(post);
          return acc;
        }, {} as { [key: string]: any[] });

        this.loading = false;
      },
      error: () => this.loading = false
    });
  }

  extractDomain(content: string): string | null {
    const urlMatch = content.match(/https?:\/\/([^\/\s]+)/);
    return urlMatch ? urlMatch[1] : null;
  }

  viewPost(id: string): void {
    this.router.navigate(['/p', id]);
  }

  Object = Object;
}

// src/app/news-feed.component.ts
@Component({
  selector: 'app-news-feed',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="card">
      <h2>News Feed</h2>
      <p class="muted">Latest news articles shared by your network</p>

      <div *ngIf="loading" class="muted">Loading news...</div>

      <div *ngIf="!loading && posts.length === 0" class="muted">
        No news articles found.
      </div>

      <div *ngFor="let post of posts" style="margin-bottom: 25px; padding: 15px; background: #f9fafb; border-radius: 8px;">
        <div class="row" style="margin-bottom: 10px;">
          <div style="display: flex; align-items: center; gap: 8px;">
            <img [src]="post.author_avatar" style="width: 32px; height: 32px; border-radius: 50%;">
            <strong>{{ post.author_display_name || post.author_acct }}</strong>
          </div>
          <span class="muted">{{ post.created_at | date: 'short' }}</span>
        </div>
        <div [innerHTML]="post.content"></div>
        <button (click)="viewPost(post.id)" class="secondary" style="margin-top: 10px;">Read More</button>
      </div>
    </div>
  `
})
export class NewsFeedComponent implements OnInit {
  posts: any[] = [];
  loading = true;

  constructor(private api: ApiService, private router: Router) {}

  ngOnInit(): void {
    const identityId = this.api.getCurrentIdentityId();
    if (!identityId) return;

    this.api.getPublicPosts(identityId, 'news', undefined).subscribe({
      next: (posts) => {
        this.posts = posts;
        this.loading = false;
      },
      error: () => this.loading = false
    });
  }

  viewPost(id: string): void {
    this.router.navigate(['/p', id]);
  }
}
