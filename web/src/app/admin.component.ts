import { Component, OnInit, OnDestroy, inject } from '@angular/core';
import { ApiService } from './api.service';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { AdminStatus, CatchupStatus, CatchupQueue, AdminBundle, AdminBundleTerm, OwnAccountCatchupResult } from './mastodon';
import { Subscription, interval } from 'rxjs';
import { switchMap } from 'rxjs/operators';

interface TermDraft {
  term: string;
  term_type: 'hashtag' | 'search';
}

interface BundleEditState {
  bundleId: number | null;  // null = creating new
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
    this.loadBundles();
  }

  ngOnDestroy() {
    this.stopPolling();
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
        this.ownAccountMessage = importedCount === 1
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

  get progressPct(): number {
    if (!this.catchupStatus || this.catchupStatus.total === 0) return 0;
    return Math.round((this.catchupStatus.done / this.catchupStatus.total) * 100);
  }

  trackByAcct(_i: number, entry: { acct: string }): string {
    return entry.acct;
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

    const req$ = bundleId === null
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
