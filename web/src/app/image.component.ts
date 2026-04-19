// src/app/image-feed.component.ts
import { Component, OnInit, OnDestroy, inject } from '@angular/core';
import { ApiService } from './api.service';
import { Router } from '@angular/router';
import { ContentHubStateService } from './content-hub-state.service';
import { combineLatest, Subscription } from 'rxjs';
import { ContentHubPost } from './mastodon';
import { RawContentPost } from './content-feed.utils';

interface ImagePost {
  id: string;
  content: string;
  created_at: string;
  author_acct: string;
  author_display_name: string;
  author_avatar: string;
  media_attachments: {
    type: string;
    url: string;
    preview_url?: string;
    description?: string;
  }[];
  counts: {
    likes: number;
    replies: number;
    reposts: number;
  };
}

@Component({
  selector: 'app-image-feed',
  standalone: true,
  imports: [],
  template: `
    <div class="image-feed-container">
      <div class="filter-bar">
        <h2 style="margin: 0;">{{ groupName ? groupName + ' — ' : '' }}Photo Gallery</h2>
        <div class="filter-buttons">
          @for (f of filters; track f) {
            <button
              [class.active]="currentFilter === f.value"
              (click)="setFilter(f.value)"
              class="filter-btn"
            >
              {{ f.label }}
            </button>
          }
          @if (groupId !== null) {
            <button (click)="fetchNew()" class="filter-btn" [disabled]="loading || refreshing">
              {{ refreshing ? 'Fetching...' : 'Fetch New' }}
            </button>
          }
        </div>
      </div>

      @if (loading) {
        <div class="loading-state">
          <div class="loading-spinner"></div>
          <p>Loading images...</p>
        </div>
      }

      @if (!loading && images.length === 0) {
        <div class="empty-state">
          <p style="color: #9ca3af; font-size: 1.1rem;">No images found</p>
        </div>
      }

      @if (!loading && images.length > 0) {
        <div class="image-grid">
          @for (post of images; track post) {
            <div
              class="image-card"
              (click)="viewPost(post)"
              (keydown.enter)="viewPost(post)"
              tabindex="0"
            >
              <div class="image-wrapper">
                <img
                  [src]="post.media_attachments[0].preview_url || post.media_attachments[0].url"
                  [alt]="post.media_attachments[0].description || 'Image'"
                  loading="lazy"
                />
                <div class="image-overlay">
                  <div class="overlay-stats">
                    <span>❤️ {{ post.counts.likes }}</span>
                    <span>💬 {{ post.counts.replies }}</span>
                  </div>
                </div>
              </div>
              <div class="image-meta">
                <div class="author-info">
                  <img [src]="post.author_avatar" alt="" class="author-avatar" />
                  <span class="author-name">{{
                    post.author_display_name || post.author_acct
                  }}</span>
                </div>
                @if (post.content) {
                  <div class="image-caption" [innerHTML]="stripHtml(post.content)"></div>
                }
              </div>
            </div>
          }
        </div>
      }
    </div>
  `,
  styles: [
    `
      .image-feed-container {
        background: white;
        border-radius: 8px;
        padding: 20px;
        border: 1px solid #e1e8ed;
      }

      .filter-bar {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 20px;
        padding-bottom: 15px;
        border-bottom: 2px solid #f3f4f6;
        flex-wrap: wrap;
        gap: 15px;
      }

      .filter-buttons {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
      }

      .filter-btn {
        padding: 6px 14px;
        background: white;
        border: 1px solid #d1d5db;
        border-radius: 20px;
        font-size: 0.85rem;
        cursor: pointer;
        transition: all 0.2s;
        color: #374151;
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

      .loading-state,
      .empty-state {
        text-align: center;
        padding: 60px 20px;
        color: #9ca3af;
      }

      .image-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
        gap: 20px;
      }

      .image-card {
        background: white;
        border-radius: 8px;
        overflow: hidden;
        border: 1px solid #e5e7eb;
        cursor: pointer;
        transition: all 0.3s ease;
      }

      .image-card:hover {
        transform: translateY(-4px);
        box-shadow: 0 8px 16px rgba(0, 0, 0, 0.1);
      }

      .image-wrapper {
        position: relative;
        padding-bottom: 100%;
        overflow: hidden;
        background: #f3f4f6;
      }

      .image-wrapper img {
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        object-fit: cover;
      }

      .image-overlay {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: linear-gradient(to bottom, transparent 60%, rgba(0, 0, 0, 0.7));
        opacity: 0;
        transition: opacity 0.3s;
        display: flex;
        align-items: flex-end;
        padding: 15px;
      }

      .image-card:hover .image-overlay {
        opacity: 1;
      }

      .overlay-stats {
        display: flex;
        gap: 15px;
        color: white;
        font-size: 0.9rem;
        font-weight: 500;
      }

      .image-meta {
        padding: 12px;
      }

      .author-info {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 8px;
      }
      .author-avatar {
        width: 24px;
        height: 24px;
        border-radius: 50%;
      }
      .author-name {
        font-size: 0.85rem;
        font-weight: 600;
        color: #374151;
      }

      .image-caption {
        font-size: 0.85rem;
        color: #6b7280;
        line-height: 1.4;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
      }

      @media (max-width: 768px) {
        .image-grid {
          grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
          gap: 10px;
        }
        .filter-bar {
          flex-direction: column;
          align-items: flex-start;
        }
      }
    `,
  ],
})
export class ImageFeedComponent implements OnInit, OnDestroy {
  private api = inject(ApiService);
  private router = inject(Router);
  private hubState = inject(ContentHubStateService);

