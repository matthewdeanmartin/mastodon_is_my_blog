// src/app/forum.component.ts
import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { ApiService } from './api.service';

interface Discussion {
  id: string;
  root_post: any;
  participant_count: number;
  reply_count: number;
  latest_reply_at: string;
  participants: Array<{
    acct: string;
    display_name: string;
    avatar: string;
  }>;
}

@Component({
  selector: 'app-forum',
  standalone: true,
  imports: [CommonModule, RouterLink],
  template: `
    <div class="forum-container">
      <div class="forum-header">
        <h1 style="margin: 0;">Forum Discussions</h1>
        <p class="muted" style="margin: 8px 0 0 0;">
          Multi-person threads from your friends and mutuals
        </p>
      </div>

      <div class="filter-bar">
        <button
          *ngFor="let f of filters"
          [class.active]="currentFilter === f.value"
          (click)="setFilter(f.value)"
          class="filter-btn">
          {{ f.label }}
        </button>
      </div>

      <div *ngIf="loading" class="loading-state">
        <div class="loading-spinner"></div>
        <p>Loading discussions...</p>
      </div>

      <div *ngIf="!loading && discussions.length === 0" class="empty-state">
        <p>No active discussions found</p>
      </div>

      <div *ngIf="!loading && discussions.length > 0" class="discussions-list">
        <div *ngFor="let disc of discussions" class="discussion-card">
          <div class="discussion-header">
            <div class="participants">
              <img
                *ngFor="let p of disc.participants.slice(0, 5)"
                [src]="p.avatar"
                [title]="p.display_name || p.acct"
                class="participant-avatar">
              <span *ngIf="disc.participant_count > 5" class="more-count">
                +{{ disc.participant_count - 5 }}
              </span>
            </div>
            <div class="discussion-meta">
              <span class="reply-count">💬 {{ disc.reply_count }} replies</span>
              <span class="time-ago">{{ disc.latest_reply_at | date: 'short' }}</span>
            </div>
          </div>

          <div class="discussion-preview">
            <div class="author-line">
              <strong>{{ disc.root_post.author_display_name || disc.root_post.author_acct }}</strong>
              <span class="muted">started the conversation</span>
            </div>
            <div class="content-preview" [innerHTML]="stripHtml(disc.root_post.content)"></div>
          </div>

          <div class="discussion-footer">
            <a [routerLink]="['/p', disc.id]" class="view-thread-btn">
              View Full Thread →
            </a>
          </div>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .forum-container {
      max-width: 900px;
      margin: 0 auto;
    }

    .forum-header {
      background: white;
      padding: 30px;
      border-radius: 8px;
      border: 1px solid #e1e8ed;
      margin-bottom: 20px;
    }

    .filter-bar {
      display: flex;
      gap: 10px;
      margin-bottom: 20px;
      flex-wrap: wrap;
    }

    .filter-btn {
      padding: 8px 16px;
      background: white;
      border: 1px solid #d1d5db;
      border-radius: 20px;
      font-size: 0.9rem;
      cursor: pointer;
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

    .loading-state, .empty-state {
      text-align: center;
      padding: 60px 20px;
      background: white;
      border-radius: 8px;
      color: #9ca3af;
    }

    .discussions-list {
      display: flex;
      flex-direction: column;
      gap: 15px;
    }

    .discussion-card {
      background: white;
      border: 1px solid #e1e8ed;
      border-radius: 8px;
      padding: 20px;
      transition: all 0.2s;
    }

    .discussion-card:hover {
      box-shadow: 0 4px 12px rgba(0,0,0,0.08);
      border-color: #6366f1;
    }

    .discussion-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 15px;
      padding-bottom: 12px;
      border-bottom: 1px solid #f3f4f6;
    }

    .participants {
      display: flex;
      align-items: center;
      gap: -8px;
    }

    .participant-avatar {
      width: 32px;
      height: 32px;
      border-radius: 50%;
      border: 2px solid white;
      margin-left: -8px;
    }

    .participant-avatar:first-child {
      margin-left: 0;
    }

    .more-count {
      margin-left: 8px;
      font-size: 0.85rem;
      color: #6b7280;
      font-weight: 600;
    }

    .discussion-meta {
      display: flex;
      gap: 15px;
      font-size: 0.85rem;
      color: #6b7280;
    }

    .discussion-preview {
      margin-bottom: 15px;
    }

    .author-line {
      margin-bottom: 8px;
      font-size: 0.9rem;
    }

    .author-line strong {
      color: #374151;
    }

    .content-preview {
      color: #4b5563;
      line-height: 1.6;
      display: -webkit-box;
      -webkit-line-clamp: 3;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }

    .discussion-footer {
      display: flex;
      justify-content: flex-end;
    }

    .view-thread-btn {
      color: #6366f1;
      text-decoration: none;
      font-weight: 500;
      font-size: 0.9rem;
      transition: color 0.2s;
    }

    .view-thread-btn:hover {
      color: #4f46e5;
      text-decoration: underline;
    }

    @media (max-width: 768px) {
      .discussion-header {
        flex-direction: column;
        align-items: flex-start;
        gap: 10px;
      }
    }
  `]
})
export class ForumComponent implements OnInit {
  discussions: Discussion[] = [];
  loading = true;
  currentFilter = 'active';

  filters = [
    { value: 'active', label: 'Most Active' },
    { value: 'recent', label: 'Recent' },
    { value: 'friends', label: 'Friends Only' },
    { value: 'all', label: 'All Discussions' }
  ];

  constructor(private api: ApiService) {}

  ngOnInit(): void {
    const identityId = this.api.getCurrentIdentityId();
    if (!identityId) {
      this.loading = false;
      return;
    }

    this.loadDiscussions(identityId);
  }

  loadDiscussions(identityId: number): void {
    this.loading = true;

    // For now, we'll fetch discussions posts and simulate the grouping
    // In production, you'd have a dedicated API endpoint for this
    this.api.getPublicPosts(identityId, 'discussions', undefined).subscribe({
      next: (posts) => {
        // Simulate discussion threads (in reality, your backend would do this)
        this.discussions = posts.map(post => ({
          id: post.id,
          root_post: post,
          participant_count: Math.floor(Math.random() * 10) + 2,
          reply_count: post.counts?.replies || 0,
          latest_reply_at: post.created_at,
          participants: [
            {
              acct: post.author_acct,
              display_name: post.author_display_name || post.author_acct,
              avatar: post.author_avatar || ''
            }
          ]
        }));

        // Sort based on filter
        if (this.currentFilter === 'active') {
          this.discussions.sort((a, b) => b.reply_count - a.reply_count);
        } else {
          this.discussions.sort((a, b) =>
            new Date(b.latest_reply_at).getTime() - new Date(a.latest_reply_at).getTime()
          );
        }

        this.loading = false;
      },
      error: (err) => {
        console.error('Error loading discussions:', err);
        this.loading = false;
      }
    });
  }

  setFilter(filter: string): void {
    this.currentFilter = filter;
    const identityId = this.api.getCurrentIdentityId();
    if (identityId) {
      this.loadDiscussions(identityId);
    }
  }

  stripHtml(html: string): string {
    return (html || '').replace(/<[^>]+>/g, '').trim();
  }
}
