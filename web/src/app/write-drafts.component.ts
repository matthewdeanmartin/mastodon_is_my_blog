import { Component, OnInit, inject } from '@angular/core';
import { Router } from '@angular/router';
import { CommonModule } from '@angular/common';
import { ApiService } from './api.service';
import { Draft } from './mastodon';

@Component({
  selector: 'app-write-drafts',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="card" style="max-width: 700px; margin: 0 auto;">
      <div
        style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;"
      >
        <h2 style="margin: 0; font-size: 1.2rem;">Drafts</h2>
        <button (click)="newPost()">+ New post</button>
      </div>

      @if (loading) {
        <div class="muted" style="font-size: 0.9rem;">Loading…</div>
      } @else if (drafts.length === 0) {
        <div class="muted" style="font-size: 0.9rem; font-style: italic;">
          No saved drafts. Start a new post!
        </div>
        <div style="margin-top: 16px;">
          <button (click)="newPost()">+ New post</button>
        </div>
      } @else {
        @for (draft of drafts; track draft.id) {
          <div
            style="
              border: 1px solid #e5e7eb;
              border-radius: 8px;
              padding: 12px 14px;
              margin-bottom: 10px;
              display: flex;
              justify-content: space-between;
              align-items: flex-start;
              gap: 12px;
              cursor: pointer;
            "
            (click)="openDraft(draft.id)"
          >
            <div style="flex: 1; min-width: 0;">
              <div
                style="font-size: 0.88rem; font-weight: 500; margin-bottom: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;"
              >
                {{ draftPreview(draft) }}
              </div>
              <div style="font-size: 0.75rem; color: #888;">
                {{ nodeCount(draft) }} post{{ nodeCount(draft) !== 1 ? 's' : '' }}
                &nbsp;·&nbsp;
                {{ draft.updated_at | date: 'MMM d, y h:mm a' }}
                @if (draft.reply_to_status_id) {
                  &nbsp;·&nbsp; <span style="color: #6366f1;">reply</span>
                }
              </div>
            </div>
            <div style="display: flex; gap: 6px; flex-shrink: 0;">
              <button
                (click)="openDraft(draft.id); $event.stopPropagation()"
                style="font-size: 0.8rem; padding: 3px 10px;"
              >
                Edit
              </button>
              <button
                (click)="deleteDraft(draft.id, $event)"
                style="font-size: 0.8rem; padding: 3px 10px; background: none; border: 1px solid #fca5a5; color: #dc2626;"
              >
                Delete
              </button>
            </div>
          </div>
        }
      }
    </div>
  `,
})
export class WriteDraftsComponent implements OnInit {
  api = inject(ApiService);
  router = inject(Router);

  drafts: Draft[] = [];
  loading = true;

  ngOnInit(): void {
    this.api.listDrafts().subscribe({
      next: (d) => {
        this.drafts = d;
        this.loading = false;
      },
      error: () => {
        this.loading = false;
      },
    });
  }

  newPost(): void {
    this.router.navigate(['/write/new']);
  }

  openDraft(id: number): void {
    this.router.navigate(['/write/draft', id]);
  }

  deleteDraft(id: number, event: Event): void {
    event.stopPropagation();
    if (!confirm('Delete this draft?')) return;
    this.api.deleteDraft(id).subscribe(() => {
      this.drafts = this.drafts.filter((d) => d.id !== id);
    });
  }

  draftPreview(draft: Draft): string {
    try {
      const nodes = JSON.parse(draft.tree_json || '[]');
      const first = nodes[0]?.body?.trim();
      return first ? first.slice(0, 80) : '(empty)';
    } catch {
      return '(empty)';
    }
  }

  nodeCount(draft: Draft): number {
    try {
      return JSON.parse(draft.tree_json || '[]').length;
    } catch {
      return 0;
    }
  }
}
