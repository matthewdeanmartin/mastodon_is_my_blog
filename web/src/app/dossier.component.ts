// src/app/dossier.component.ts
import { Component, OnInit, OnDestroy, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { ApiService } from './api.service';
import {
  AccountCatchupStatus,
  Dossier,
  DossierInteraction,
  HeatmapCell,
  MastodonAccount,
  QuickDossier,
} from './mastodon';
import { RawContentPost } from './content-feed.utils';
import { Subject, Subscription, interval } from 'rxjs';
import { takeUntil, switchMap } from 'rxjs/operators';

const DOW_LABELS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTH_LABELS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

interface HeatmapGridCell {
  dow: number;
  hour: number;
  count: number;
  color: string;
}

interface CalendarDay {
  date: string;
  count: number;
  color: string;
}

interface CalendarWeek {
  days: (CalendarDay | null)[];
}

interface CalendarYear {
  year: number;
  weeks: CalendarWeek[];
  monthLabels: { label: string; weekIndex: number }[];
}

interface DossierRouteState {
  account?: MastodonAccount;
}

interface DossierTimezoneOption {
  label: string;
  value: number;
  inferredLabel: string;
}

type PostsTab = 'recent' | 'popular' | 'hashtag';

@Component({
  selector: 'app-dossier',
  standalone: true,
  imports: [CommonModule, RouterLink, FormsModule],
  template: `
    <div class="dossier-page">
      @if (loading) {
        <div class="loading">Loading dossier…</div>
      }
      @if (!dossier && !loading) {
        <!-- Profile card: show whatever basic info we have while/if full dossier is absent -->
        @if (quickDossier) {
          <div class="dossier-header" style="margin-top: 12px;">
            @if (quickDossier.header) {
              <div class="header-banner" [style.backgroundImage]="'url(' + quickDossier.header + ')'"></div>
            }
            <div class="header-body">
              <img class="avatar-lg" [src]="quickDossier.avatar" [alt]="quickDossier.display_name" />
              <div class="header-info">
                <h2>{{ quickDossier.display_name }}</h2>
                <p class="acct-line">
                  <a [href]="quickDossier.url" target="_blank" rel="noopener noreferrer" class="acct-link">&#64;{{ quickDossier.acct }}</a>
                </p>
                <div class="stat-row">
                  <span>{{ quickDossier.followers_count | number }} followers</span>
                  <span>{{ quickDossier.following_count | number }} following</span>
                  <span>{{ quickDossier.statuses_count | number }} posts</span>
                </div>
                @if (quickDossier.bot) { <span class="bot-badge">BOT</span> }
                @if (quickDossier.locked) { <span class="locked-badge">🔒 Approves followers</span> }
              </div>
            </div>
            @if (quickDossier.featured_hashtags.length > 0) {
              <div style="padding: 8px 16px 12px;">
                <div style="font-size: 0.78rem; font-weight: 600; color: #9ca3af; text-transform: uppercase; margin-bottom: 6px;">Featured Hashtags</div>
                <div class="hashtag-chips">
                  @for (ht of quickDossier.featured_hashtags; track ht.tag) {
                    <span class="hashtag-chip featured-chip">#{{ ht.tag }} <span class="chip-count">{{ ht.uses }}</span></span>
                  }
                </div>
              </div>
            }
          </div>
        }
        @if (quickDossierLoading) {
          <div style="color: #9ca3af; font-size: 0.84rem; margin-top: 8px;">Loading account info…</div>
        }
        @if (!quickDossier && !quickDossierLoading && error) {
          <div class="error-msg">{{ error }}</div>
        }

        <!-- Catchup prompt: always show when there is no full dossier yet -->
        <div class="catchup-prompt" style="margin-top: 12px;">
          <p style="margin: 0 0 8px 0; font-size: 0.9rem; color: #374151;">
            No cached posts yet. Run a catch-up to build the full dossier.
          </p>
          <div class="catchup-limit-row" style="margin-bottom: 10px;">
            <label for="deep-catchup-limit" style="font-size: 0.84rem; color: #374151;">Limit:</label>
            <select id="deep-catchup-limit" [(ngModel)]="deepCatchupLimit" style="font-size: 0.82rem; border: 1px solid #d1d5db; border-radius: 6px; padding: 3px 8px; background: white; margin-left: 8px;">
              <option [ngValue]="null">All posts</option>
              <option [ngValue]="25">~500 posts</option>
              <option [ngValue]="50">~1,000 posts</option>
              <option [ngValue]="125">~2,500 posts</option>
              <option [ngValue]="250">~5,000 posts</option>
              <option [ngValue]="500">~10,000 posts</option>
              <option [ngValue]="750">~15,000 posts</option>
            </select>
          </div>
          <div class="catchup-btn-row">
            <button class="action-btn secondary" (click)="shallowFetchUnknown()" [disabled]="fetchBusy" title="Fetches the most recent page of posts">
              {{ fetchBusy ? 'Starting…' : 'Catch Up' }}
            </button>
            <button class="action-btn secondary" (click)="deepFetchUnknown()" [disabled]="fetchBusy" title="Walks full post history in the background">
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
              @if (dossier.locked) {
                <span class="locked-badge">🔒 Approves followers</span>
              }
              @if (dossier.is_followed_by) {
                <span class="follows-you-badge">Follows you</span>
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
                title="Fetches the most recent page of posts"
              >
                {{ fetchBusy ? 'Starting…' : catchupStatus?.running ? 'Running…' : 'Catch Up' }}
              </button>
              <div style="display: flex; gap: 6px; align-items: center;">
                <button
                  class="action-btn secondary"
                  (click)="deepFetch()"
                  [disabled]="fetchBusy || catchupStatus?.running"
                  title="Walks full post history in the background"
                >
                  {{
                    fetchBusy
                      ? 'Starting…'
                      : catchupStatus?.running
                        ? 'Running…'
                        : 'Deep Catch Up'
                  }}
                </button>
                <select [(ngModel)]="deepCatchupLimit" style="font-size: 0.78rem; border: 1px solid #d1d5db; border-radius: 6px; padding: 3px 6px; background: white;" title="Limit pages fetched">
                  <option [ngValue]="null">All</option>
                  <option [ngValue]="25">~500</option>
                  <option [ngValue]="50">~1k</option>
                  <option [ngValue]="125">~2.5k</option>
                  <option [ngValue]="250">~5k</option>
                  <option [ngValue]="500">~10k</option>
                  <option [ngValue]="750">~15k</option>
                </select>
              </div>
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

        <!-- Cache Info -->
        @if (dossier.cache_info) {
          <div class="section">
            <h4>Cache</h4>
            <div class="cache-info-grid">
              <div class="cache-cell">
                <span class="cache-label">Cached posts</span>
                <span class="cache-value">{{ dossier.cache_info.cached_posts | number }}</span>
              </div>
              @if (dossier.cache_info.oldest_cached_post_at) {
                <div class="cache-cell">
                  <span class="cache-label">Oldest cached</span>
                  <span class="cache-value">{{ dossier.cache_info.oldest_cached_post_at | date: 'mediumDate' }}</span>
                </div>
              }
              @if (dossier.cache_info.latest_cached_post_at) {
                <div class="cache-cell">
                  <span class="cache-label">Newest cached</span>
                  <span class="cache-value">{{ dossier.cache_info.latest_cached_post_at | date: 'mediumDate' }}</span>
                </div>
              }
              @if (dossier.cache_info.last_status_at) {
                <div class="cache-cell">
                  <span class="cache-label">Last post (API)</span>
                  <span class="cache-value">{{ dossier.cache_info.last_status_at | date: 'mediumDate' }}</span>
                </div>
              }
              @if (cacheGapDays !== null) {
                <div class="cache-cell">
                  <span class="cache-label">Cache gap</span>
                  <span class="cache-value" [style.color]="cacheGapDays > 30 ? '#dc2626' : '#374151'">{{ cacheGapDays }} days behind</span>
                </div>
              }
            </div>
          </div>
        }

        <!-- Posting Heatmap -->
        <div class="section">
          <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
            <h4 style="margin: 0;">Posting Heatmap</h4>
            <div style="display: flex; align-items: center; gap: 8px; font-size: 0.8rem; color: #6b7280;">
              <label for="heatmap-timezone-offset">Timezone offset:</label>
              <select id="heatmap-timezone-offset" [(ngModel)]="heatmapTzOffset" style="font-size: 0.78rem; border: 1px solid #d1d5db; border-radius: 6px; padding: 2px 6px; background: white;">
                @for (tz of tzOptions; track tz.value) {
                  <option [ngValue]="tz.value">{{ tz.label }}</option>
                }
              </select>
            </div>
          </div>
          @if (inferredTimezoneDescription) {
            <div style="font-size: 0.78rem; color: #64748b; margin-bottom: 6px;">{{ inferredTimezoneDescription }}</div>
          }
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
                  <div class="heatmap-hour-label">{{ h % 6 === 0 ? shiftedHourLabel(h) : '' }}</div>
                }
              </div>
              @for (row of heatmapGrid; track $index) {
                <div class="heatmap-row">
                  <div class="heatmap-dow-label">{{ dowLabel($index) }}</div>
                  @for (cell of row; track $index) {
                    <div
                      class="heatmap-cell"
                      [style.background]="cell.color"
                      [title]="dowLabel(cell.dow) + ' ' + shiftedHourLabel(cell.hour) + ':00 — ' + cell.count + ' posts'"
                    ></div>
                  }
                </div>
              }
            </div>
          }
        </div>

        <!-- Activity Calendar -->
        <div class="section">
          <h4>Activity</h4>
          @if (calendarLoading) {
            <div style="color: #9ca3af; font-size: 0.84rem;">Loading…</div>
          }
          @if (!calendarLoading && calendarYears.length === 0) {
            <div style="color: #9ca3af; font-style: italic; font-size: 0.84rem;">No activity in cache yet.</div>
          }
          @for (yr of calendarYears; track yr.year) {
            <div style="margin-bottom: 16px;">
              <div class="calendar-year-label">{{ yr.year }}</div>
              <div class="calendar-wrap">
                <div class="calendar-months-row">
                  <div class="calendar-dow-col"></div>
                  @for (ml of yr.monthLabels; track ml.label) {
                    <div
                      class="calendar-month-label"
                      [style.left.px]="ml.weekIndex * 13 + 24"
                    >{{ ml.label }}</div>
                  }
                </div>
                <div class="calendar-grid">
                  <div class="calendar-dow-col">
                    @for (d of [1,3,5]; track d) {
                      <div class="calendar-dow-label">{{ dowLabel(d) }}</div>
                    }
                  </div>
                  @for (week of yr.weeks; track $index) {
                    <div class="calendar-week-col">
                      @for (day of week.days; track $index) {
                        @if (day) {
                          <div
                            class="calendar-cell"
                            [style.background]="day.color"
                            [title]="day.date + ' — ' + day.count + ' posts'"
                          ></div>
                        } @else {
                          <div class="calendar-cell calendar-cell-empty"></div>
                        }
                      }
                    </div>
                  }
                </div>
              </div>
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

        <!-- Hashtags -->
        @if (dossier.top_hashtags.length > 0 || (dossier.featured_hashtags && dossier.featured_hashtags.length > 0)) {
          <div class="section">
            <h4>Hashtags</h4>
            @if (dossier.featured_hashtags && dossier.featured_hashtags.length > 0) {
              <div style="margin-bottom: 10px;">
                <div class="hashtag-section-label">Featured (pinned by user)</div>
                <div class="hashtag-chips">
                  @for (ht of dossier.featured_hashtags; track ht.tag) {
                    <button
                      class="hashtag-chip featured-chip"
                      [class.active]="activeHashtag === ht.tag"
                      (click)="filterByHashtag(ht.tag)"
                      title="{{ ht.uses }} total posts"
                    >#{{ ht.tag }} <span class="chip-count">{{ ht.uses }}</span></button>
                  }
                </div>
              </div>
            }
            @if (dossier.top_hashtags.length > 0) {
              <div>
                <div class="hashtag-section-label">Post hashtags (from cached posts)</div>
                <div class="hashtag-chips">
                  @for (ht of dossier.top_hashtags; track ht.tag) {
                    <button
                      class="hashtag-chip"
                      [class.active]="activeHashtag === ht.tag"
                      (click)="filterByHashtag(ht.tag)"
                      title="{{ ht.count }} cached posts"
                    >#{{ ht.tag }} <span class="chip-count">{{ ht.count }}</span></button>
                  }
                </div>
              </div>
            }
          </div>
        }
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
              @if (activeHashtag) {
                <button
                  class="tab-btn active"
                  (click)="clearHashtagFilter()"
                >#{{ activeHashtag }} ✕</button>
              }
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
                  <a [routerLink]="['/write/reply', post.id]" class="reply-link">↩ Reply</a>
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
        border: 1px solid #bfdbfe;
      }
      .hashtag-chip:hover {
        background: #dbeafe;
      }
      .hashtag-chip.active {
        background: #6366f1;
        color: white;
        border: none;
      }
      .hashtag-chip.active .chip-count {
        background: rgba(255,255,255,0.25);
        color: white;
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
      /* Activity Calendar */
      .calendar-year-label {
        font-size: 0.75rem;
        font-weight: 700;
        color: #6b7280;
        margin-bottom: 4px;
      }
      .calendar-wrap {
        overflow-x: auto;
        position: relative;
      }
      .calendar-months-row {
        position: relative;
        height: 16px;
        display: flex;
        margin-left: 24px;
      }
      .calendar-month-label {
        position: absolute;
        font-size: 0.6rem;
        color: #9ca3af;
        white-space: nowrap;
      }
      .calendar-grid {
        display: flex;
        gap: 2px;
        margin-top: 2px;
      }
      .calendar-dow-col {
        width: 24px;
        flex-shrink: 0;
        display: flex;
        flex-direction: column;
        gap: 1px;
        padding-top: 13px;
      }
      .calendar-dow-label {
        font-size: 0.6rem;
        color: #9ca3af;
        height: 11px;
        line-height: 11px;
      }
      .calendar-week-col {
        display: flex;
        flex-direction: column;
        gap: 1px;
      }
      .calendar-cell {
        width: 11px;
        height: 11px;
        border-radius: 2px;
        flex-shrink: 0;
      }
      .calendar-cell-empty {
        background: transparent !important;
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
      .reply-link {
        color: #6b7280;
        font-size: 0.75rem;
        text-decoration: none;
      }
      .reply-link:hover {
        color: #6366f1;
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
      .locked-badge {
        font-size: 0.65rem;
        background: #fef3c7;
        color: #92400e;
        padding: 2px 6px;
        border-radius: 4px;
        margin-top: 4px;
        display: inline-block;
      }
      .follows-you-badge {
        font-size: 0.65rem;
        background: #d1fae5;
        color: #065f46;
        padding: 2px 6px;
        border-radius: 4px;
        margin-top: 4px;
        display: inline-block;
      }
      .hashtag-section-label {
        font-size: 0.72rem;
        font-weight: 600;
        color: #9ca3af;
        text-transform: uppercase;
        margin-bottom: 6px;
      }
      .featured-chip {
        background: #fef3c7 !important;
        border-color: #fcd34d !important;
        color: #92400e !important;
      }
      .featured-chip.active {
        background: #f59e0b !important;
        color: white !important;
      }
      .cache-info-grid {
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
      }
      .cache-cell {
        display: flex;
        flex-direction: column;
        background: #f9fafb;
        border-radius: 6px;
        padding: 8px 12px;
        min-width: 120px;
      }
      .cache-label {
        font-size: 0.72rem;
        color: #9ca3af;
        text-transform: uppercase;
        font-weight: 600;
      }
      .cache-value {
        font-size: 0.9rem;
        color: #374151;
        font-weight: 600;
        margin-top: 2px;
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
  quickDossier: QuickDossier | null = null;
  quickDossierLoading = false;
  cacheMissMessage: string | null = null;
  loading = true;
  error: string | null = null;
  noteExpanded = true;
  followBusy = false;
  fetchBusy = false;
  catchupError: string | null = null;
  catchupStatus: AccountCatchupStatus | null = null;
  isFollowing = false;
  deepCatchupLimit: number | null = null;

  readonly tzOptions: DossierTimezoneOption[] = [
    { label: 'UTC (server time)', value: 0, inferredLabel: 'UTC' },
    { label: 'UTC-12', value: -12, inferredLabel: 'UTC-12' },
    { label: 'UTC-11', value: -11, inferredLabel: 'UTC-11' },
    { label: 'UTC-10 (Hawaii)', value: -10, inferredLabel: 'UTC-10 (Hawaii)' },
    { label: 'UTC-9 (Alaska)', value: -9, inferredLabel: 'UTC-9 (Alaska)' },
    { label: 'UTC-8 (Pacific)', value: -8, inferredLabel: 'UTC-8 (Pacific / Los Angeles)' },
    { label: 'UTC-7 (Mountain)', value: -7, inferredLabel: 'UTC-7 (Mountain / Denver)' },
    { label: 'UTC-6 (Central)', value: -6, inferredLabel: 'UTC-6 (Central / Chicago)' },
    { label: 'UTC-5 (Eastern)', value: -5, inferredLabel: 'UTC-5 (Eastern / New York)' },
    { label: 'UTC-4 (Atlantic)', value: -4, inferredLabel: 'UTC-4 (Atlantic / Halifax)' },
    { label: 'UTC-3', value: -3, inferredLabel: 'UTC-3' },
    { label: 'UTC-2', value: -2, inferredLabel: 'UTC-2' },
    { label: 'UTC-1', value: -1, inferredLabel: 'UTC-1' },
    { label: 'UTC+1 (CET)', value: 1, inferredLabel: 'UTC+1 (Central Europe / Berlin)' },
    { label: 'UTC+2 (EET)', value: 2, inferredLabel: 'UTC+2 (Eastern Europe / Helsinki)' },
    { label: 'UTC+3 (Moscow)', value: 3, inferredLabel: 'UTC+3 (Moscow)' },
    { label: 'UTC+4', value: 4, inferredLabel: 'UTC+4' },
    { label: 'UTC+5', value: 5, inferredLabel: 'UTC+5' },
    { label: 'UTC+5:30 (IST)', value: 5.5, inferredLabel: 'UTC+5:30 (India / Delhi)' },
    { label: 'UTC+6', value: 6, inferredLabel: 'UTC+6' },
    { label: 'UTC+7', value: 7, inferredLabel: 'UTC+7' },
    { label: 'UTC+8 (CST/AWST)', value: 8, inferredLabel: 'UTC+8 (China / Perth)' },
    { label: 'UTC+9 (JST)', value: 9, inferredLabel: 'UTC+9 (Japan / Tokyo)' },
    { label: 'UTC+10 (AEST)', value: 10, inferredLabel: 'UTC+10 (Eastern Australia / Sydney)' },
    { label: 'UTC+11', value: 11, inferredLabel: 'UTC+11' },
    { label: 'UTC+12', value: 12, inferredLabel: 'UTC+12' },
  ];
  heatmapTzOffset = 0;
  inferredTimezone: DossierTimezoneOption | null = null;

  inferTimezoneFromHeatmap(): void {
    if (this.heatmapCells.length === 0) {
      this.inferredTimezone = null;
      return;
    }

    const hourTotals = new Array(24).fill(0);
    for (const c of this.heatmapCells) hourTotals[c.hour] += c.count;

    // Find the 6-hour window with the lowest total post count (sleep window).
    // We try all 24 possible 6-hour windows (wrapping around midnight).
    const SLEEP_HOURS = 6;
    let minWindowCount = Infinity;
    let sleepWindowStart = 0;
    for (let start = 0; start < 24; start++) {
      let windowCount = 0;
      for (let i = 0; i < SLEEP_HOURS; i++) {
        windowCount += hourTotals[(start + i) % 24];
      }
      if (windowCount < minWindowCount) {
        minWindowCount = windowCount;
        sleepWindowStart = start;
      }
    }

    // Sleep window end = first hour after the sleep window (assumed ~8am local)
    const sleepWindowEndUtc = (sleepWindowStart + SLEEP_HOURS) % 24;
    // offset = 8 - sleepWindowEndUtc  (so that sleepWindowEndUtc + offset = 8)
    let rawOffset = 8 - sleepWindowEndUtc;
    // Normalise to [-12, 12]
    if (rawOffset > 12) rawOffset -= 24;
    if (rawOffset < -12) rawOffset += 24;

    // Snap to nearest available tzOptions value
    const best = this.tzOptions.reduce((prev, cur) =>
      Math.abs(cur.value - rawOffset) < Math.abs(prev.value - rawOffset) ? cur : prev
    );
    this.inferredTimezone = best;
    this.heatmapTzOffset = best.value;
  }

  get inferredTimezoneDescription(): string | null {
    if (!this.inferredTimezone) return null;
    return `The inferred timezone of this person is roughly ${this.inferredTimezone.inferredLabel}. Posting drops overnight and picks back up around 8a local time.`;
  }

  get cacheGapDays(): number | null {
    if (!this.dossier?.cache_info) return null;
    const lastStatus = this.dossier.cache_info.last_status_at;
    const latestCached = this.dossier.cache_info.latest_cached_post_at;
    if (!lastStatus || !latestCached) return null;
    const diff = new Date(lastStatus).getTime() - new Date(latestCached).getTime();
    return Math.max(0, Math.round(diff / 86400000));
  }

  heatmapCells: HeatmapCell[] = [];
  heatmapLoading = false;
  heatmapError: string | null = null;
  readonly hours = Array.from({ length: 24 }, (_u, h) => h);

  calendarDays: { date: string; count: number }[] = [];
  calendarLoading = false;
  calendarYears: CalendarYear[] = [];

  allPosts: RawContentPost[] = [];
  hashtagPosts: RawContentPost[] = [];
  postsLoading = false;
  postsTab: PostsTab = 'recent';
  activeHashtag: string | null = null;

  interactions: DossierInteraction[] = [];
  interactionsLoading = false;

  interactionWindows: {
    label: string;
    them_to_me: number;
    me_to_them: number;
    max: number;
  }[] = [];

  get displayedPosts(): RawContentPost[] {
    if (this.postsTab === 'hashtag') {
      return this.hashtagPosts.slice(0, 20);
    }
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

  shiftedHourLabel(h: number): string {
    const shifted = ((h + this.heatmapTzOffset) % 24 + 24) % 24;
    return this.hourLabel(shifted);
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
        this.loadCalendar(acct, id);
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

  private loadCalendar(acct: string, identityId: number): void {
    this.calendarLoading = true;
    this.api
      .getActivityCalendar(identityId, acct, 2)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (days) => {
          this.calendarDays = days;
          this.calendarYears = this.buildCalendarYears(days);
          this.calendarLoading = false;
        },
        error: () => {
          this.calendarLoading = false;
        },
      });
  }

  private buildCalendarYears(
    days: { date: string; count: number }[],
  ): CalendarYear[] {
    const countMap = new Map<string, number>();
    let maxCount = 0;
    for (const d of days) {
      countMap.set(d.date, d.count);
      if (d.count > maxCount) maxCount = d.count;
    }

    const now = new Date();
    const currentYear = now.getFullYear();
    const years: CalendarYear[] = [];

    for (let yr = currentYear - 1; yr <= currentYear; yr++) {
      const jan1 = new Date(yr, 0, 1);
      const dec31 = new Date(yr, 11, 31);
      const startDow = jan1.getDay(); // 0=Sun

      const weeks: CalendarWeek[] = [];
      let week: (CalendarDay | null)[] = Array(startDow).fill(null);
      const cur = new Date(jan1);

      while (cur <= dec31) {
        const dateStr = cur.toISOString().slice(0, 10);
        const count = countMap.get(dateStr) ?? 0;
        week.push({ date: dateStr, count, color: this.calendarColor(count, maxCount) });
        if (week.length === 7) {
          weeks.push({ days: week });
          week = [];
        }
        cur.setDate(cur.getDate() + 1);
      }
      if (week.length > 0) {
        while (week.length < 7) week.push(null);
        weeks.push({ days: week });
      }

      // Month label positions
      const monthLabels: { label: string; weekIndex: number }[] = [];
      let prevMonth = -1;
      for (let wi = 0; wi < weeks.length; wi++) {
        for (const day of weeks[wi].days) {
          if (day) {
            const m = new Date(day.date).getMonth();
            if (m !== prevMonth) {
              monthLabels.push({ label: MONTH_LABELS[m], weekIndex: wi });
              prevMonth = m;
            }
            break;
          }
        }
      }

      years.push({ year: yr, weeks, monthLabels });
    }
    return years;
  }

  private calendarColor(count: number, max: number): string {
    if (count === 0 || max === 0) return '#ebedf0';
    const t = Math.log1p(count) / Math.log1p(max);
    return this.lerpColor('#9be9a8', '#216e39', Math.min(1, Math.max(0.15, t)));
  }

  filterByHashtag(tag: string): void {
    const acct = this.route.snapshot.paramMap.get('acct') ?? '';
    const id = this.api.getCurrentIdentityId();
    if (!id) return;

    if (this.activeHashtag === tag) {
      this.clearHashtagFilter();
      return;
    }

    this.activeHashtag = tag;
    this.postsTab = 'hashtag';
    this.postsLoading = true;
    this.api
      .getPublicPosts(id, 'all', acct, null, 20, tag)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (page) => {
          this.hashtagPosts = page.items;
          this.postsLoading = false;
        },
        error: () => {
          this.hashtagPosts = [];
          this.postsLoading = false;
        },
      });
  }

  clearHashtagFilter(): void {
    this.activeHashtag = null;
    this.hashtagPosts = [];
    this.postsTab = 'recent';
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
          this.inferTimezoneFromHeatmap();
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
    const req$ = mode === 'deep'
      ? this.api.deepFetchDossier(acct, id, this.deepCatchupLimit ?? undefined)
      : this.api.startAccountCatchup(acct, id, mode);
    req$
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
            this.loadHeatmap(acct, identityId);
            this.loadCalendar(acct, identityId);
            this.loadPosts(acct, identityId);
            this.loadInteractions(acct, identityId);
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
    this.dossier = null;
    this.error = null;
    this.cacheMissMessage = null;
    // Only prime from route/storage if we have nothing yet — don't blank out
    // an already-visible profile card during a catch-up reload.
    if (!this.quickDossier) {
      this.primeQuickDossierFromRoute(acct);
    }
    this.quickDossierLoading = false;
    this.api
      .getDossier(acct, identityId)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (d) => {
          this.dossier = d;
          this.quickDossier = null;
          this.isFollowing = d.is_following;
          this.buildInteractionWindows(d);
          this.loading = false;
        },
        error: (e: unknown) => {
          this.loading = false;
          if (this.getHttpStatus(e) === 404) {
            this.cacheMissMessage = 'No cached posts found yet, so this is a quick API lookup.';
            this.loadQuickDossier(acct, identityId);
            return;
          }
          this.error = 'Failed to load dossier.';
          console.error(e);
        },
      });
  }

  private loadQuickDossier(acct: string, identityId: number): void {
    this.quickDossierLoading = true;
    const candidates = this.getQuickLookupCandidates(acct);
    this.tryLoadQuickDossier(candidates, identityId);
  }

  private tryLoadQuickDossier(candidates: string[], identityId: number): void {
    const [acct, ...rest] = candidates;
    if (!acct) {
      this.quickDossierLoading = false;
      this.cacheMissMessage = null;
      if (!this.quickDossier) {
        this.error = 'No cached data found for this account yet.';
      }
      return;
    }

    this.api
      .getQuickDossier(acct, identityId)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (qd) => {
          this.quickDossier = qd;
          this.quickDossierLoading = false;
        },
        error: () => {
          if (rest.length > 0) {
            this.tryLoadQuickDossier(rest, identityId);
            return;
          }
          this.quickDossierLoading = false;
          this.cacheMissMessage = null;
          if (!this.quickDossier) {
            this.error = 'No cached data found for this account yet.';
          }
        },
      });
  }

  private getQuickLookupCandidates(acct: string): string[] {
    const candidates = new Set<string>([acct]);
    const routeAccount = this.getRouteStateAccount(acct);
    if (!routeAccount) return [...candidates];

    const canonicalAcct = this.getCanonicalAcct(routeAccount);
    if (canonicalAcct) {
      candidates.add(canonicalAcct);
    }
    if (routeAccount.username) {
      candidates.add(routeAccount.username);
    }
    return [...candidates];
  }

  private primeQuickDossierFromRoute(acct: string): void {
    const routeAccount = this.getRouteStateAccount(acct);
    if (routeAccount) {
      this.quickDossier = {
        id: routeAccount.id,
        acct: this.getCanonicalAcct(routeAccount) ?? routeAccount.acct,
        display_name: routeAccount.display_name,
        avatar: routeAccount.avatar,
        header: routeAccount.header ?? routeAccount.header_static ?? '',
        url: routeAccount.url,
        note: routeAccount.note,
        bot: routeAccount.bot,
        locked: Boolean(routeAccount.locked),
        followers_count: routeAccount.followers_count ?? routeAccount.counts?.followers ?? 0,
        following_count: routeAccount.following_count ?? routeAccount.counts?.following ?? 0,
        statuses_count: routeAccount.statuses_count ?? routeAccount.counts?.statuses ?? 0,
        created_at: routeAccount.created_at ?? null,
        featured_hashtags: [],
        fields: [],
      };
      return;
    }

    // Fallback: check localStorage hint written by new-friends page.
    // Uses localStorage (not sessionStorage) so the hint survives the new-tab
    // navigation that the new-friends Dossier link triggers.
    try {
      const raw = localStorage.getItem(`dossier_hint_${acct}`);
      if (raw) {
        const hint = JSON.parse(raw) as {
          id: string; acct: string; display_name: string; avatar: string;
          url: string; note: string; bot: boolean; locked: boolean;
          followers_count: number; following_count: number; statuses_count: number;
          created_at: string | null;
        };
        localStorage.removeItem(`dossier_hint_${acct}`);
        this.quickDossier = {
          id: hint.id,
          acct: hint.acct,
          display_name: hint.display_name,
          avatar: hint.avatar,
          header: '',
          url: hint.url,
          note: hint.note,
          bot: hint.bot,
          locked: hint.locked,
          followers_count: hint.followers_count,
          following_count: hint.following_count,
          statuses_count: hint.statuses_count,
          created_at: hint.created_at,
          featured_hashtags: [],
          fields: [],
        };
        return;
      }
    } catch {
      // ignore storage errors
    }

    this.quickDossier = null;
  }

  private getRouteStateAccount(acct: string): MastodonAccount | null {
    const state = history.state as DossierRouteState | null;
    const account = state?.account;
    if (!account) return null;
    const canonicalAcct = this.getCanonicalAcct(account);
    if (account.acct === acct || canonicalAcct === acct) {
      return account;
    }
    return null;
  }

  private getCanonicalAcct(account: MastodonAccount): string | null {
    if (account.acct.includes('@')) {
      return account.acct;
    }
    const host = this.getAccountHost(account.url);
    const username = account.username ?? account.acct;
    if (!host || !username) return null;
    return `${username}@${host}`;
  }

  private getAccountHost(url: string): string | null {
    try {
      return new URL(url).hostname;
    } catch {
      return null;
    }
  }

  private getHttpStatus(error: unknown): number | null {
    if (typeof error === 'object' && error !== null && 'status' in error) {
      const status = (error as { status: unknown }).status;
      return typeof status === 'number' ? status : null;
    }
    return null;
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
    const acct = this.dossier.acct;
    const req$ = mode === 'deep'
      ? this.api.deepFetchDossier(acct, id, this.deepCatchupLimit ?? undefined)
      : this.api.startAccountCatchup(acct, id, mode);
    req$
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (status) => {
          this.catchupStatus = status;
          this.fetchBusy = false;
          if (status.running) {
            this.startCatchupPolling(acct, id);
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
