import { ChangeDetectionStrategy, Component, computed, effect, input, output, signal } from '@angular/core';

import { LiteFollowCandidate } from './lite.models';

@Component({
  selector: 'app-lite-bulk-accounts',
  templateUrl: './lite-bulk-accounts.component.html',
  styleUrl: './lite-bulk-accounts.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LiteBulkAccountsComponent {
  readonly accounts = input.required<LiteFollowCandidate[]>();
  readonly actionLabel = input('Follow');
  readonly busy = input(false);
  readonly result = input<string | null>(null);
  readonly showDirectoryLinks = input(true);
  readonly submitted = output<LiteFollowCandidate[]>();
  readonly directoryRequested = output<boolean>();

  readonly selected = signal<ReadonlySet<string>>(new Set());
  readonly selectedAccounts = computed(() =>
    this.accounts().filter((candidate) => this.selected().has(candidate.acct)),
  );

  constructor() {
    effect(() => {
      const accounts = this.accounts();
      this.selected.set(new Set(accounts.map((candidate) => candidate.acct)));
    });
  }

  toggle(acct: string): void {
    const next = new Set(this.selected());
    if (next.has(acct)) next.delete(acct);
    else next.add(acct);
    this.selected.set(next);
  }

  selectAll(): void {
    this.selected.set(new Set(this.accounts().map((candidate) => candidate.acct)));
  }

  clear(): void {
    this.selected.set(new Set());
  }
}
