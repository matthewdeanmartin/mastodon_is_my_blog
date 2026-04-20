import { Component, OnInit, OnDestroy, inject } from '@angular/core';
import { ApiService } from './api.service';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import {
  AdminStatus,
  CatchupStatus,
  CatchupQueue,
  AdminBundle,
  AdminBundleTerm,
  OwnAccountCatchupResult,
  BulkSyncJobStatus,
  NlpBackfillStatus,
} from './mastodon';
import { Subscription, interval } from 'rxjs';
import { switchMap } from 'rxjs/operators';

interface TermDraft {
  term: string;
  term_type: 'hashtag' | 'search';
}

interface BundleEditState {
  bundleId: number | null; // null = creating new
  name: string;
  terms: TermDraft[];
  saving: boolean;
  error: string | null;
}

@Component({
  selector: 'app-admin',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: 'admin.component.html',
})
export class AdminComponent implements OnInit, OnDestroy {
  api = inject(ApiService);

  status: AdminStatus | null = null;
  syncing = false;
  ownAccountSyncing = false;
  ownAccountMessage: string | null = null;
  ownAccountError: string | null = null;

  catchupStatus: CatchupStatus | null = null;
  catchupQueue: CatchupQueue | null = null;
  catchupLoading = false;
  catchupError: string | null = null;

  // Download-all-friends (paginated following/followers backfill)
  followingJob: BulkSyncJobStatus | null = null;
  followingJobError: string | null = null;
  followingJobLoading = false;
  private followingPollSub?: Subscription;

  // Download-all-notifications (paginated notification backfill)
  notificationsJob: BulkSyncJobStatus | null = null;
  notificationsJobError: string | null = null;
  notificationsJobLoading = false;
  private notificationsPollSub?: Subscription;

  // NLP topic backfill
  nlpStatus: NlpBackfillStatus | null = null;
  nlpJobLoading = false;
  nlpJobError: string | null = null;
  private nlpPollSub?: Subscription;

  // Bundle management
  bundles: AdminBundle[] = [];
  bundlesLoading = false;
  bundlesError: string | null = null;
  editState: BundleEditState | null = null;
  deletingId: number | null = null;
  syncingFollows = false;

  private pollSub?: Subscription;

  ngOnInit() {
    this.refreshStatus();
    this.loadCatchupQueue();
    this.checkCatchupStatus();
    this.checkFollowingJob();
    this.checkNotificationsJob();
    this.checkNlpBackfill();
    this.loadBundles();
  }

  ngOnDestroy() {
    this.stopPolling();
    this.stopFollowingPolling();
    this.stopNotificationsPolling();
    this.stopNlpPolling();
  }

  refreshStatus() {
    this.api.getAdminStatus().subscribe((s) => (this.status = s));
  }

  sync() {
    this.syncing = true;
    this.api.triggerSync(true).subscribe({
      next: () => {
        this.syncing = false;
        this.refreshStatus();
        alert('Sync complete!');
      },
      error: () => (this.syncing = false),
    });
  }

  catchupOwnAccount() {
    this.ownAccountSyncing = true;
    this.ownAccountMessage = null;
    this.ownAccountError = null;
    const identityId = this.currentIdentityId();
    this.api.catchupOwnAccount(identityId).subscribe({
      next: (result: OwnAccountCatchupResult) => {
        this.ownAccountSyncing = false;
        this.refreshStatus();
        const importedCount = result.count ?? 0;
        this.ownAccountMessage =
          importedCount === 1
            ? 'Imported 1 post from your own account history.'
            : `Imported ${importedCount} posts from your own account history.`;
      },
      error: (err) => {
        this.ownAccountSyncing = false;
        this.ownAccountError = err?.error?.detail ?? 'Failed to import your own account history';
      },
    });
  }

  loadCatchupQueue() {
    this.api.getCatchupQueue().subscribe({
      next: (q) => (this.catchupQueue = q),
      error: (err) => {
        this.catchupError = err?.error?.detail ?? 'Failed to load catch-up queue';
      },
    });
  }

