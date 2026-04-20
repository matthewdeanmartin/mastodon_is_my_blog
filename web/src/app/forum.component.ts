// src/app/forum.component.ts
import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { ApiService } from './api.service';
import { ForumThread, ForumFacets } from './mastodon';

interface ActiveFacets {
  hashtags: Set<string>;
  uncommon_words: Set<string>;
  root_instances: Set<string>;
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
          Threads from your timeline — grouped by root post
        </p>
      </div>

      <div class="toolbar">
        <div class="filter-bar">
          @for (f of filters; track f.value) {
            <button
              [class.active]="currentFilter === f.value"
              (click)="setFilter(f.value)"
              class="filter-btn"
            >
              {{ f.label }}
            </button>
          }
        </div>
        <button
          class="content-hub-toggle"
          [class.active]="includeContentHub"
          (click)="toggleContentHub()"
          title="Content hub posts are fetched via hashtag subscriptions and are usually monologues, not discussions."
        >
          {{ includeContentHub ? '✓ ' : '' }}Content Hub
        </button>
      </div>

      <div class="main-layout">
        <!-- Thread list -->
        <div class="thread-list-col">
          @if (loading && threads.length === 0) {
            <div class="state-box">
              <div class="loading-spinner"></div>
              <p>Loading discussions…</p>
            </div>
          }

          @if (!loading && threads.length === 0) {
            <div class="state-box">
              <p>No threads found for this filter.</p>
            </div>
          }

          @if (error) {
            <div class="state-box error">
              <p>Failed to load discussions. Please try again.</p>
            </div>
          }

          @for (thread of threads; track thread.root_id) {
            <div class="thread-card">
              @if (thread.root_is_partial) {
                <span class="partial-badge">partial thread</span>
              }

              <div class="thread-meta">
                <span class="author">{{ thread.root_post.author_display_name || thread.root_post.author_acct }}</span>
                <span class="instance muted">{{ thread.root_post.author_instance }}</span>
                @if (thread.root_post.has_question) {
                  <span class="question-badge">?</span>
                }
                <span class="time muted">{{ thread.root_post.created_at | date: 'short' }}</span>
              </div>

              <div class="thread-content" [innerHTML]="thread.root_post.content"></div>

              <div class="thread-footer">
                <div class="repliers">
                  @if (thread.friend_reply_count > 0) {
                    <div class="friend-repliers">
                      @for (r of thread.friend_repliers.slice(0, 5); track r.acct) {
                        <img
                          [src]="r.avatar"
                          [title]="r.display_name || r.acct"
                          alt=""
                          class="replier-avatar"
                        />
                      }
                      <span class="reply-label">
                        {{ formatRepliers(thread) }}
                      </span>
                    </div>
                  } @else if (thread.reply_count > 0) {
                    <span class="reply-label muted">{{ thread.reply_count }} repl{{ thread.reply_count === 1 ? 'y' : 'ies' }} (no friends yet)</span>
                  }
                </div>

                <a [routerLink]="['/p', thread.root_id]" class="view-thread-btn">
                  View Full Thread →
                </a>
              </div>
            </div>
          }

          @if (nextCursor && !loading) {
            <button class="load-more-btn" (click)="loadMore()">Load more</button>
          }
          @if (loading && threads.length > 0) {
            <div class="state-box small">Loading…</div>
          }
        </div>

        <!-- Sidebar -->
        <aside class="sidebar">
          <details open class="sidebar-section">
            <summary>Hashtags in discussion</summary>
            <div class="chip-list">
              @for (h of facets.hashtags; track h.tag) {
                <button
                  class="chip"
                  [class.active]="activeFacets.hashtags.has(h.tag)"
                  (click)="toggleFacet('hashtags', h.tag)"
                >
                  #{{ h.tag }} <span class="chip-count">{{ h.count }}</span>
                  @if (activeFacets.hashtags.has(h.tag)) { <span class="remove">×</span> }
                </button>
              }
              @if (facets.hashtags.length === 0) {
                <span class="muted">—</span>
              }
            </div>
          </details>

          <details open class="sidebar-section">
            <summary>Uncommon words</summary>
            <div class="chip-list">
              @for (w of facets.uncommon_words; track w.word) {
                <button
                  class="chip"
                  [class.active]="activeFacets.uncommon_words.has(w.word)"
                  (click)="toggleFacet('uncommon_words', w.word)"
                >
                  {{ w.word }} <span class="chip-count">{{ w.thread_count }}</span>
                  @if (activeFacets.uncommon_words.has(w.word)) { <span class="remove">×</span> }
                </button>
              }
              @if (facets.uncommon_words.length === 0) {
                <span class="muted">—</span>
              }
            </div>
          </details>

