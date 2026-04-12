// web/src/app/content-hub-group.component.ts
import { Component, OnInit, OnDestroy, inject } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { CommonModule } from '@angular/common';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { ApiService } from './api.service';
import { ContentHubPost } from './mastodon';
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
}

@Component({
  selector: 'app-content-hub-group',
  standalone: true,
  imports: [CommonModule],
  templateUrl: 'content-hub-group.component.html',
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
    };
  }

  trackById(_i: number, vm: PostViewModel): string {
    return vm.id;
  }
}
