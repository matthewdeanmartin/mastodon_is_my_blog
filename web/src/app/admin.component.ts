import { Component, OnInit, OnDestroy, inject } from '@angular/core';
import { ApiService } from './api.service';
import { CommonModule } from '@angular/common';
import { AdminStatus, CatchupStatus, CatchupQueue } from './mastodon';
import { Subscription, interval } from 'rxjs';
import { switchMap } from 'rxjs/operators';

@Component({
  selector: 'app-admin',
  standalone: true,
  imports: [CommonModule],
  templateUrl: 'admin.component.html',
})
export class AdminComponent implements OnInit, OnDestroy {
  api = inject(ApiService);

  status: AdminStatus | null = null;
  syncing = false;

  catchupStatus: CatchupStatus | null = null;
  catchupQueue: CatchupQueue | null = null;
  catchupLoading = false;
  catchupError: string | null = null;

  private pollSub?: Subscription;

  ngOnInit() {
    this.refreshStatus();
    this.loadCatchupQueue();
    this.checkCatchupStatus();
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

  loadCatchupQueue() {
    this.api.getCatchupQueue().subscribe({
      next: (q) => (this.catchupQueue = q),
      error: () => {},
    });
  }

  checkCatchupStatus() {
    this.api.getCatchupStatus().subscribe({
      next: (s) => {
        this.catchupStatus = s;
        if (s.running) this.startPolling();
      },
      error: () => {},
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
      error: () => {},
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
}
