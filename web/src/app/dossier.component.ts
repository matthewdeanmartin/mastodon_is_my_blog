// src/app/dossier.component.ts
import { Component, OnInit, OnDestroy, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute } from '@angular/router';
import { ApiService } from './api.service';
import { AccountCatchupStatus, Dossier } from './mastodon';
import { Subject, Subscription, interval } from 'rxjs';
import { takeUntil, switchMap } from 'rxjs/operators';

@Component({
  selector: 'app-dossier',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="dossier-page">
      @if (loading) {
        <div class="loading">Loading dossier…</div>
      }
      @if (error) {
        <div class="error-msg">{{ error }}</div>
        <div
          style="margin-top: 16px; padding: 16px; background: white; border: 1px solid #e1e8ed; border-radius: 8px;"
        >
          <p style="margin: 0 0 12px 0; font-size: 0.9rem; color: #374151;">
            To build a dossier, first run a Deep Catch Up to download this account's posts into your
            local cache.
          </p>
          <button class="action-btn secondary" (click)="deepFetchUnknown()" [disabled]="fetchBusy">
            {{ fetchBusy ? 'Starting…' : 'Deep Catch Up' }}
          </button>
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
              <p class="acct-line">&#64;{{ dossier.acct }}</p>
              <div class="stat-row">
                <span>{{ dossier.followers_count }} followers</span>
                <span>{{ dossier.following_count }} following</span>
                <span>{{ dossier.statuses_count }} posts</span>
              </div>
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
                >Last deep catch-up fetched {{ catchupStatus.posts_fetched }} posts across
                {{ catchupStatus.pages_fetched }} page(s).</span
              >
            }
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

        <!-- Post/Reply Ratio -->
        @if (dossier.post_reply_ratio !== null) {
          <div class="section">
            <h4>Post/Reply Ratio</h4>
            <p class="ratio-value">
              {{ dossier.post_reply_ratio | number: '1.1-1' }}x more posts than replies
            </p>
          </div>
        }

        <!-- Top Hashtags -->
        @if (dossier.top_hashtags.length > 0) {
          <div class="section">
            <h4>Top Hashtags</h4>
            <div class="hashtag-chips">
              @for (ht of dossier.top_hashtags; track ht.tag) {
                <span class="hashtag-chip"
                  >#{{ ht.tag }} <span class="chip-count">{{ ht.count }}</span></span
                >
              }
            </div>
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
        margin: 0 0 8px 0;
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
        border: 1px solid #d1d5db;
        background: white;
        cursor: pointer;
        font-size: 0.85rem;
        font-weight: 600;
        transition: background 0.1s;
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
      .action-btn.secondary {
        background: #f9fafb;
        color: #374151;
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
      }
      .chip-count {
        background: #dbeafe;
        color: #1e40af;
        padding: 0 5px;
        border-radius: 6px;
        font-size: 0.72rem;
        margin-left: 4px;
      }
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
    `,
  ],
})
export class DossierComponent implements OnInit, OnDestroy {
  private api = inject(ApiService);
  private route = inject(ActivatedRoute);
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

  interactionWindows: {
    label: string;
    them_to_me: number;
    me_to_them: number;
    max: number;
  }[] = [];

  ngOnInit(): void {
    const acct = this.route.snapshot.paramMap.get('acct') ?? '';
    this.api.identityId$.pipe(takeUntil(this.destroy$)).subscribe((id) => {
      if (id) {
        this.loadDossier(acct, id);
        this.loadCatchupStatus(acct, id);
      }
    });
  }

  ngOnDestroy(): void {
    this.catchupPollSub?.unsubscribe();
    this.destroy$.next();
    this.destroy$.complete();
  }

  deepFetchUnknown(): void {
    const acct = this.route.snapshot.paramMap.get('acct') ?? '';
    const id = this.api.getCurrentIdentityId();
    if (!id || !acct) return;
    this.fetchBusy = true;
    this.catchupError = null;
    this.api
      .startAccountCatchup(acct, id, 'deep')
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
          this.catchupError = 'Failed to start deep catch-up.';
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

  deepFetch(): void {
    if (!this.dossier) return;
    const id = this.api.getCurrentIdentityId();
    if (!id) return;
    this.fetchBusy = true;
    this.catchupError = null;
    this.api
      .startAccountCatchup(this.dossier.acct, id, 'deep')
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
          console.error('Deep fetch failed', e);
          this.fetchBusy = false;
          this.catchupError = 'Failed to start deep catch-up.';
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
          this.catchupError = 'Failed to stop deep catch-up.';
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

          this.catchupError = httpError.error?.detail ?? 'Failed to load deep catch-up status.';
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
          console.error('Deep catch-up status failed', e);
          this.catchupPollSub?.unsubscribe();
          this.catchupPollSub = undefined;
        },
      });
  }
}
