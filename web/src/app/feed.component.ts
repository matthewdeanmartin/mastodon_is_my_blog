// web/src/app/feed.component.ts

import { Component, OnInit } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { ApiService } from './api.service';
import { CommonModule } from '@angular/common';
import { DomSanitizer } from '@angular/platform-browser';
import { LinkPreviewComponent } from './link.component';
import { LinkPreviewService } from './link.service';
import { combineLatest } from 'rxjs';
import { HttpErrorResponse } from '@angular/common/http'; // Import HttpErrorResponse

@Component({
  selector: 'app-public-feed',
  standalone: true,
  imports: [CommonModule, RouterLink, LinkPreviewComponent],
  templateUrl: 'feed.component.html',
})
export class PublicFeedComponent implements OnInit {
  items: any[] = [];
  loading = true;
  isStormView = false;
  currentFilter = 'storms';
  currentUser: string | undefined;
  syncingUser = false;

  // Track context
  currentIdentityId: number | null = null;

  constructor(
    private route: ActivatedRoute,
    private api: ApiService,
    private sanitizer: DomSanitizer,
    private linkPreviewService: LinkPreviewService,
  ) {}

  ngOnInit(): void {
    // Combine Route Params with Identity State
    combineLatest([this.route.queryParams, this.api.identityId$])
      .subscribe(([params, identityId]) => {
          this.currentIdentityId = identityId;

          if (!identityId) {
              this.loading = true; // Wait for identity
              return;
          }

          const newFilter = params['filter'] || 'storms';
          const newUser = params['user'] || undefined; // "everyone" passes through as string here

          // Reload if parameters changed or just initialized
          if (newFilter !== this.currentFilter || newUser !== this.currentUser || identityId) {
              this.currentFilter = newFilter;
              this.currentUser = newUser;
              this.syncingUser = false;
              this.load(this.currentFilter, this.currentUser, identityId);
          }
      });
  }

  load(filter: string, user: string | undefined, identityId: number): void {
    this.loading = true;
    this.items = [];

    // Define the success handler to reuse
    const handleSuccess = (data: any[]) => {
      this.loading = false;
      // If we got an empty list for a specific user, try syncing ONCE to see if they exist remotely
      if (data.length === 0 && user && user !== 'everyone' && filter !== 'everyone' && !this.syncingUser) {
        this.attemptUserSync(user, identityId);
      } else {
        this.items = data;
      }
    };

    const handleError = (error: HttpErrorResponse) => {
      if (error.status === 404 && user && user !== 'everyone' && !this.syncingUser) {
          console.log(`Posts not found (404) for ${user}, attempting JIT sync...`);
          this.attemptUserSync(user, identityId);
      } else {
          console.error(`Error loading posts (Status: ${error.status}):`, error);
          this.loading = false;
      }
    };

    // If 'storms' (or legacy 'all'), use the Storms endpoint for the threaded view
    if (filter === 'storms' || filter === 'all') {
      this.isStormView = true;
      this.api.getStorms(identityId, user).subscribe({ next: handleSuccess, error: handleError });
    }
    // If 'shorts', use the new Shorts endpoint for flat view
    else if (filter === 'shorts') {
      this.isStormView = false;
      this.api.getShorts(identityId, user).subscribe({ next: handleSuccess, error: handleError });
    }
    else {
      // Otherwise use the standard flat list with the specific filter
      this.isStormView = false;
      this.api.getPublicPosts(identityId, filter, user).subscribe({ next: handleSuccess, error: handleError });
    }
  }

  attemptUserSync(acct: string, identityId: number): void {
    this.syncingUser = true;
    this.loading = true;

    // We only try this once per navigation to avoid loops
    this.api.syncAccount(acct, identityId).subscribe({
      next: (res) => {
        // Retry load exactly once
        this.load(this.currentFilter, acct, identityId);
      },
      error: (err) => {
        console.error('Failed to sync user', err);
        this.loading = false;
      },
    });
  }

  stripHtml(html: string) {
    return this.sanitizer.bypassSecurityTrustHtml(html);
    // return (html || '').replace(/<[^>]+>/g, '').trim();
  }

  getImages(post: any) {
    // Handle storm root vs regular post structure if needed,
    // but the API ensures 'media' or 'media_attachments' exists.
    const media = post.media_attachments || post.media || [];
    return media.filter((m: any) => m.type === 'image');
  }
  getQueryParams() {
    const params: any = { filter: this.currentFilter };
    if (this.currentUser) {
      params.user = this.currentUser;
    }
    return params;
  }

   getOriginalPostUrl(post: any): string {
    const acct = post.author_acct;
    if (!acct) return '#';

    const parts = acct.split('@');
    return `https://${parts[1] || 'mastodon.social'}/@${parts[0]}/${post.id}`;
  }

  getPostUrls(post: any): string[] {
    // Extract URLs from post content for link previews
    return this.linkPreviewService.extractUrls(post.content || '');
  }
}