  checkCatchupStatus() {
    this.api.getCatchupStatus().subscribe({
      next: (s) => {
        this.catchupStatus = s;
        if (s.running) this.startPolling();
      },
      error: (err) => {
        if (err?.status !== 404) {
          this.catchupError = err?.error?.detail ?? 'Failed to load catch-up status';
        }
      },
    });
  }

  startCatchup(mode: 'urgent' | 'trickle') {
    this.catchupLoading = true;
    this.catchupError = null;
    this.api.startCatchup(mode).subscribe({
      next: (s) => {
        this.catchupStatus = s;
        this.catchupLoading = false;
        this.startPolling();
      },
      error: (err) => {
        this.catchupLoading = false;
        this.catchupError = err?.error?.detail ?? 'Failed to start catch-up';
      },
    });
  }

  stopCatchup() {
    this.api.cancelCatchup().subscribe({
      next: () => this.checkCatchupStatus(),
      error: (err) => {
        this.catchupError = err?.error?.detail ?? 'Failed to stop catch-up';
      },
    });
  }

  private startPolling() {
    this.stopPolling();
    this.pollSub = interval(2000)
      .pipe(switchMap(() => this.api.getCatchupStatus()))
      .subscribe({
        next: (s) => {
          this.catchupStatus = s;
          if (!s.running) {
            this.stopPolling();
            this.api.refreshNeeded$.next();
            this.loadCatchupQueue();
          }
        },
        error: () => this.stopPolling(),
      });
  }

  private stopPolling() {
    this.pollSub?.unsubscribe();
    this.pollSub = undefined;
  }

  // --- Download all friends (paginated backfill) ---

  checkFollowingJob() {
    const identityId = this.currentIdentityId();
    if (!identityId) return;
    this.api.getSyncAllFollowingStatus(identityId).subscribe({
      next: (s) => {
        this.followingJob = s;
        if (!s.finished) this.startFollowingPolling();
      },
      error: (err) => {
        if (err?.status !== 404) {
          this.followingJobError = err?.error?.detail ?? 'Failed to load friends-sync status';
        }
      },
    });
  }

  startSyncAllFollowing() {
    const identityId = this.currentIdentityId();
    if (!identityId || this.followingJobLoading) return;
    this.followingJobLoading = true;
    this.followingJobError = null;
    this.api.startSyncAllFollowing(identityId).subscribe({
      next: (s) => {
        this.followingJob = s;
        this.followingJobLoading = false;
        this.startFollowingPolling();
      },
      error: (err) => {
        this.followingJobLoading = false;
        this.followingJobError = err?.error?.detail ?? 'Failed to start friends backfill';
      },
    });
  }

  cancelSyncAllFollowing() {
    const identityId = this.currentIdentityId();
    if (!identityId) return;
    this.api.cancelSyncAllFollowing(identityId).subscribe({
      next: () => this.checkFollowingJob(),
      error: (err) => {
        this.followingJobError = err?.error?.detail ?? 'Failed to cancel';
      },
    });
  }

  private startFollowingPolling() {
    this.stopFollowingPolling();
    const identityId = this.currentIdentityId();
    if (!identityId) return;
    this.followingPollSub = interval(2000)
      .pipe(switchMap(() => this.api.getSyncAllFollowingStatus(identityId)))
      .subscribe({
        next: (s) => {
          this.followingJob = s;
          if (s.finished) {
            this.stopFollowingPolling();
            this.api.refreshNeeded$.next();
          }
        },
        error: () => this.stopFollowingPolling(),
      });
  }

  private stopFollowingPolling() {
    this.followingPollSub?.unsubscribe();
    this.followingPollSub = undefined;
  }

  get followingProgressPct(): number {
    const j = this.followingJob;
    if (!j || !j.total || j.total === 0) return 0;
    return Math.min(100, Math.round((j.done / j.total) * 100));
  }

  // --- Download all notifications (paginated backfill) ---

  checkNotificationsJob() {
    const identityId = this.currentIdentityId();
    if (!identityId) return;
    this.api.getSyncAllNotificationsStatus(identityId).subscribe({
      next: (s) => {
        this.notificationsJob = s;
        if (!s.finished) this.startNotificationsPolling();
      },
      error: (err) => {
        if (err?.status !== 404) {
          this.notificationsJobError =
            err?.error?.detail ?? 'Failed to load notifications-sync status';
        }
      },
    });
  }

