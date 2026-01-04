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

  constructor(private route: ActivatedRoute, private api: ApiService) {}

  ngOnInit() {
    this.route.queryParams.subscribe(params => {
      this.currentFilter = params['filter'] || 'all';
      this.load(this.currentFilter);
    });
  }

  load(filter: string) {
    this.loading = true;
    this.items = [];

    // If 'all', use the Storms endpoint for the threaded view
    if (filter === 'all') {
      this.isStormView = true;
      this.api.getStorms().subscribe({
        next: (data) => { this.items = data; this.loading = false; },
        error: () => this.loading = false
      });
    } else {
      // Otherwise use the standard flat list with the specific filter
      this.isStormView = false;
      this.api.getPublicPosts(filter).subscribe({
        next: (data) => { this.items = data; this.loading = false; },
        error: () => this.loading = false
      });
    }
  }

  stripHtml(html: string) { return (html || '').replace(/<[^>]+>/g, '').trim(); }

  getImages(post: any) {
    // Handle storm root vs regular post structure if needed,
    // but the API ensures 'media' or 'media_attachments' exists.
    const media = post.media_attachments || post.media || [];
    return media.filter((m: any) => m.type === 'image');
  }
}
