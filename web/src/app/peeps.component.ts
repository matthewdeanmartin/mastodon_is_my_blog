// src/app/peeps.component.ts
import { Component, OnInit, OnDestroy, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { ApiService } from './api.service';
import { EngagementMatrix } from './mastodon';
import { Subject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';

@Component({
  selector: 'app-peeps',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="peeps-page">
      <h2 class="page-title">Who's My Peeps</h2>

      @if (loading) {
        <div class="loading">Loading engagement matrix…</div>
      }
      @if (error) {
        <div class="error-msg">{{ error }}</div>
      }

      @if (!loading && matrix) {
        <div class="matrix-grid">
          <div class="quadrant-card">
            <h3 class="quadrant-title">🤝 Inner Circle</h3>
            <p class="quadrant-desc">Mutual high engagement</p>
            <div class="account-list">
              @for (entry of matrix.inner_circle; track entry.account_id) {
                <div class="account-row" role="button" tabindex="0" (click)="viewDossier(entry.acct)" (keydown.enter)="viewDossier(entry.acct)">
                  <img class="avatar" [src]="entry.avatar" [alt]="entry.display_name" />
                  <div class="account-info">
                    <span class="display-name">{{ entry.display_name }}</span>
                    <span class="acct">&#64;{{ entry.acct }}</span>
                    <span class="counts-line">{{ entry.statuses_count | number }} posts</span>
                  </div>
                  <span class="score-chip">{{ entry.combined_score | number: '1.0-0' }}</span>
                </div>
              }
              @if (matrix.inner_circle.length === 0) {
                <p class="empty">No data yet — sync more notifications.</p>
              }
            </div>
          </div>

          <div class="quadrant-card">
            <h3 class="quadrant-title">🌟 Fans</h3>
            <p class="quadrant-desc">They engage you; you haven't followed back</p>
            <div class="account-list">
              @for (entry of matrix.fans; track entry.account_id) {
                <div class="account-row" role="button" tabindex="0" (click)="viewDossier(entry.acct)" (keydown.enter)="viewDossier(entry.acct)">
                  <img class="avatar" [src]="entry.avatar" [alt]="entry.display_name" />
                  <div class="account-info">
                    <span class="display-name">{{ entry.display_name }}</span>
                    <span class="acct">&#64;{{ entry.acct }}</span>
                    <span class="counts-line">{{ entry.statuses_count | number }} posts</span>
                  </div>
                  <span class="score-chip">{{ entry.in_score | number: '1.0-0' }} → you</span>
                </div>
              }
              @if (matrix.fans.length === 0) {
                <p class="empty">No quiet admirers found.</p>
              }
            </div>
          </div>

          <div class="quadrant-card">
            <h3 class="quadrant-title">🎯 Idols</h3>
            <p class="quadrant-desc">You engage them; they rarely engage back</p>
            <div class="account-list">
              @for (entry of matrix.idols; track entry.account_id) {
                <div class="account-row" role="button" tabindex="0" (click)="viewDossier(entry.acct)" (keydown.enter)="viewDossier(entry.acct)">
                  <img class="avatar" [src]="entry.avatar" [alt]="entry.display_name" />
                  <div class="account-info">
                    <span class="display-name">{{ entry.display_name }}</span>
                    <span class="acct">&#64;{{ entry.acct }}</span>
                    <span class="counts-line">{{ entry.statuses_count | number }} posts</span>
                    @if (entry.is_following) {
                      <span class="follow-badge">following</span>
                    }
                  </div>
                  <span class="score-chip">you → {{ entry.out_score | number: '1.0-0' }}</span>
                </div>
              }
              @if (matrix.idols.length === 0) {
                <p class="empty">No one-sided engagement found.</p>
              }
            </div>
          </div>

          <div class="quadrant-card">
            <h3 class="quadrant-title">📢 Broadcasters</h3>
            <p class="quadrant-desc">You follow them, but they rarely interact</p>
            <div class="account-list">
              @for (entry of matrix.broadcasters; track entry.account_id) {
                <div class="account-row" role="button" tabindex="0" (click)="viewDossier(entry.acct)" (keydown.enter)="viewDossier(entry.acct)">
                  <img class="avatar" [src]="entry.avatar" [alt]="entry.display_name" />
                  <div class="account-info">
                    <span class="display-name">{{ entry.display_name }}</span>
                    <span class="acct">&#64;{{ entry.acct }}</span>
                    <span class="counts-line"
                      >{{ entry.statuses_count | number }} posts ·
                      {{ entry.is_following ? 'following' : '' }}
                      {{ entry.is_followed_by ? '· follows you' : '' }}</span
                    >
                  </div>
                  <span class="score-chip">{{ entry.statuses_count | number }} posts</span>
                </div>
              }
              @if (matrix.broadcasters.length === 0) {
                <p class="empty">No broadcaster accounts found.</p>
              }
            </div>
          </div>
        </div>
      }
    </div>
  `,
  styles: [
    `
      .peeps-page {
        padding: 24px;
        max-width: 1200px;
        margin: 0 auto;
      }
      .page-title {
        color: #374151;
        margin: 0 0 24px 0;
      }
      .loading,
      .error-msg {
        padding: 16px;
        text-align: center;
        color: #6b7280;
      }
      .error-msg {
        color: #dc2626;
      }
      .matrix-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
        gap: 20px;
      }
      .quadrant-card {
        background: white;
        border: 1px solid #e1e8ed;
        border-radius: 8px;
        padding: 16px;
      }
      .quadrant-title {
        margin: 0 0 4px 0;
        font-size: 1rem;
        color: #1f2937;
      }
      .quadrant-desc {
        margin: 0 0 12px 0;
        font-size: 0.78rem;
        color: #9ca3af;
      }
      .account-list {
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      .account-row {
        display: flex;
        align-items: center;
        gap: 8px;
        cursor: pointer;
        padding: 6px;
        border-radius: 6px;
        transition: background 0.1s;
      }
      .account-row:hover {
        background: #f3f4f6;
      }
      .avatar {
        width: 36px;
        height: 36px;
        border-radius: 50%;
        flex-shrink: 0;
        object-fit: cover;
      }
      .account-info {
        flex: 1;
        display: flex;
        flex-direction: column;
        min-width: 0;
      }
      .display-name {
        font-size: 0.85rem;
        font-weight: 600;
        color: #1f2937;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .acct {
        font-size: 0.75rem;
        color: #6b7280;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .counts-line {
        font-size: 0.7rem;
        color: #9ca3af;
        margin-top: 1px;
      }
      .follow-badge {
        font-size: 0.68rem;
        color: #059669;
        background: #d1fae5;
        padding: 1px 5px;
        border-radius: 4px;
        align-self: flex-start;
      }
      .score-chip {
        font-size: 0.72rem;
        color: #6b7280;
        background: #f3f4f6;
        padding: 2px 8px;
        border-radius: 10px;
        white-space: nowrap;
        flex-shrink: 0;
      }
      .empty {
        color: #9ca3af;
        font-size: 0.82rem;
        text-align: center;
        padding: 12px 0;
      }
    `,
  ],
})
export class PeepsComponent implements OnInit, OnDestroy {
  private api = inject(ApiService);
  private router = inject(Router);
  private destroy$ = new Subject<void>();

  matrix: EngagementMatrix | null = null;
  loading = true;
  error: string | null = null;

  ngOnInit(): void {
    this.api.identityId$.pipe(takeUntil(this.destroy$)).subscribe((id) => {
      if (id) this.loadMatrix(id);
    });
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  loadMatrix(identityId: number): void {
    this.loading = true;
    this.error = null;
    this.api
      .getEngagementMatrix(identityId)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (m) => {
          this.matrix = m;
          this.loading = false;
        },
        error: (e: unknown) => {
          this.error = 'Failed to load engagement matrix.';
          this.loading = false;
          console.error(e);
        },
      });
  }

  viewDossier(acct: string): void {
    this.router.navigate(['/peeps/dossier', acct]);
  }
}