  startSyncAllNotifications() {
    const identityId = this.currentIdentityId();
    if (!identityId || this.notificationsJobLoading) return;
    this.notificationsJobLoading = true;
    this.notificationsJobError = null;
    this.api.startSyncAllNotifications(identityId).subscribe({
      next: (s) => {
        this.notificationsJob = s;
        this.notificationsJobLoading = false;
        this.startNotificationsPolling();
      },
      error: (err) => {
        this.notificationsJobLoading = false;
        this.notificationsJobError = err?.error?.detail ?? 'Failed to start notifications backfill';
      },
    });
  }

  cancelSyncAllNotifications() {
    const identityId = this.currentIdentityId();
    if (!identityId) return;
    this.api.cancelSyncAllNotifications(identityId).subscribe({
      next: () => this.checkNotificationsJob(),
      error: (err) => {
        this.notificationsJobError = err?.error?.detail ?? 'Failed to cancel';
      },
    });
  }

  private startNotificationsPolling() {
    this.stopNotificationsPolling();
    const identityId = this.currentIdentityId();
    if (!identityId) return;
    this.notificationsPollSub = interval(2000)
      .pipe(switchMap(() => this.api.getSyncAllNotificationsStatus(identityId)))
      .subscribe({
        next: (s) => {
          this.notificationsJob = s;
          if (s.finished) {
            this.stopNotificationsPolling();
            this.api.refreshNeeded$.next();
          }
        },
        error: () => this.stopNotificationsPolling(),
      });
  }

  private stopNotificationsPolling() {
    this.notificationsPollSub?.unsubscribe();
    this.notificationsPollSub = undefined;
  }

  get progressPct(): number {
    if (!this.catchupStatus || this.catchupStatus.total === 0) return 0;
    return Math.round((this.catchupStatus.done / this.catchupStatus.total) * 100);
  }

  trackByAcct(_i: number, entry: { acct: string }): string {
    return entry.acct;
  }

  // --- NLP topic backfill ---

  checkNlpBackfill() {
    this.api.getNlpBackfillStatus().subscribe({
      next: (s) => {
        this.nlpStatus = s;
        if (s.job && !s.job.finished) this.startNlpPolling();
      },
      error: () => {},
    });
  }

  startNlpBackfillJob() {
    if (this.nlpJobLoading) return;
    this.nlpJobLoading = true;
    this.nlpJobError = null;
    this.api.startNlpBackfill().subscribe({
      next: (s) => {
        this.nlpStatus = s as unknown as NlpBackfillStatus;
        this.nlpJobLoading = false;
        this.startNlpPolling();
      },
      error: (err) => {
        this.nlpJobLoading = false;
        this.nlpJobError = err?.error?.detail ?? 'Failed to start NLP backfill';
      },
    });
  }

  cancelNlpBackfillJob() {
    this.api.cancelNlpBackfill().subscribe({
      next: () => this.checkNlpBackfill(),
      error: (err) => {
        this.nlpJobError = err?.error?.detail ?? 'Failed to cancel';
      },
    });
  }

  private startNlpPolling() {
    this.stopNlpPolling();
    this.nlpPollSub = interval(2000)
      .pipe(switchMap(() => this.api.getNlpBackfillStatus()))
      .subscribe({
        next: (s) => {
          this.nlpStatus = s;
          if (!s.job || s.job.finished) this.stopNlpPolling();
        },
        error: () => this.stopNlpPolling(),
      });
  }

  private stopNlpPolling() {
    this.nlpPollSub?.unsubscribe();
    this.nlpPollSub = undefined;
  }

  get nlpProgressPct(): number {
    const j = this.nlpStatus?.job;
    if (!j || !j.total || j.total === 0) return 0;
    return Math.min(100, Math.round((j.done / j.total) * 100));
  }

  // --- Recompute post stats ---