          <details open class="sidebar-section">
            <summary>Root instance</summary>
            <div class="chip-list">
              @for (inst of facets.root_instances; track inst.instance) {
                <button
                  class="chip"
                  [class.active]="activeFacets.root_instances.has(inst.instance)"
                  (click)="toggleFacet('root_instances', inst.instance)"
                >
                  {{ inst.instance }} <span class="chip-count">{{ inst.count }}</span>
                  @if (activeFacets.root_instances.has(inst.instance)) { <span class="remove">×</span> }
                </button>
              }
              @if (facets.root_instances.length === 0) {
                <span class="muted">—</span>
              }
            </div>
          </details>
        </aside>
      </div>
    </div>
  `,
  styles: [
    `
      .forum-container {
        max-width: 1100px;
        margin: 0 auto;
        padding: 0 16px;
      }

      .forum-header {
        background: white;
        padding: 24px 30px;
        border-radius: 8px;
        border: 1px solid #e1e8ed;
        margin-bottom: 16px;
      }

      .toolbar {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 16px;
        flex-wrap: wrap;
      }

      .filter-bar {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        flex: 1;
      }

      .content-hub-toggle {
        padding: 6px 14px;
        background: white;
        color: #6b7280;
        border: 1px solid #d1d5db;
        border-radius: 20px;
        font-size: 0.875rem;
        cursor: pointer;
        white-space: nowrap;
        transition: all 0.15s;
        flex-shrink: 0;
      }

      .content-hub-toggle:hover {
        border-color: #6366f1;
        color: #374151;
      }

      .content-hub-toggle.active {
        background: #fef3c7;
        color: #92400e;
        border-color: #fde68a;
      }

      .filter-btn {
        padding: 6px 14px;
        background: white;
        color: #374151;
        border: 1px solid #d1d5db;
        border-radius: 20px;
        font-size: 0.875rem;
        cursor: pointer;
        transition: all 0.15s;
      }

      .filter-btn:hover {
        border-color: #6366f1;
      }

      .filter-btn.active {
        background: #6366f1;
        color: white;
        border-color: #6366f1;
      }

      .main-layout {
        display: flex;
        gap: 20px;
        align-items: flex-start;
      }

      .thread-list-col {
        flex: 1;
        min-width: 0;
        display: flex;
        flex-direction: column;
        gap: 12px;
      }

      .sidebar {
        width: 240px;
        flex-shrink: 0;
        display: flex;
        flex-direction: column;
        gap: 12px;
      }

      @media (max-width: 768px) {
        .main-layout {
          flex-direction: column-reverse;
        }
        .sidebar {
          width: 100%;
        }
      }

      .sidebar-section {
        background: white;
        border: 1px solid #e1e8ed;
        border-radius: 8px;
        padding: 12px 16px;
      }

      .sidebar-section summary {
        font-weight: 600;
        font-size: 0.85rem;
        cursor: pointer;
        margin-bottom: 8px;
        color: #374151;
      }

      .chip-list {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        margin-top: 8px;
      }

      .chip {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 3px 10px;
        background: #f3f4f6;
        border: 1px solid #e5e7eb;
        border-radius: 12px;
        font-size: 0.8rem;
        cursor: pointer;
        color: #374151;
        transition: all 0.15s;
      }

      .chip:hover {
        border-color: #6366f1;
      }

      .chip.active {
        background: #eef2ff;
        border-color: #6366f1;
        color: #4f46e5;
      }

      .chip-count {
        font-size: 0.75rem;
        color: #9ca3af;
      }

      .chip.active .chip-count {
        color: #6366f1;
      }

      .remove {
        margin-left: 2px;
        font-weight: bold;
      }

      .state-box {
        text-align: center;
        padding: 40px 20px;
        background: white;
        border-radius: 8px;
        border: 1px solid #e1e8ed;
        color: #9ca3af;
      }

      .state-box.error {
        color: #ef4444;
        border-color: #fecaca;
      }

      .state-box.small {
        padding: 16px;
      }

      .thread-card {
        background: white;
        border: 1px solid #e1e8ed;
        border-radius: 8px;
        padding: 16px 20px;
        position: relative;
        transition: box-shadow 0.15s, border-color 0.15s;
      }

      .thread-card:hover {
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
        border-color: #a5b4fc;
      }

      .partial-badge {
        display: inline-block;
        font-size: 0.7rem;
        background: #fef3c7;
        color: #92400e;
        border: 1px solid #fde68a;
        border-radius: 4px;
        padding: 1px 6px;
        margin-bottom: 8px;
      }

      .thread-meta {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 8px;
        flex-wrap: wrap;
      }

      .author {
        font-weight: 600;
        font-size: 0.9rem;
        color: #111827;
      }

      .instance {
        font-size: 0.8rem;
      }

      .time {
        font-size: 0.8rem;
        margin-left: auto;
      }

      .question-badge {
        background: #dbeafe;
        color: #1d4ed8;
        border-radius: 50%;
        width: 18px;
        height: 18px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-size: 0.75rem;
        font-weight: 700;
      }

