// src/app/new-friends.component.ts
import { Component, OnInit, OnDestroy, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from './api.service';
import { NewFriendCandidate } from './mastodon';
import { Subject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';

interface FacetChip {
  id: string;
  label: string;
  active: boolean;
  test: (c: NewFriendCandidate) => boolean;
}

@Component({
  selector: 'app-new-friends',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="new-friends-page">
      <div class="page-header">
        <h2 class="page-title">🌱 New Friends</h2>
        <p class="page-subtitle">
          People your friends follow that you don't yet.
        </p>
      </div>

      <!-- Controls -->
      <div class="controls-panel">
        <div class="filter-row">
          <label>
            Max friends to scan
            <input
              type="number"
              [(ngModel)]="maxFriends"
              min="1"
              max="500"
              class="num-input"
            />
            <span class="hint">(each costs 1 API call — 50 = ~50 requests)</span>
          </label>

          <label>
            Source friends
            <select [(ngModel)]="blogRollFilter" class="select-input">
              <option value="">All follows</option>
              <option value="top_friends">Top friends</option>
              <option value="mutuals">Mutuals only</option>
              <option value="lively">Lively (active 30d)</option>
            </select>
          </label>
        </div>

        <div class="filter-row">
          <label>
            Min posts
            <input type="number" [(ngModel)]="minPosts" min="0" class="num-input-sm" />
          </label>

          <label>
            Active within
            <select [(ngModel)]="activeSinceDays" class="select-input">
              <option [ngValue]="30">30 days</option>
              <option [ngValue]="90">90 days</option>
              <option [ngValue]="365">1 year</option>
              <option [ngValue]="1825">5 years</option>
              <option [ngValue]="3650">Any time</option>
            </select>
          </label>

          <label>
            Bio contains
            <input
              type="text"
              [(ngModel)]="bioContains"
              placeholder="e.g. python"
              class="text-input"
            />
          </label>
        </div>

        <div class="action-row">
          <button class="btn-primary" (click)="loadFresh()" [disabled]="loading">
            {{ loading ? 'Fetching…' : '⬇ Download / Refresh' }}
          </button>
          <button class="btn-secondary" (click)="applyFilters()" [disabled]="loading">
            Apply Filters
          </button>
          @if (fetchedAt) {
            <span class="cache-info">
              {{ cacheHit ? 'Cached' : 'Fresh fetch' }} · {{ fetchedAt | date: 'short' }}
            </span>
          }
        </div>
      </div>

      @if (error) {
        <div class="error-msg">{{ error }}</div>
      }

      <!-- Facet chips -->
      @if (displayed.length > 0 || facets.some(f => f.active)) {
        <div class="facet-bar">
          @for (facet of facets; track facet.id) {
            <button
              class="facet-chip"
              [class.active]="facet.active"
              (click)="toggleFacet(facet)"
            >
              {{ facet.label }}
            </button>
          }
          @if (facets.some(f => f.active)) {
            <button class="facet-chip clear" (click)="clearFacets()">✕ Clear</button>
          }
        </div>
      }

      <!-- Results summary -->
      @if (!loading && (allCandidates.length > 0 || fetchedAt)) {
        <div class="results-summary">
          @if (allCandidates.length > 0) {
            Showing {{ displayed.length }} of {{ allCandidates.length }} candidates
            ({{ totalDownloaded }} profiles downloaded, {{ allCandidates.length }} not yet followed)
          } @else {
            {{ totalDownloaded }} profiles downloaded — all already followed, or filtered out.
          }
        </div>
      }

      <!-- Bulk action bar -->
      @if (selectedIds.size > 0) {
        <div class="bulk-bar">
          <span>{{ selectedIds.size }} selected</span>
          <button
            class="btn-follow-bulk"
            (click)="followSelected()"
            [disabled]="bulkFollowInProgress"
          >
            {{ bulkFollowInProgress ? 'Following…' : 'Follow ' + selectedIds.size + ' selected' }}
          </button>
          <button class="btn-secondary-sm" (click)="clearSelection()">Clear</button>
          @if (bulkFollowResult) {
            <span class="bulk-result">{{ bulkFollowResult }}</span>
          }
        </div>
      }

      <!-- Loading -->
      @if (loading) {
        <div class="loading-block">
          <div class="spinner"></div>
          <span>Fetching friends-of-friends… this may take a moment.</span>
        </div>
      }

      <!-- Candidate cards -->
      <div class="candidate-list">
        @for (c of displayed; track c.id) {
          <div class="candidate-card" [class.selected]="selectedIds.has(c.id)">
            <label class="check-wrap">
              <input
                type="checkbox"
                [checked]="selectedIds.has(c.id)"
                (change)="toggleSelect(c.id)"
              />
            </label>

            <img class="avatar" [src]="c.avatar" [alt]="c.display_name" />

            <div class="candidate-info">
              <div class="name-row">
                <span class="display-name">{{ c.display_name || c.acct }}</span>
                <span class="acct">&#64;{{ c.acct }}</span>
                @if (c.bot) { <span class="badge bot">bot</span> }
                @if (c.locked) { <span class="badge locked">🔒</span> }
              </div>
              @if (c.note) {
                <p class="bio">{{ c.note | slice: 0:140 }}{{ c.note.length > 140 ? '…' : '' }}</p>
              }
              <div class="stats-row">
                <span>{{ c.statuses_count | number }} posts</span>
                <span>{{ c.followers_count | number }} followers</span>
                @if (c.last_status_at) {
                  <span>Active {{ c.last_status_at | date: 'mediumDate' }}</span>
                }
                @if (c.followed_by_count > 0) {
                  <span class="friends-badge">
                    👥 {{ c.followed_by_count }} of your friends follow them
                  </span>
                }
              </div>
            </div>

            <div class="card-actions">
              <button class="btn-follow" (click)="followOne(c)" [disabled]="followingInProgress.has(c.id)">
                {{ followingInProgress.has(c.id) ? '…' : 'Follow' }}
              </button>
              <a class="btn-dossier" [href]="dossierHref(c.acct)" target="_blank" rel="noopener" (mousedown)="storeCandidateForDossier(c)">Dossier ↗</a>
            </div>
          </div>
        }
      </div>

      @if (!loading && allCandidates.length === 0 && fetchedAt) {
        <div class="empty-state">
          No candidates found with current filters. Try scanning more friends or relaxing filters.
        </div>
      }

      @if (!loading && !fetchedAt) {
        <div class="empty-state">
          Click "Download / Refresh" to scan your friends' following lists.
        </div>
      }
    </div>
  `,
  styles: [`
    .new-friends-page { padding: 16px; max-width: 900px; }
    .page-header { margin-bottom: 16px; }
    .page-title { margin: 0 0 4px; font-size: 1.5rem; }
    .page-subtitle { margin: 0; color: #6b7280; font-size: 0.9rem; }

    .controls-panel { background: #1e293b; border-radius: 8px; padding: 14px; margin-bottom: 16px; }
    .filter-row { display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 10px; align-items: flex-end; }
    .filter-row label { display: flex; flex-direction: column; gap: 4px; font-size: 0.85rem; color: #94a3b8; }
    .num-input { width: 70px; padding: 4px 6px; border-radius: 4px; border: 1px solid #334155; background: #0f172a; color: #e2e8f0; }
    .num-input-sm { width: 60px; padding: 4px 6px; border-radius: 4px; border: 1px solid #334155; background: #0f172a; color: #e2e8f0; }
    .select-input { padding: 4px 6px; border-radius: 4px; border: 1px solid #334155; background: #0f172a; color: #e2e8f0; }
    .text-input { padding: 4px 8px; border-radius: 4px; border: 1px solid #334155; background: #0f172a; color: #e2e8f0; width: 160px; }
    .hint { font-size: 0.75rem; color: #64748b; }

    .action-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
    .btn-primary { padding: 6px 14px; background: #6366f1; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 0.9rem; }
    .btn-primary:disabled { opacity: 0.5; cursor: default; }
    .btn-secondary { padding: 6px 12px; background: #334155; color: #e2e8f0; border: none; border-radius: 6px; cursor: pointer; font-size: 0.85rem; }
    .btn-secondary:disabled { opacity: 0.5; }
    .cache-info { font-size: 0.8rem; color: #64748b; }

    .facet-bar { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
    .facet-chip { padding: 4px 10px; border-radius: 20px; border: 1px solid #334155; background: #1e293b; color: #94a3b8; cursor: pointer; font-size: 0.8rem; }
    .facet-chip.active { background: #4f46e5; color: white; border-color: #4f46e5; }
    .facet-chip.clear { border-color: #6b7280; color: #6b7280; }

    .results-summary { font-size: 0.85rem; color: #64748b; margin-bottom: 8px; }

    .bulk-bar { display: flex; align-items: center; gap: 10px; padding: 10px 14px; background: #1e3a5f; border-radius: 6px; margin-bottom: 12px; flex-wrap: wrap; }
    .btn-follow-bulk { padding: 6px 14px; background: #10b981; color: white; border: none; border-radius: 6px; cursor: pointer; }
    .btn-follow-bulk:disabled { opacity: 0.5; }
    .btn-secondary-sm { padding: 4px 10px; background: #334155; color: #e2e8f0; border: none; border-radius: 6px; cursor: pointer; font-size: 0.8rem; }
    .bulk-result { font-size: 0.85rem; color: #10b981; }

    .loading-block { display: flex; align-items: center; gap: 12px; padding: 24px; color: #94a3b8; }
    .spinner { width: 20px; height: 20px; border: 2px solid #334155; border-top-color: #6366f1; border-radius: 50%; animation: spin 0.8s linear infinite; }
    @keyframes spin { to { transform: rotate(360deg); } }

    .candidate-list { display: flex; flex-direction: column; gap: 8px; }
    .candidate-card { display: flex; align-items: flex-start; gap: 12px; padding: 12px; background: #1e293b; border-radius: 8px; border: 1px solid #334155; }
    .candidate-card.selected { border-color: #4f46e5; background: #1e2a4a; }

    .check-wrap { display: flex; align-items: center; padding-top: 2px; }
    .avatar { width: 44px; height: 44px; border-radius: 50%; flex-shrink: 0; border: 2px solid #334155; object-fit: cover; }

    .candidate-info { flex: 1; min-width: 0; }
    .name-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 4px; }
    .display-name { font-weight: 600; color: #e2e8f0; }
    .acct { color: #64748b; font-size: 0.85rem; }
    .badge { font-size: 0.7rem; padding: 1px 6px; border-radius: 4px; }
    .badge.bot { background: #7c3aed; color: white; }
    .badge.locked { background: #374151; }
    .bio { margin: 0 0 6px; font-size: 0.85rem; color: #94a3b8; line-height: 1.4; }
    .stats-row { display: flex; gap: 12px; font-size: 0.8rem; color: #64748b; flex-wrap: wrap; }
    .friends-badge { color: #a78bfa; }

    .card-actions { display: flex; flex-direction: column; gap: 6px; flex-shrink: 0; }
    .btn-follow { padding: 5px 12px; background: #10b981; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 0.85rem; white-space: nowrap; }
    .btn-follow:disabled { opacity: 0.5; }
    .btn-dossier { padding: 5px 12px; background: #334155; color: #e2e8f0; border: none; border-radius: 6px; cursor: pointer; font-size: 0.85rem; }

    .empty-state { text-align: center; padding: 40px; color: #64748b; }
    .error-msg { background: #7f1d1d; color: #fca5a5; padding: 10px 14px; border-radius: 6px; margin-bottom: 12px; }
  `],
})
export class NewFriendsComponent implements OnInit, OnDestroy {
  private api = inject(ApiService);
  private destroy$ = new Subject<void>();

  // Filter state
  maxFriends = 50;
  blogRollFilter = '';
  minPosts = 1;
  activeSinceDays = 365;
  bioContains = '';

  // Data state
  loading = false;
  error: string | null = null;
  allCandidates: NewFriendCandidate[] = [];
  displayed: NewFriendCandidate[] = [];
  fetchedAt: string | null = null;
  cacheHit = false;
  totalDownloaded = 0;

  // Selection state
  selectedIds = new Set<string>();
  followingInProgress = new Set<string>();
  bulkFollowInProgress = false;
  bulkFollowResult: string | null = null;

  facets: FacetChip[] = [
    { id: 'no-bot', label: 'Bot-free', active: false, test: (c) => !c.bot },
    { id: 'has-bio', label: 'Has bio', active: false, test: (c) => (c.note?.length ?? 0) > 10 },
    { id: 'active-30d', label: 'Active 30d', active: false, test: (c) => this.activeWithin(c, 30) },
    { id: 'active-90d', label: 'Active 90d', active: false, test: (c) => this.activeWithin(c, 90) },
    { id: 'not-locked', label: 'Not locked', active: false, test: (c) => !c.locked },
    { id: 'multi-friend', label: '2+ friends follow', active: false, test: (c) => c.followed_by_count >= 2 },
  ];

  ngOnInit(): void {
    const identityId = this.api.getCurrentIdentityId();
    if (identityId) {
      this.loadCached(identityId);
    }
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  private activeWithin(c: NewFriendCandidate, days: number): boolean {
    if (!c.last_status_at) return false;
    try {
      const last = new Date(c.last_status_at);
      const cutoff = new Date(Date.now() - days * 86400_000);
      return last >= cutoff;
    } catch {
      return false;
    }
  }

  private loadCached(identityId: number): void {
    this.loading = true;
    this.error = null;
    this.api
      .getNewFriendsCandidates(identityId, {
        min_posts: this.minPosts,
        active_since_days: this.activeSinceDays,
        bio_contains: this.bioContains,
        max_friends: this.maxFriends,
        blog_roll_filter: this.blogRollFilter || undefined,
        limit: 1000,
      })
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (resp) => {
          this.allCandidates = resp.candidates;
          this.totalDownloaded = resp.total_downloaded;
          this.fetchedAt = resp.fetched_at;
          this.cacheHit = resp.cache_hit;
          this.applyFacets();
          this.loading = false;
        },
        error: (err) => {
          this.error = err?.error?.detail ?? 'Failed to load candidates.';
          this.loading = false;
        },
      });
  }

  loadFresh(): void {
    const identityId = this.api.getCurrentIdentityId();
    if (!identityId) return;
    this.loading = true;
    this.error = null;
    this.bulkFollowResult = null;
    this.api
      .refreshNewFriendsCache(identityId, this.maxFriends, this.blogRollFilter || undefined)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: () => this.loadCached(identityId),
        error: (err) => {
          this.error = err?.error?.detail ?? 'Refresh failed.';
          this.loading = false;
        },
      });
  }

  applyFilters(): void {
    const identityId = this.api.getCurrentIdentityId();
    if (!identityId) return;
    this.loadCached(identityId);
  }

  toggleFacet(facet: FacetChip): void {
    facet.active = !facet.active;
    this.applyFacets();
  }

  clearFacets(): void {
    this.facets.forEach((f) => (f.active = false));
    this.applyFacets();
  }

  private applyFacets(): void {
    const active = this.facets.filter((f) => f.active);
    if (active.length === 0) {
      this.displayed = [...this.allCandidates];
    } else {
      this.displayed = this.allCandidates.filter((c) => active.every((f) => f.test(c)));
    }
  }

  toggleSelect(id: string): void {
    if (this.selectedIds.has(id)) {
      this.selectedIds.delete(id);
    } else {
      this.selectedIds.add(id);
    }
    this.selectedIds = new Set(this.selectedIds);
  }

  clearSelection(): void {
    this.selectedIds = new Set();
  }

  followOne(candidate: NewFriendCandidate): void {
    const identityId = this.api.getCurrentIdentityId();
    if (!identityId) return;
    this.followingInProgress = new Set(this.followingInProgress).add(candidate.id);
    this.api
      .followAccount(candidate.acct, identityId)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: () => {
          this.allCandidates = this.allCandidates.filter((c) => c.id !== candidate.id);
          this.applyFacets();
          const next = new Set(this.followingInProgress);
          next.delete(candidate.id);
          this.followingInProgress = next;
        },
        error: () => {
          const next = new Set(this.followingInProgress);
          next.delete(candidate.id);
          this.followingInProgress = next;
        },
      });
  }

  followSelected(): void {
    const identityId = this.api.getCurrentIdentityId();
    if (!identityId || this.selectedIds.size === 0) return;
    this.bulkFollowInProgress = true;
    this.bulkFollowResult = null;

    const toFollow = [...this.selectedIds];
    const promises = toFollow.map((id) => {
      const candidate = this.allCandidates.find((c) => c.id === id);
      if (!candidate) return Promise.resolve();
      return this.api.followAccount(candidate.acct, identityId).toPromise().catch(() => null);
    });

    Promise.all(promises).then(() => {
      this.allCandidates = this.allCandidates.filter((c) => !this.selectedIds.has(c.id));
      this.applyFacets();
      const count = toFollow.length;
      this.bulkFollowResult = `Followed ${count} account${count !== 1 ? 's' : ''}.`;
      this.selectedIds = new Set();
      this.bulkFollowInProgress = false;
    });
  }

  dossierHref(acct: string): string {
    const identityId = this.api.getCurrentIdentityId();
    const query = identityId ? `?identity_id=${identityId}` : '';
    return `/#/peeps/dossier/${encodeURIComponent(acct)}${query}`;
  }

  storeCandidateForDossier(candidate: NewFriendCandidate): void {
    try {
      localStorage.setItem(
        `dossier_hint_${candidate.acct}`,
        JSON.stringify({ ...candidate, _stored_at: Date.now() }),
      );
    } catch {
      // storage full — ignore
    }
  }
}
