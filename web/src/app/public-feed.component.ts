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
  posts: any[] = [];
  loading = true;

  constructor(private route: ActivatedRoute, private api: ApiService) {}

  ngOnInit() {
    this.route.queryParams.subscribe(params => {
      const filter = params['filter'] || 'all';
      this.load(filter);
    });
  }

  load(filter: string) {
    this.loading = true;
    this.api.getPublicPosts(filter).subscribe({
      next: (data) => { this.posts = data; this.loading = false; },
      error: () => this.loading = false
    });
  }

  stripHtml(html: string) { return (html || '').replace(/<[^>]+>/g, '').trim(); }

  getImages(post: any) {
    return post.media_attachments?.filter((m: any) => m.type === 'image') || [];
  }
}