      .thread-content {
        color: #374151;
        font-size: 0.9rem;
        line-height: 1.6;
        display: -webkit-box;
        -webkit-line-clamp: 3;
        -webkit-box-orient: vertical;
        overflow: hidden;
        margin-bottom: 12px;
      }

      .thread-footer {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding-top: 10px;
        border-top: 1px solid #f3f4f6;
      }

      .friend-repliers {
        display: flex;
        align-items: center;
        gap: 4px;
      }

      .replier-avatar {
        width: 24px;
        height: 24px;
        border-radius: 50%;
        border: 2px solid white;
        margin-left: -6px;
      }

      .replier-avatar:first-child {
        margin-left: 0;
      }

      .reply-label {
        font-size: 0.8rem;
        color: #6b7280;
        margin-left: 6px;
      }

      .view-thread-btn {
        color: #6366f1;
        text-decoration: none;
        font-weight: 500;
        font-size: 0.875rem;
        white-space: nowrap;
        flex-shrink: 0;
      }

      .view-thread-btn:hover {
        text-decoration: underline;
        color: #4f46e5;
      }

      .load-more-btn {
        padding: 10px;
        width: 100%;
        background: white;
        border: 1px solid #d1d5db;
        border-radius: 8px;
        cursor: pointer;
        color: #6366f1;
        font-size: 0.9rem;
        transition: background 0.15s;
      }

      .load-more-btn:hover {
        background: #f9fafb;
      }

      .muted {
        color: #9ca3af;
      }
    `,
  ],
})
export class ForumComponent implements OnInit {
  private api = inject(ApiService);

  threads: ForumThread[] = [];
  loading = true;
  error = false;
  currentFilter = 'recent';
  nextCursor: string | null = null;
  includeContentHub = false;

  facets: ForumFacets = { hashtags: [], uncommon_words: [], root_instances: [] };
  activeFacets: ActiveFacets = {
    hashtags: new Set(),
    uncommon_words: new Set(),
    root_instances: new Set(),
  };

  readonly filters = [
    { value: 'questions', label: 'Questions?' },
    { value: 'friends_started', label: 'Friends Started' },
    { value: 'popular', label: 'Popular' },
    { value: 'recent', label: 'Recent' },
    { value: 'mine', label: 'Mine' },
    { value: 'participating', label: 'Participating' },
  ];

  ngOnInit(): void {
    const identityId = this.api.getCurrentIdentityId();
    if (!identityId) {
      this.loading = false;
      return;
    }
    this.loadThreads(identityId, false);
  }

  setFilter(filter: string): void {
    this.currentFilter = filter;
    this.activeFacets = { hashtags: new Set(), uncommon_words: new Set(), root_instances: new Set() };
    this.threads = [];
    this.nextCursor = null;
    const identityId = this.api.getCurrentIdentityId();
    if (identityId) this.loadThreads(identityId, false);
  }

  toggleContentHub(): void {
    this.includeContentHub = !this.includeContentHub;
    this.threads = [];
    this.nextCursor = null;
    const identityId = this.api.getCurrentIdentityId();
    if (identityId) this.loadThreads(identityId, false);
  }

  toggleFacet(type: keyof ActiveFacets, value: string): void {
    const s = this.activeFacets[type];
    if (s.has(value)) {
      s.delete(value);
    } else {
      s.add(value);
    }
    this.threads = [];
    this.nextCursor = null;
    const identityId = this.api.getCurrentIdentityId();
    if (identityId) this.loadThreads(identityId, false);
  }

  loadMore(): void {
    const identityId = this.api.getCurrentIdentityId();
    if (identityId && this.nextCursor) this.loadThreads(identityId, true);
  }

  loadThreads(identityId: number, append: boolean): void {
    this.loading = true;
    this.error = false;

    this.api
      .getForumThreads(identityId, {
        top_filter: this.currentFilter,
        hashtag: [...this.activeFacets.hashtags],
        uncommon_word: [...this.activeFacets.uncommon_words],
        root_instance: [...this.activeFacets.root_instances],
        before: append ? this.nextCursor : null,
        include_content_hub: this.includeContentHub,
      })
      .subscribe({
        next: (resp) => {
          if (append) {
            this.threads = [...this.threads, ...resp.items];
          } else {
            this.threads = resp.items;
            this.facets = resp.facets;
          }
          this.nextCursor = resp.next_cursor;
          this.loading = false;
        },
        error: (err: unknown) => {
          console.error('Forum load error:', err);
          this.error = true;
          this.loading = false;
        },
      });
  }

  formatRepliers(thread: ForumThread): string {
    const names = thread.friend_repliers
      .slice(0, 3)
      .map((r) => `@${r.acct.split('@')[0]}`);
    const extra = thread.friend_reply_count - names.length;
    let label = names.join(', ');
    if (extra > 0) label += ` +${extra}`;
    return `${label} replied`;
  }
}
