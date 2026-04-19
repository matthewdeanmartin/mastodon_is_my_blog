// src/app/dossier.component.ts
import { Component, OnInit, OnDestroy, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { ApiService } from './api.service';
import { AccountCatchupStatus, Dossier, DossierInteraction, HeatmapCell } from './mastodon';
import { RawContentPost } from './content-feed.utils';
import { Subject, Subscription, interval } from 'rxjs';
import { takeUntil, switchMap } from 'rxjs/operators';

const DOW_LABELS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

interface HeatmapGridCell {
  dow: number;
  hour: number;
  count: number;
  color: string;
}

type PostsTab = 'recent' | 'popular';

@Component({
  selector: 'app-dossier',
  standalone: true,
  imports: [CommonModule, RouterLink],
  template: `
    <div class="dossier-page">
      @if (loading) {
        <div class="loading">Loading dossier…</div>
      }
      @if (error) {
        <div class="error-msg">{{ error }}</div>
        <div class="catchup-prompt">
          <p style="margin: 0 0 12px 0; font-size: 0.9rem; color: #374151;">
            To build a dossier, first run a Deep Catch Up to download this account's posts into your
            local cache.
          </p>
          <div class="catchup-btn-row">
            <button class="action-btn secondary" (click)="shallowFetchUnknown()" [disabled]="fetchBusy">
              {{ fetchBusy ? 'Starting…' : 'Catch Up' }}
            </button>
            <button class="action-btn secondary" (click)="deepFetchUnknown()" [disabled]="fetchBusy">
              {{ fetchBusy ? 'Starting…' : 'Deep Catch Up' }}
            </button>
          </div>
          @if (catchupStatus?.running) {
            <div style="margin-top: 8px; font-size: 0.84rem; color: #475569;">
              {{ catchupStatus!.stage }} — {{ catchupStatus!.posts_fetched }} posts across
              {{ catchupStatus!.pages_fetched }} page(s)
            </div>
          }
        </div>
      }

      @if (dossier) {
        <!-- Header -->
        <div class="dossier-header">
          @if (dossier.header) {
            <div
              class="header-banner"
              [style.backgroundImage]="'url(' + dossier.header + ')'"
            ></div>
          }
          <div class="header-body">
            <img class="avatar-lg" [src]="dossier.avatar" [alt]="dossier.display_name" />
            <div class="header-info">
              <h2>{{ dossier.display_name }}</h2>
              <p class="acct-line">
                <a [href]="dossier.url" target="_blank" rel="noopener noreferrer" class="acct-link">&#64;{{ dossier.acct }}</a>
              </p>
              <div class="stat-row">
                <span>{{ dossier.followers_count | number }} followers</span>
                <span>{{ dossier.following_count | number }} following</span>
                <span>{{ dossier.statuses_count | number }} posts</span>
              </div>
              @if (dossier.created_at) {
                <div class="joined-line">Joined {{ dossier.created_at | date: 'MMMM yyyy' }}</div>
              }
              @if (dossier.bot) {
                <span class="bot-badge">BOT</span>
              }
            </div>
            <div class="header-actions">
              <button
                class="action-btn"
                [class.following]="isFollowing"
                (click)="toggleFollow()"
                [disabled]="followBusy"
              >
                {{ followBusy ? '…' : isFollowing ? 'Unfollow' : 'Follow' }}
              </button>
              <button
                class="action-btn secondary"
                (click)="shallowFetch()"
                [disabled]="fetchBusy || catchupStatus?.running"
              >
                {{ fetchBusy ? 'Starting…' : catchupStatus?.running ? 'Running…' : 'Catch Up' }}
              </button>
              <button
                class="action-btn secondary"
                (click)="deepFetch()"
                [disabled]="fetchBusy || catchupStatus?.running"
              >
                {{
                  fetchBusy
                    ? 'Starting…'
                    : catchupStatus?.running
                      ? 'Deep Catch Up Running…'
                      : 'Deep Catch Up'
                }}
              </button>
              @if (catchupStatus?.running) {
                <button class="action-btn secondary" (click)="cancelCatchup()">Stop</button>
              }
            </div>
          </div>
        </div>

        <div style="margin: 10px 0 18px 0; font-size: 0.84rem; color: #64748b;">
          Deep Catch Up walks this account's full available history in the background so cached
          dossier stats can fill in over time.
        </div>
        @if (catchupError) {
          <div class="error-msg" style="padding-top: 0;">{{ catchupError }}</div>
        }
        @if (catchupStatus) {
          <div style="margin: 0 0 16px 0; font-size: 0.84rem; color: #475569;">
            @if (catchupStatus.running) {
              <span
                >{{ catchupStatus.stage }} — {{ catchupStatus.posts_fetched }} posts across
                {{ catchupStatus.pages_fetched }} page(s)</span
              >
            } @else {
              <span
                >Last catch-up fetched {{ catchupStatus.posts_fetched }} posts across
                {{ catchupStatus.pages_fetched }} page(s).</span
              >
            }
          </div>
        }

        <!-- Profile Fields -->
        @if (dossier.fields && dossier.fields.length > 0) {
          <div class="section">
            <h4>Profile Info</h4>
            <div class="fields-list">
              @for (field of dossier.fields; track field.name) {
                <div class="field-row" [class.field-verified]="field.verified_at">
                  <span class="field-name">{{ field.name }}</span>
                  <span class="field-value" [innerHTML]="sanitizeHtml(field.value)"></span>
                  @if (field.verified_at) {
                    <span class="verified-badge" title="Verified {{ field.verified_at | date }}">✓</span>
                  }
                </div>
              }
            </div>
          </div>
        }

        <!-- Note -->
        @if (dossier.note) {
          <div class="section">
            <div
              class="note-body"
              [class.note-collapsed]="!noteExpanded"
              [innerHTML]="dossier.note"
            ></div>
            <button class="note-toggle" (click)="noteExpanded = !noteExpanded">
              {{ noteExpanded ? 'Show less ▲' : 'Show more ▼' }}
            </button>
          </div>
        }

        <!-- Top Hashtags -->
        @if (dossier.top_hashtags.length > 0) {
          <div class="section">
            <h4>Hashtags</h4>
            <div class="hashtag-chips">
              @for (ht of dossier.top_hashtags; track ht.tag) {
                <a
                  class="hashtag-chip"
                  [href]="hashtagUrl(ht.tag)"
                  target="_blank"
                  rel="noopener noreferrer"
                  title="{{ ht.count }} posts"
                >#{{ ht.tag }} <span class="chip-count">{{ ht.count }}</span></a
                >
              }
            </div>
          </div>
        }

        <!-- Posting Heatmap -->
        <div class="section">
          <h4>Posting Heatmap</h4>
          @if (heatmapLoading) {
            <div style="color: #9ca3af; font-size: 0.84rem;">Loading…</div>
          }
          @if (heatmapError) {
            <div style="color: #dc2626; font-size: 0.84rem;">{{ heatmapError }}</div>
          }
          @if (!heatmapLoading && heatmapCells.length === 0 && !heatmapError) {
            <div style="color: #9ca3af; font-style: italic; font-size: 0.84rem;">No post activity in cache yet.</div>
          }
          @if (heatmapCells.length > 0) {
            <div class="heatmap-wrap">
              <div class="heatmap-hours-row">
                <div class="heatmap-corner"></div>
                @for (h of hours; track h) {
                  <div class="heatmap-hour-label">{{ h % 6 === 0 ? hourLabel(h) : '' }}</div>
                }
              </div>
              @for (row of heatmapGrid; track $index) {
                <div class="heatmap-row">
                  <div class="heatmap-dow-label">{{ dowLabel($index) }}</div>
                  @for (cell of row; track $index) {
                    <div
                      class="heatmap-cell"
                      [style.background]="cell.color"
                      [title]="dowLabel(cell.dow) + ' ' + hourLabel(cell.hour) + ':00 — ' + cell.count + ' posts'"
                    ></div>
                  }
                </div>
              }
            </div>
          }
        </div>

        <!-- Interaction History -->
        <div class="section">
          <h4>Interaction History</h4>
          <div class="interaction-grid">
            @for (window of interactionWindows; track window.label) {
              <div class="interaction-cell">
                <span class="window-label">{{ window.label }}</span>
                <div class="bar-row">
                  <span class="bar-label">Them → Me</span>
                  <div class="bar-track">
                    <div
                      class="bar them"
                      [style.width.%]="barWidth(window.them_to_me, window.max)"
                    ></div>
                  </div>
                  <span class="bar-count">{{ window.them_to_me }}</span>
                </div>
                <div class="bar-row">
                  <span class="bar-label">Me → Them</span>
                  <div class="bar-track">
                    <div
                      class="bar me"
                      [style.width.%]="barWidth(window.me_to_them, window.max)"
                    ></div>
                  </div>
                  <span class="bar-count">{{ window.me_to_them }}</span>
                </div>
              </div>
            }
          </div>
        </div>

        <!-- Messages / Interactions from them -->
        <div class="section">
          <h4>Messages from them</h4>
          @if (interactionsLoading) {
            <div style="color: #9ca3af; font-size: 0.84rem;">Loading…</div>
          }
          @if (!interactionsLoading && interactions.length === 0) {
            <div style="color: #9ca3af; font-style: italic; font-size: 0.84rem;">No cached notifications from this person.</div>
          }
          <div class="posts-list">
            @for (n of interactions; track n.notification_id) {
              <div class="post-card">
                <div class="post-meta">
                  <span class="notif-type-badge notif-{{ n.type }}">{{ n.type }}</span>
                  <span class="post-date">{{ n.created_at | date: 'MMM d, yyyy' }}</span>
                  <a [routerLink]="['/p', n.status_id]" class="view-link">View →</a>
                </div>
                @if (n.content) {
                  <div class="post-body" [innerHTML]="sanitizeHtml(n.content)"></div>
                } @else {
                  <div class="post-body" style="color: #9ca3af; font-style: italic;">Post not in local cache</div>
                }
              </div>
            }
          </div>
        </div>

        <!-- Post/Reply Ratio -->
        @if (dossier.post_reply_ratio !== null) {
          <div class="section">
            <h4>Post/Reply Ratio</h4>
            <p class="ratio-value">
              {{ dossier.post_reply_ratio | number: '1.1-1' }}x more posts than replies
            </p>
          </div>
        }

        <!-- Media Profile -->
        <div class="section">
          <h4>Content Mix</h4>
          <div class="media-grid">
            <div class="media-cell">
              <span class="media-pct"
                >{{ pct(dossier.media_profile.has_media, dossier.media_profile.total) }}%</span
              >
              <span class="media-label">Images</span>
            </div>
            <div class="media-cell">
              <span class="media-pct"
                >{{ pct(dossier.media_profile.has_video, dossier.media_profile.total) }}%</span
              >
              <span class="media-label">Video</span>
            </div>
            <div class="media-cell">
              <span class="media-pct"
                >{{ pct(dossier.media_profile.has_link, dossier.media_profile.total) }}%</span
              >
              <span class="media-label">Links</span>
            </div>
            <div class="media-cell">
              <span class="media-pct">{{ dossier.media_profile.total }}</span>
              <span class="media-label">Total cached</span>
            </div>
          </div>
        </div>

        <!-- Posts -->
        <div class="section">
          <div class="posts-header">
            <h4>Posts</h4>
            <div class="posts-tabs">
              <button
                class="tab-btn"
                [class.active]="postsTab === 'recent'"
                (click)="setPostsTab('recent')"
              >Recent</button>
              <button
                class="tab-btn"
                [class.active]="postsTab === 'popular'"
                (click)="setPostsTab('popular')"
              >Popular</button>
            </div>
          </div>
          @if (postsLoading) {
            <div style="color: #9ca3af; font-size: 0.84rem; padding: 8px 0;">Loading posts…</div>
          }
          @if (!postsLoading && displayedPosts.length === 0) {
            <div style="color: #9ca3af; font-style: italic; font-size: 0.84rem; padding: 8px 0;">No cached posts found.</div>
          }
          <div class="posts-list">
            @for (post of displayedPosts; track post.id) {
              <div class="post-card">
                <div class="post-meta">
                  <span class="post-date">{{ post.created_at | date: 'MMM d, yyyy' }}</span>
                  @if (post.counts) {
                    <span class="post-counts">
                      @if (post.counts.replies) { 💬 {{ post.counts.replies }} }
                      @if (post.counts.reposts) { 🔁 {{ post.counts.reposts }} }
                      @if (post.counts.likes) { ⭐ {{ post.counts.likes }} }
                    </span>
                  }
                  <a [routerLink]="['/p', post.id]" class="view-link">View →</a>
                </div>
                <div class="post-body" [innerHTML]="sanitizeHtml(post.content ?? '')"></div>
              </div>
            }
          </div>
        </div>
      }
    </div>
  `,
  styles: [
    `
      .dossier-page {
        padding: 24px;
        max-width: 900px;
        margin: 0 auto;
      }
      .loading,
      .error-msg {
        padding: 24px;
        text-align: center;
        color: #6b7280;
      }
      .error-msg {
        color: #dc2626;
      }
      .catchup-prompt {
        margin-top: 16px;
        padding: 16px;
        background: white;
        border: 1px solid #e1e8ed;
        border-radius: 8px;
      }
      .catchup-btn-row {
        display: flex;
        gap: 8px;
      }
      .dossier-header {
        background: white;
        border: 1px solid #e1e8ed;
        border-radius: 8px;
        overflow: hidden;
        margin-bottom: 20px;
      }
      .header-banner {
        height: 100px;
        background-size: cover;
        background-position: center;
      }
      .header-body {
        display: flex;
        align-items: flex-start;
        gap: 16px;
        padding: 16px;
      }
      .avatar-lg {
        width: 72px;
        height: 72px;
        border-radius: 8px;
        object-fit: cover;
        flex-shrink: 0;
        border: 3px solid white;
        margin-top: -36px;
      }
      .header-info {
        flex: 1;
      }
      .header-info h2 {
        margin: 0 0 2px 0;
        font-size: 1.2rem;
        color: #1f2937;
      }
      .acct-line {
        color: #6b7280;
        margin: 0 0 4px 0;
      }
      .joined-line {
        color: #9ca3af;
        font-size: 0.78rem;
        margin: 2px 0 4px 0;
      }
      .stat-row {
        display: flex;
        gap: 16px;
        font-size: 0.82rem;
        color: #374151;
      }
      .bot-badge {
        font-size: 0.65rem;
        background: #fef3c7;
        color: #92400e;
        padding: 2px 6px;
        border-radius: 4px;
        margin-top: 4px;
        display: inline-block;
      }
      .header-actions {
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      .action-btn {
        padding: 7px 16px;
        border-radius: 6px;
        border: 1px solid #6366f1;
        background: #6366f1;
        color: white;
        cursor: pointer;
        font-size: 0.85rem;
        font-weight: 600;
        transition: background 0.1s;
      }
      .action-btn:hover {
        background: #4f46e5;
        border-color: #4f46e5;
      }
      .action-btn:disabled {
        opacity: 0.5;
        cursor: default;
      }
      .action-btn.following {
        background: #dbeafe;
        border-color: #93c5fd;
        color: #1e40af;
      }
      .action-btn.following:hover {
        background: #bfdbfe;
      }
      .action-btn.secondary {
        background: #f9fafb;
        border-color: #d1d5db;
        color: #374151;
      }
      .action-btn.secondary:hover {
        background: #f3f4f6;
      }
      .section {
        background: white;
        border: 1px solid #e1e8ed;
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 16px;
      }
      .section h4 {
        margin: 0 0 12px 0;
        color: #374151;
      }
      /* Profile fields */
      .fields-list {
        display: flex;
        flex-direction: column;
        gap: 6px;
      }
      .field-row {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 6px 10px;
        border-radius: 6px;
        background: #f9fafb;
        font-size: 0.85rem;
      }
      .field-row.field-verified {
        background: #dcfce7;
        border: 1px solid #86efac;
      }
      .field-name {
        font-weight: 600;
        color: #374151;
        min-width: 100px;
        flex-shrink: 0;
      }
      .field-value {
        flex: 1;
        color: #1d4ed8;
        word-break: break-all;
      }
      .verified-badge {
        color: #16a34a;
        font-weight: 700;
        font-size: 0.9rem;
      }
      /* Interaction history */
      .interaction-grid {
        display: flex;
        gap: 16px;
        flex-wrap: wrap;
      }
      .interaction-cell {
        flex: 1;
        min-width: 180px;
        background: #f9fafb;
        border-radius: 6px;
        padding: 10px;
      }
      .window-label {
        font-size: 0.75rem;
        font-weight: 700;
        color: #9ca3af;
        text-transform: uppercase;
      }
      .bar-row {
        display: flex;
        align-items: center;
        gap: 6px;
        margin-top: 6px;
      }
      .bar-label {
        font-size: 0.72rem;
        color: #6b7280;
        width: 70px;
        flex-shrink: 0;
      }
      .bar-track {
        flex: 1;
        height: 8px;
        background: #e5e7eb;
        border-radius: 4px;
        overflow: hidden;
      }
      .bar {
        height: 100%;
        border-radius: 4px;
      }
      .bar.them {
        background: #3b82f6;
      }
      .bar.me {
        background: #10b981;
      }
      .bar-count {
        font-size: 0.72rem;
        color: #374151;
        width: 24px;
        text-align: right;
      }
      .ratio-value {
        color: #374151;
        margin: 0;
      }
      /* Hashtags */
      .hashtag-chips {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }
      .hashtag-chip {
        background: #eff6ff;
        color: #1d4ed8;
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 0.82rem;
        text-decoration: none;
        cursor: pointer;
        transition: background 0.1s;
      }
      .hashtag-chip:hover {
        background: #dbeafe;
      }
      .chip-count {
        background: #dbeafe;
        color: #1e40af;
        padding: 0 5px;
        border-radius: 6px;
        font-size: 0.72rem;
        margin-left: 4px;
      }
      /* Media grid */
      .media-grid {
        display: flex;
        gap: 20px;
        flex-wrap: wrap;
      }
      .media-cell {
        text-align: center;
      }
      .media-pct {
        display: block;
        font-size: 1.4rem;
        font-weight: 700;
        color: #1f2937;
      }
      .media-label {
        font-size: 0.75rem;
        color: #6b7280;
      }
      /* Note */
      .note-body {
        font-size: 0.92rem;
        color: #374151;
        line-height: 1.6;
      }
      .note-collapsed {
        max-height: calc(1.6em * 10);
        overflow: hidden;
      }
      .note-toggle {
        margin-top: 6px;
        background: none;
        border: none;
        color: #6366f1;
        font-size: 0.82rem;
        cursor: pointer;
        padding: 0;
      }
      .note-toggle:hover {
        text-decoration: underline;
      }
      /* Heatmap */
      .heatmap-wrap {
        overflow-x: auto;
      }
      .heatmap-hours-row {
        display: flex;
      }
      .heatmap-corner {
        width: 32px;
        flex-shrink: 0;
      }
      .heatmap-hour-label {
        width: 14px;
        font-size: 0.6rem;
        color: #9ca3af;
        text-align: center;
        flex-shrink: 0;
        white-space: nowrap;
        overflow: hidden;
      }
      .heatmap-row {
        display: flex;
        align-items: center;
      }
      .heatmap-dow-label {
        width: 32px;
        font-size: 0.68rem;
        color: #9ca3af;
        flex-shrink: 0;
      }
      .heatmap-cell {
        width: 14px;
        height: 14px;
        border-radius: 2px;
        margin: 1px;
        flex-shrink: 0;
      }
      /* Posts */
      .posts-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 12px;
      }
      .posts-header h4 {
        margin: 0;
      }
      .posts-tabs {
        display: flex;
        gap: 4px;
      }
      .tab-btn {
        padding: 4px 12px;
        border-radius: 6px;
        border: 1px solid #d1d5db;
        background: white;
        color: #6b7280;
        font-size: 0.8rem;
        cursor: pointer;
      }
      .tab-btn.active {
        background: #6366f1;
        border-color: #6366f1;
        color: white;
        font-weight: 600;
      }
      .tab-btn:hover:not(.active) {
        background: #f3f4f6;
      }
      .posts-list {
        display: flex;
        flex-direction: column;
        gap: 10px;
      }
      .post-card {
        border: 1px solid #e5e7eb;
        border-radius: 6px;
        padding: 10px 12px;
        background: #f9fafb;
      }
      .post-meta {
        display: flex;
        gap: 12px;
        margin-bottom: 6px;
        font-size: 0.75rem;
        color: #9ca3af;
      }
      .post-counts {
        display: flex;
        gap: 8px;
      }
      .post-body {
        font-size: 0.88rem;
        color: #1f2937;
        line-height: 1.55;
      }
      .post-body a {
        color: #1d4ed8;
      }
      .acct-link {
        color: #6b7280;
        text-decoration: none;
      }
      .acct-link:hover {
        text-decoration: underline;
        color: #374151;
      }
      .view-link {
        color: #6366f1;
        font-size: 0.75rem;
        text-decoration: none;
        margin-left: auto;
      }
      .view-link:hover {
        text-decoration: underline;
      }
      .notif-type-badge {
        font-size: 0.7rem;
        font-weight: 600;
        padding: 1px 6px;
        border-radius: 4px;
        text-transform: uppercase;
        background: #e5e7eb;
        color: #374151;
      }
      .notif-mention {
        background: #e0e7ff;
        color: #4338ca;
      }
      .notif-favourite {
        background: #fef3c7;
        color: #92400e;
      }
      .notif-reblog {
        background: #d1fae5;
        color: #065f46;
      }
      .notif-follow {
        background: #fce7f3;
        color: #9d174d;
      }
    `,
  ],
})
export class DossierComponent implements OnInit, OnDestroy {
  private api = inject(ApiService);
  private route = inject(ActivatedRoute);
  private sanitizer = inject(DomSanitizer);
  private destroy$ = new Subject<void>();
  private catchupPollSub?: Subscription;

  dossier: Dossier | null = null;
  loading = true;
  error: string | null = null;
  noteExpanded = false;
  followBusy = false;
  fetchBusy = false;
  catchupError: string | null = null;
  catchupStatus: AccountCatchupStatus | null = null;
  isFollowing = false;

  heatmapCells: HeatmapCell[] = [];
  heatmapLoading = false;
  heatmapError: string | null = null;
  readonly hours = Array.from({ length: 24 }, (_u, h) => h);

  allPosts: RawContentPost[] = [];
  postsLoading = false;
  postsTab: PostsTab = 'recent';

  interactions: DossierInteraction[] = [];
  interactionsLoading = false;

  interactionWindows: {
    label: string;
    them_to_me: number;
    me_to_them: number;
    max: number;
  }[] = [];

  get displayedPosts(): RawContentPost[] {
    if (this.postsTab === 'popular') {
      return [...this.allPosts]
        .sort((a, b) => {
          const scoreA =
            (a.counts?.likes ?? 0) + (a.counts?.reposts ?? 0) * 3 + (a.counts?.replies ?? 0) * 2;
          const scoreB =
            (b.counts?.likes ?? 0) + (b.counts?.reposts ?? 0) * 3 + (b.counts?.replies ?? 0) * 2;
          return scoreB - scoreA;
        })
        .slice(0, 20);
    }
    return this.allPosts.slice(0, 20);
  }

  get heatmapMax(): number {
    let max = 0;
    for (const c of this.heatmapCells) if (c.count > max) max = c.count;
    return max;
  }

  get heatmapGrid(): HeatmapGridCell[][] {
    const map = new Map<string, number>();
    for (const c of this.heatmapCells) map.set(`${c.dow}:${c.hour}`, c.count);
    const max = this.heatmapMax;
    const grid: HeatmapGridCell[][] = [];
    for (let dow = 0; dow < 7; dow++) {
      const row: HeatmapGridCell[] = [];
      for (let hour = 0; hour < 24; hour++) {
        const count = map.get(`${dow}:${hour}`) ?? 0;
        row.push({ dow, hour, count, color: this.heatmapColor(count, max) });
      }
      grid.push(row);
    }
    return grid;
  }

  private heatmapColor(count: number, max: number): string {
    if (count === 0 || max === 0) return '#f1f5f9';
    const t = Math.log1p(count) / Math.log1p(max);
    return this.lerpColor('#e0e7ff', '#6366f1', Math.min(1, Math.max(0.08, t)));
  }

  private lerpColor(a: string, b: string, t: number): string {
    const ax = parseInt(a.slice(1), 16);
    const bx = parseInt(b.slice(1), 16);
    const r = Math.round(((ax >> 16) & 255) + (((bx >> 16) & 255) - ((ax >> 16) & 255)) * t);
    const g = Math.round(((ax >> 8) & 255) + (((bx >> 8) & 255) - ((ax >> 8) & 255)) * t);
    const bl = Math.round((ax & 255) + ((bx & 255) - (ax & 255)) * t);
    return `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${bl.toString(16).padStart(2, '0')}`;
  }

  dowLabel(dow: number): string {
    return DOW_LABELS[dow] ?? '';
  }

  hourLabel(h: number): string {
    if (h === 0) return '12a';
    if (h < 12) return `${h}a`;
    if (h === 12) return '12p';
    return `${h - 12}p`;
  }

  hashtagUrl(tag: string): string {
    if (this.dossier?.url) {
      try {
        const base = new URL(this.dossier.url).origin;
        return `${base}/tags/${tag}`;
      } catch {
        // fall through
      }
    }
    return `https://mastodon.social/tags/${tag}`;
  }

  sanitizeHtml(html: string): SafeHtml {
    return this.sanitizer.bypassSecurityTrustHtml(html);
  }

  ngOnInit(): void {
    const acct = this.route.snapshot.paramMap.get('acct') ?? '';
    this.api.identityId$.pipe(takeUntil(this.destroy$)).subscribe((id) => {
      if (id) {
        this.loadDossier(acct, id);
        this.loadCatchupStatus(acct, id);
        this.loadHeatmap(acct, id);
        this.loadPosts(acct, id);
        this.loadInteractions(acct, id);
      }
    });
  }

  ngOnDestroy(): void {
    this.catchupPollSub?.unsubscribe();
    this.destroy$.next();
    this.destroy$.complete();
  }

  setPostsTab(tab: PostsTab): void {
    this.postsTab = tab;
  }

  private loadHeatmap(acct: string, identityId: number): void {
    this.heatmapLoading = true;
    this.heatmapError = null;
    this.api
      .getPostingHeatmap(identityId, acct)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (cells) => {
          this.heatmapCells = cells;
          this.heatmapLoading = false;
        },
        error: (err: unknown) => {
          this.heatmapLoading = false;
          this.heatmapError =
            (err as { error?: { detail?: string } })?.error?.detail ?? 'Failed to load heatmap';
        },
      });
  }

  private loadPosts(acct: string, identityId: number): void {
    this.postsLoading = true;
    this.api
      .getPublicPosts(identityId, 'all', acct, null, 20)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (page) => {
          this.allPosts = page.items;
          this.postsLoading = false;
        },
        error: () => {
          this.allPosts = [];
          this.postsLoading = false;
        },
      });
  }

  private loadInteractions(acct: string, identityId: number): void {
    this.interactionsLoading = true;
    this.api
      .getDossierInteractions(acct, identityId)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (items) => {
          this.interactions = items;
          this.interactionsLoading = false;
        },
        error: () => {
          this.interactions = [];
          this.interactionsLoading = false;
        },
      });
  }

  shallowFetchUnknown(): void {
    this.startFetchUnknown('recent');
  }

  deepFetchUnknown(): void {
    this.startFetchUnknown('deep');
  }

  private startFetchUnknown(mode: 'recent' | 'deep'): void {
    const acct = this.route.snapshot.paramMap.get('acct') ?? '';
    const id = this.api.getCurrentIdentityId();
    if (!id || !acct) return;
    this.fetchBusy = true;
    this.catchupError = null;
    this.api
      .startAccountCatchup(acct, id, mode)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (status) => {
          this.catchupStatus = status;
          this.fetchBusy = false;
          if (status.running) {
            this.startCatchupPollingUnknown(acct, id);
          }
        },
        error: () => {
          this.fetchBusy = false;
          this.catchupError = 'Failed to start catch-up.';
        },
      });
  }

  private startCatchupPollingUnknown(acct: string, identityId: number): void {
    this.catchupPollSub?.unsubscribe();
    this.catchupPollSub = interval(2000)
      .pipe(
        takeUntil(this.destroy$),
        switchMap(() => this.api.getAccountCatchupStatus(acct, identityId)),
      )
      .subscribe({
        next: (status) => {
          this.catchupStatus = status;
          this.catchupError = status.error;
          if (!status.running) {
            this.catchupPollSub?.unsubscribe();
            this.catchupPollSub = undefined;
            this.loadDossier(acct, identityId);
          }
        },
        error: () => {
          this.catchupPollSub?.unsubscribe();
          this.catchupPollSub = undefined;
        },
      });
  }

  loadDossier(acct: string, identityId: number): void {
    this.loading = true;
    this.error = null;
    this.api
      .getDossier(acct, identityId)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (d) => {
          this.dossier = d;
          this.isFollowing = d.is_following;
          this.buildInteractionWindows(d);
          this.loading = false;
        },
        error: (e: unknown) => {
          this.error = 'No cached data found for this account yet.';
          this.loading = false;
          console.error(e);
        },
      });
  }

  buildInteractionWindows(d: Dossier): void {
    this.interactionWindows = Object.entries(d.interaction_history).map(([label, v]) => ({
      label,
      them_to_me: v.them_to_me,
      me_to_them: v.me_to_them,
      max: Math.max(v.them_to_me, v.me_to_them, 1),
    }));
  }

  barWidth(value: number, max: number): number {
    if (max === 0) return 0;
    return Math.round((value / max) * 100);
  }

  pct(part: number, total: number): number {
    if (total === 0) return 0;
    return Math.round((part / total) * 100);
  }

  toggleFollow(): void {
    if (!this.dossier) return;
    const id = this.api.getCurrentIdentityId();
    if (!id) return;
    this.followBusy = true;
    const action$ = this.isFollowing
      ? this.api.unfollowAccount(this.dossier.acct, id)
      : this.api.followAccount(this.dossier.acct, id);

    action$.pipe(takeUntil(this.destroy$)).subscribe({
      next: () => {
        this.isFollowing = !this.isFollowing;
        if (this.dossier) this.dossier.is_following = this.isFollowing;
        this.followBusy = false;
      },
      error: (e: unknown) => {
        console.error('Follow/unfollow failed', e);
        this.followBusy = false;
      },
    });
  }

  shallowFetch(): void {
    this.startFetch('recent');
  }

  deepFetch(): void {
    this.startFetch('deep');
  }

  private startFetch(mode: 'recent' | 'deep'): void {
    if (!this.dossier) return;
    const id = this.api.getCurrentIdentityId();
    if (!id) return;
    this.fetchBusy = true;
    this.catchupError = null;
    this.api
      .startAccountCatchup(this.dossier.acct, id, mode)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (status) => {
          this.catchupStatus = status;
          this.fetchBusy = false;
          if (status.running) {
            this.startCatchupPolling(this.dossier!.acct, id);
          }
        },
        error: (e: unknown) => {
          console.error('Fetch failed', e);
          this.fetchBusy = false;
          this.catchupError = 'Failed to start catch-up.';
        },
      });
  }

  cancelCatchup(): void {
    if (!this.dossier) return;
    const id = this.api.getCurrentIdentityId();
    if (!id) return;

    this.api
      .cancelAccountCatchup(this.dossier.acct, id)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: () => this.loadCatchupStatus(this.dossier!.acct, id),
        error: (e: unknown) => {
          console.error('Cancel catch-up failed', e);
          this.catchupError = 'Failed to stop catch-up.';
        },
      });
  }

  private loadCatchupStatus(acct: string, identityId: number): void {
    this.api
      .getAccountCatchupStatus(acct, identityId)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (status) => {
          this.catchupStatus = status;
          this.catchupError = status.error;
          if (status.running) {
            this.startCatchupPolling(acct, identityId);
          } else {
            this.catchupPollSub?.unsubscribe();
            this.catchupPollSub = undefined;
          }
        },
        error: (e: unknown) => {
          const httpError = e as { status?: number; error?: { detail?: string } };
          if (httpError.status === 404) {
            this.catchupStatus = null;
            this.catchupError = null;
            return;
          }

          this.catchupError = httpError.error?.detail ?? 'Failed to load catch-up status.';
        },
      });
  }

  private startCatchupPolling(acct: string, identityId: number): void {
    this.catchupPollSub?.unsubscribe();
    this.catchupPollSub = interval(2000)
      .pipe(
        takeUntil(this.destroy$),
        switchMap(() => this.api.getAccountCatchupStatus(acct, identityId)),
      )
      .subscribe({
        next: (status) => {
          this.catchupStatus = status;
          this.catchupError = status.error;
          if (!status.running) {
            this.catchupPollSub?.unsubscribe();
            this.catchupPollSub = undefined;
            this.api.refreshNeeded$.next();
            this.loadDossier(acct, identityId);
          }
        },
        error: (e: unknown) => {
          console.error('Catch-up status failed', e);
          this.catchupPollSub?.unsubscribe();
          this.catchupPollSub = undefined;
        },
      });
  }
}