  recomputingStats = false;
  recomputeStatsMessage: string | null = null;
  recomputeStatsError: string | null = null;

  recomputePostStats() {
    const identityId = this.currentIdentityId();
    if (!identityId || this.recomputingStats) return;
    this.recomputingStats = true;
    this.recomputeStatsMessage = null;
    this.recomputeStatsError = null;
    this.api.recomputePostStats(identityId).subscribe({
      next: (r) => {
        this.recomputingStats = false;
        this.recomputeStatsMessage = `Updated ${r['updated']} accounts (${r['total_authors']} with cached posts).`;
      },
      error: (err) => {
        this.recomputingStats = false;
        this.recomputeStatsError = err?.error?.detail ?? 'Failed to recompute stats';
      },
    });
  }

  // --- Bundle management ---

  private currentIdentityId(): number | null {
    return this.api.getCurrentIdentityId();
  }

  loadBundles() {
    const identityId = this.currentIdentityId();
    if (!identityId) return;
    this.bundlesLoading = true;
    this.bundlesError = null;
    this.api.getAdminBundles(identityId).subscribe({
      next: (b) => {
        this.bundles = b;
        this.bundlesLoading = false;
      },
      error: (err) => {
        this.bundlesError = err?.error?.detail ?? 'Failed to load bundles';
        this.bundlesLoading = false;
      },
    });
  }

  startCreateBundle() {
    this.editState = { bundleId: null, name: '', terms: [], saving: false, error: null };
  }

  startEditBundle(bundle: AdminBundle) {
    this.editState = {
      bundleId: bundle.id,
      name: bundle.name,
      terms: bundle.terms.map((t) => ({ term: t.term, term_type: t.term_type })),
      saving: false,
      error: null,
    };
  }

  cancelEdit() {
    this.editState = null;
  }

  addTerm() {
    if (!this.editState) return;
    this.editState.terms.push({ term: '', term_type: 'hashtag' });
  }

  removeTerm(index: number) {
    if (!this.editState) return;
    this.editState.terms.splice(index, 1);
  }

  saveBundle() {
    if (!this.editState) return;
    const identityId = this.currentIdentityId();
    if (!identityId) return;

    const name = this.editState.name.trim();
    if (!name) {
      this.editState.error = 'Name is required';
      return;
    }
    const terms = this.editState.terms
      .map((t) => ({ term: t.term.trim(), term_type: t.term_type }))
      .filter((t) => t.term.length > 0);

    this.editState.saving = true;
    this.editState.error = null;

    const { bundleId } = this.editState;

    const req$ =
      bundleId === null
        ? this.api.createAdminBundle(identityId, name, terms)
        : this.api.updateAdminBundle(identityId, bundleId, name, terms);

    req$.subscribe({
      next: () => {
        this.editState = null;
        this.loadBundles();
      },
      error: (err) => {
        if (this.editState) {
          this.editState.saving = false;
          this.editState.error = err?.error?.detail ?? 'Save failed';
        }
      },
    });
  }

  deleteBundle(bundle: AdminBundle) {
    if (!confirm(`Delete bundle "${bundle.name}"?`)) return;
    const identityId = this.currentIdentityId();
    if (!identityId) return;
    this.deletingId = bundle.id;
    this.api.deleteAdminBundle(identityId, bundle.id).subscribe({
      next: () => {
        this.deletingId = null;
        this.loadBundles();
      },
      error: () => {
        this.deletingId = null;
      },
    });
  }

  syncFollows() {
    const identityId = this.currentIdentityId();
    if (!identityId || this.syncingFollows) return;
    this.syncingFollows = true;
    this.api.syncContentHubFollows(identityId).subscribe({
      next: () => {
        this.syncingFollows = false;
        this.loadBundles();
      },
      error: () => {
        this.syncingFollows = false;
      },
    });
  }

  trackByBundleId(_i: number, b: AdminBundle): number {
    return b.id;
  }

  trackByTermIndex(i: number): number {
    return i;
  }

  termTypeLabel(t: AdminBundleTerm | TermDraft): string {
    return t.term_type === 'hashtag' ? '#' : '🔍';
  }
}