  images: ImagePost[] = [];
  loading = true;
  refreshing = false;
  currentFilter = 'recent';
  groupName: string | null = null;
  groupId: number | null = null;

  filters = [
    { value: 'recent', label: 'Recent' },
    { value: 'popular', label: 'Popular' },
    { value: 'following', label: 'Following' },
    { value: 'everyone', label: 'Everyone' },
  ];

  private sub?: Subscription;

  ngOnInit(): void {
    this.sub = combineLatest([this.api.identityId$, this.hubState.activeGroup$]).subscribe(
      ([identityId, group]) => {
        this.groupId = group?.id ?? null;
        if (identityId) this.loadImages(identityId, group?.id ?? null, group?.name ?? null);
      },
    );
  }

  ngOnDestroy(): void {
    this.sub?.unsubscribe();
  }

  private loadImages(identityId: number, groupId: number | null, groupName: string | null): void {
    this.loading = true;
    this.groupName = groupName;

    if (groupId !== null) {
      // Hashtag group mode: fetch group posts, keep only those with images
      this.api.getContentHubGroupPosts(groupId, identityId, 'text', null, 100).subscribe({
        next: (res) => {
          this.images = res.items
            .filter((p) => this.hasImage(p))
            .map((p) => this.hubPostToImage(p));
          this.applySort();
          this.loading = false;
        },
        error: () => (this.loading = false),
      });
    } else {
      // Follows mode: existing behaviour
      const userFilter = this.currentFilter === 'everyone' ? 'everyone' : undefined;
      this.api.getPublicPosts(identityId, 'pictures', userFilter).subscribe({
        next: (page) => {
          this.images = page.items
            .filter((p) => p.media_attachments && p.media_attachments.length > 0)
            .map((p) => this.rawToImage(p));
          this.applySort();
          this.loading = false;
        },
        error: () => (this.loading = false),
      });
    }
  }

  setFilter(filter: string): void {
    this.currentFilter = filter;
    const identityId = this.api.getCurrentIdentityId();
    const group = this.hubState.getActiveGroup();
    if (identityId) this.loadImages(identityId, group?.id ?? null, group?.name ?? null);
  }

  fetchNew(): void {
    const identityId = this.api.getCurrentIdentityId();
    const group = this.hubState.getActiveGroup();
    if (!identityId || !group) return;
    this.refreshing = true;
    this.api.refreshContentHubGroup(group.id, identityId).subscribe({
      next: () => {
        this.refreshing = false;
        this.loadImages(identityId, group.id, group.name);
      },
      error: () => (this.refreshing = false),
    });
  }

  viewPost(post: ImagePost): void {
    this.router.navigate(['/p', post.id]);
  }

  stripHtml(html: string): string {
    return (html || '').replace(/<[^>]+>/g, '').trim();
  }

  private hasImage(p: ContentHubPost): boolean {
    const attachments = p.media_attachments as { type?: string; url?: string }[];
    return attachments.some((m) => m.type === 'image' || (!m.type && !!m.url));
  }

  private applySort(): void {
    if (this.currentFilter === 'popular') {
      this.images.sort((a, b) => b.counts.likes - a.counts.likes);
    } else {
      this.images.sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      );
    }
  }

  private rawToImage(p: RawContentPost): ImagePost {
    return {
      id: p.id,
      content: p.content ?? '',
      created_at: p.created_at,
      author_acct: p.author_acct,
      author_display_name: p.author_display_name || p.author_acct,
      author_avatar: p.author_avatar || '',
      media_attachments: (p.media_attachments ?? []) as ImagePost['media_attachments'],
      counts: {
        likes: p.counts?.likes ?? 0,
        replies: p.counts?.replies ?? 0,
        reposts: p.counts?.reposts ?? 0,
      },
    };
  }

  private hubPostToImage(p: ContentHubPost): ImagePost {
    const attachments = (p.media_attachments as ImagePost['media_attachments']).filter(
      (m) => m.type === 'image' || (!m.type && !!m.url),
    );
    return {
      id: p.id,
      content: p.content,
      created_at: p.created_at,
      author_acct: p.author_acct,
      author_display_name: p.author_display_name,
      author_avatar: p.author_avatar,
      media_attachments: attachments,
      counts: { likes: p.counts.likes, replies: p.counts.replies, reposts: p.counts.reblogs },
    };
  }
}
