// web/src/app/feed.component.ts

import { Component, OnInit } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { ApiService } from './api.service';
import { CommonModule } from '@angular/common';
import { DomSanitizer } from '@angular/platform-browser';

@Component({
  selector: 'app-public-feed',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: 'feed.component.html',
})
export class PublicFeedComponent implements OnInit {
  items: any[] = []; // Can be Posts or Storms
  loading = true;
  isStormView = false;
  currentFilter = 'storms';
  currentUser: string | undefined;
  syncingUser = false; // Add this flag to prevent infinite loops

  constructor(
    private route: ActivatedRoute,
    private api: ApiService,
    private sanitizer: DomSanitizer,
  ) {}


   ngOnInit() {
    this.route.queryParams.subscribe((params) => {
      // Default to 'storms' if no filter is provided
      const newFilter = params['filter'] || 'storms';
      const userParam = params['user'] || undefined;

      // FIX: Do NOT convert 'everyone' to undefined.
      // We must pass 'everyone' to the API so it knows to disable the default "My Blog" filter.
      const newUser = userParam;

      // Check if anything actually changed
      const filterChanged = newFilter !== this.currentFilter;
      const userChanged = newUser !== this.currentUser;

      this.currentFilter = newFilter;
      this.currentUser = newUser;

      // Reset sync flag when navigation happens
      if (filterChanged || userChanged) {
        this.syncingUser = false;
        this.load(this.currentFilter, this.currentUser);
      }
    });
  }

  load(filter: string, user?: string) {
    this.loading = true;
    this.items = [];

    // Define the success handler to reuse
    const handleSuccess = (data: any[]) => {
      this.loading = false;

      // If we got no data, we are viewing a specific user, and we haven't tried syncing yet...
      // FIX: Ensure we don't try to sync the virtual 'everyone' user
      if (data.length === 0 && user && user !== 'everyone' && filter !== 'everyone' && !this.syncingUser) {
        this.attemptUserSync(user);
      } else {
        this.items = data;
      }
    };

    const handleError = () => (this.loading = false);

    // If 'storms' (or legacy 'all'), use the Storms endpoint for the threaded view
    if (filter === 'storms' || filter === 'all') {
      this.isStormView = true;
      this.api.getStorms(user).subscribe({ next: handleSuccess, error: handleError });
    }
    // If 'shorts', use the new Shorts endpoint for flat view
    else if (filter === 'shorts') {
      this.isStormView = false;
      this.api.getShorts(user).subscribe({ next: handleSuccess, error: handleError });
    }
    else {
      // Otherwise use the standard flat list with the specific filter
      this.isStormView = false;
      this.api.getPublicPosts(filter, user).subscribe({ next: handleSuccess, error: handleError });
    }
  }

  attemptUserSync(acct: string) {
    this.syncingUser = true;
    this.loading = true; // Keep loading spinner up

    // We only try this once per navigation to avoid loops
    this.api.syncAccount(acct).subscribe({
      next: (res) => {
        // Sync finished, try loading the feed again
        // We leave syncingUser=true so we don't try again if it's still empty
        this.load(this.currentFilter, acct);
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
    const username = parts[0];
    const instance = parts[1] || 'mastodon.social';

    return `https://${instance}/@${username}/${post.id}`;
  }
}
