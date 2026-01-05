// web/src/app/public-feed.component.ts

import { Component, OnInit } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { ApiService } from './api.service';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-public-feed',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: "public-feed.component.html"
})
export class PublicFeedComponent implements OnInit {
  items: any[] = []; // Can be Posts or Storms
  loading = true;
  isStormView = false;
  currentFilter = 'all';
  currentUser: string | undefined;
  syncingUser = false; // Add this flag to prevent infinite loops

  constructor(private route: ActivatedRoute, private api: ApiService) {}

  ngOnInit() {
    this.route.queryParams.subscribe(params => {
      this.currentFilter = params['filter'] || 'all';
      this.currentUser = params['user'];
      this.syncingUser = false; // Reset sync flag on nav change
      this.load(this.currentFilter, this.currentUser);
    });
  }

  load(filter: string, user?: string) {
    this.loading = true;
    this.items = [];

    // Define the success handler to reuse
    const handleSuccess = (data: any[]) => {
      this.loading = false;

      // If we got no data, we are viewing a specific user, and we haven't tried syncing yet...
      if (data.length === 0 && user && !this.syncingUser) {
        this.attemptUserSync(user);
      } else {
        this.items = data;
      }
    };

    const handleError = () => this.loading = false;

    // If 'all', use the Storms endpoint for the threaded view
    if (filter === 'all') {
      this.isStormView = true;
      this.api.getStorms(user).subscribe({ next: handleSuccess, error: handleError });
    } else {
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
        console.error("Failed to sync user", err);
        this.loading = false;
      }
    });
  }

  stripHtml(html: string) { return (html || '').replace(/<[^>]+>/g, '').trim(); }

  getImages(post: any) {
    // Handle storm root vs regular post structure if needed,
    // but the API ensures 'media' or 'media_attachments' exists.
    const media = post.media_attachments || post.media || [];
    return media.filter((m: any) => m.type === 'image');
  }
}
