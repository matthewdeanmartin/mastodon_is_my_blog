import { Component, Input, OnChanges, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { ApiService } from './api.service';
import { MastodonStatus } from './mastodon';

@Component({
  selector: 'app-reply-context-panel',
  standalone: true,
  imports: [CommonModule],
  template: `
    @if (loading) {
      <div class="muted" style="padding: 12px; text-align: center;">Loading context…</div>
    }
    @for (post of ancestors; track post.id) {
      <div class="card" style="opacity: 0.85; margin-bottom: 8px; padding: 12px;">
        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
          <img [src]="post.account.avatar" alt="" style="width: 28px; height: 28px; border-radius: 50%;" />
          <div>
            <strong style="font-size: 0.9rem;">{{ post.account.display_name || post.account.acct }}</strong>
            <span class="muted" style="margin-left: 6px; font-size: 0.8rem;">&#64;{{ post.account.acct }}</span>
          </div>
          <small class="muted" style="margin-left: auto;">{{ post.created_at | date:'short' }}</small>
        </div>
        <div class="post-body" [innerHTML]="processContent(post.content)"></div>
      </div>
    }
    @if (target) {
      <div class="card" style="margin-bottom: 12px; padding: 12px; border-left: 4px solid #6366f1;">
        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
          <img [src]="target.account.avatar" alt="" style="width: 32px; height: 32px; border-radius: 50%;" />
          <div>
            <strong style="font-size: 0.95rem;">{{ target.account.display_name || target.account.acct }}</strong>
            <span class="muted" style="margin-left: 6px; font-size: 0.8rem;">&#64;{{ target.account.acct }}</span>
          </div>
          <small class="muted" style="margin-left: auto;">{{ target.created_at | date:'short' }}</small>
        </div>
        <div class="post-body" [innerHTML]="processContent(target.content)"></div>
        <div style="margin-top: 8px; padding-top: 8px; border-top: 1px solid #eee; font-size: 0.8rem; color: #888;">
          Replying to this post ↑
        </div>
      </div>
    }
  `,
})
export class ReplyContextPanelComponent implements OnChanges {
  @Input() statusId: string | null = null;

  private api = inject(ApiService);
  private sanitizer = inject(DomSanitizer);

  ancestors: MastodonStatus[] = [];
  target: MastodonStatus | null = null;
  loading = false;

  ngOnChanges(): void {
    if (!this.statusId) {
      this.ancestors = [];
      this.target = null;
      return;
    }
    this.loading = true;
    const identityId = this.api.getCurrentIdentityId();
    this.api.getPostContext(this.statusId, identityId ?? undefined).subscribe({
      next: (ctx) => {
        this.ancestors = ctx.ancestors ?? [];
        this.target = ctx.target ?? null;
        this.loading = false;
      },
      error: () => (this.loading = false),
    });
  }

  processContent(html: string): SafeHtml {
    if (!html) return '';
    const withTargetBlank = html.replace(/<a /g, '<a target="_blank" rel="noopener noreferrer" ');
    return this.sanitizer.bypassSecurityTrustHtml(withTargetBlank);
  }
}
