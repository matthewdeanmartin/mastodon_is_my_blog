// web/src/app/content-hub-group.component.ts
import { Component, OnInit, OnDestroy, inject } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { CommonModule } from '@angular/common';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { ApiService } from './api.service';
import { ContentHubPost, MastodonMediaAttachment } from './mastodon';
import { Subscription, combineLatest } from 'rxjs';

type Tab = 'text' | 'videos' | 'jobs';

interface PostViewModel {
  id: string;
  safeHtml: SafeHtml;
  author_acct: string;
  author_display_name: string;
  author_avatar: string;
  created_at: string;
  counts: { replies: number; reblogs: number; likes: number };
  is_reblog: boolean;
  is_reply: boolean;
  videos: MastodonMediaAttachment[];
}

@Component({
  selector: 'app-content-hub-group',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: 'content-hub-group.component.html',
  styles: [
    `
      .group-header {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 16px;
        margin-bottom: 16px;
        flex-wrap: wrap;
      }

      .stale-badge {
        display: inline-block;
        background: #fef3c7;
        color: #92400e;
        font-size: 0.7rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        padding: 1px 5px;
        border-radius: 3px;
        margin-left: 6px;
      }

      .tab-bar {
        display: flex;
        gap: 6px;
        margin-bottom: 20px;
        border-bottom: 1px solid #e5e7eb;
        padding-bottom: 12px;
      }

      .tab-btn {
        padding: 5px 16px;
        background: white;
        border: 1px solid #d1d5db;
        border-radius: 999px;
        font-size: 0.85rem;
        cursor: pointer;
        color: #374151;
        transition: all 0.2s;
        font-weight: 500;
      }

      .tab-btn:hover {
        background: #f3f4f6;
        border-color: #6366f1;
      }

      .tab-btn.active {
        background: #6366f1;
        color: white;
        border-color: #6366f1;
      }

      .post-item {
        padding: 4px 0;
      }

      .badge {
        padding: 2px 8px;
        border-radius: 3px;
        font-size: 0.75rem;
        font-weight: 600;
      }

      .badge.reblog {
        background: #e3f2fd;
        color: #1976d2;
      }

      .badge.reply {
        background: #f3e5f5;
        color: #7b1fa2;
      }
    `,
  ],
})
export class ContentHubGroupComponent implements OnInit, OnDestroy {
  private route = inject(ActivatedRoute);
  private api = inject(ApiService);
  private sanitizer = inject(DomSanitizer);

  groupId: number | null = null;
  identityId: number | null = null;

  groupName = '';
  lastFetchedAt: string | null = null;
  stale = false;

  activeTab: Tab = 'text';
  readonly tabs: { value: Tab; label: string }[] = [
    { value: 'text', label: 'Text' },
    { value: 'videos', label: 'Videos' },
    { value: 'jobs', label: 'Jobs' },
  ];

  posts: PostViewModel[] = [];
  loading = false;
  loadingMore = false;
  refreshing = false;
  nextCursor: string | null = null;

  private sub?: Subscription;

  ngOnInit(): void {
    this.sub = combineLatest([this.route.paramMap, this.api.identityId$]).subscribe(
      ([params, identityId]) => {
        const id = params.get('groupId');
        if (!id || !identityId) return;
        this.groupId = parseInt(id, 10);
        this.identityId = identityId;
        this.loadPosts(true);
      },
    );
  }

  ngOnDestroy(): void {
    this.sub?.unsubscribe();
  }

  setTab(tab: Tab): void {
    if (this.activeTab === tab) return;
    this.activeTab = tab;
    this.loadPosts(true);
  }

  loadPosts(reset: boolean): void {
    if (!this.groupId || !this.identityId) return;
    if (reset) {
      this.posts = [];
      this.nextCursor = null;
      this.loading = true;
    } else {
      this.loadingMore = true;
    }

    this.api
      .getContentHubGroupPosts(
        this.groupId,
        this.identityId,
        this.activeTab,
        reset ? null : this.nextCursor,
      )
      .subscribe({
        next: (res) => {
          const vms = res.items.map((p) => this.toVm(p));
          this.posts = reset ? vms : [...this.posts, ...vms];
          this.nextCursor = res.next_cursor;
          this.stale = res.stale;
          this.groupName = res.group.name;
          this.lastFetchedAt = res.group.last_fetched_at;
          this.loading = false;
          this.loadingMore = false;
        },
        error: () => {
          this.loading = false;
          this.loadingMore = false;
        },
      });
  }

  forceRefresh(): void {
    if (!this.groupId || !this.identityId || this.refreshing) return;
    this.refreshing = true;
    this.api.refreshContentHubGroup(this.groupId, this.identityId).subscribe({
      next: () => {
        this.refreshing = false;
        this.loadPosts(true);
      },
      error: () => {
        this.refreshing = false;
      },
    });
  }

  loadMore(): void {
    if (this.loadingMore || !this.nextCursor) return;
    this.loadPosts(false);
  }

  private toVm(p: ContentHubPost): PostViewModel {
    return {
      id: p.id,
      safeHtml: this.sanitizer.bypassSecurityTrustHtml(p.content),
      author_acct: p.author_acct,
      author_display_name: p.author_display_name || p.author_acct,
      author_avatar: p.author_avatar,
      created_at: p.created_at,
      counts: p.counts,
      is_reblog: p.is_reblog,
      is_reply: p.is_reply,
      videos: (p.media_attachments ?? []).filter((m) => m.type === 'video' || m.type === 'gifv'),
    };
  }

  trackById(_i: number, vm: PostViewModel): string {
    return vm.id;
  }
}
