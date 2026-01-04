import { Component, OnInit } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { ApiService } from './api.service';
import { CommonModule } from '@angular/common';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';

interface MediaAttachment {
  type: string;
  url: string;
  preview_url?: string;
  description?: string;
}

interface CachedPost {
  id: string;
  content: string;
  created_at: string;
  visibility: string;
  author_acct: string;
  is_reblog: boolean;
  is_reply: boolean;
  has_media: boolean;
  has_video: boolean;
  replies_count: number;
  media_attachments: MediaAttachment[];
}

interface CommentAccount {
  display_name: string;
  acct: string;
}

interface Comment {
  account: CommentAccount;
  content: string;
  created_at: string;
}

interface CommentsResponse {
  descendants: Comment[];
}

@Component({
  selector: 'app-public-post',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: 'public-post.component.html'
})
export class PublicPostComponent implements OnInit {
  post: CachedPost | null = null;
  comments: Comment[] = [];
  loadingComments = true;

  constructor(
    private route: ActivatedRoute,
    private api: ApiService,
    private sanitizer: DomSanitizer
  ) {}

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('id')!;

    // 1. Get Cached Post
    this.api.getPublicPost(id).subscribe(p => this.post = p);

    // 2. Get Live Comments
    this.api.getComments(id).subscribe({
      next: (c: CommentsResponse) => {
        this.comments = c.descendants || [];
        this.loadingComments = false;
      },
      error: () => this.loadingComments = false
    });
  }

  sanitizeHtml(html: string): SafeHtml {
    return this.sanitizer.sanitize(1, html) || '';
  }

  getMediaImages(post: CachedPost): MediaAttachment[] {
    console.log(post)
    return post.media_attachments?.filter(m => m.type === 'image') || [];
  }
}
