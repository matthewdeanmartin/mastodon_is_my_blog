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
    this.api.getPublicPost(id).subscribe(p => {
      this.post = p;
    });

    // 2. Get Live Comments
    this.api.getComments(id).subscribe({
      next: (c: CommentsResponse) => {
        this.comments = c.descendants || [];
        this.loadingComments = false;
      },
      error: () => this.loadingComments = false
    });
  }

  // Process HTML to trust links and embed videos
  processContent(html: string): SafeHtml {
    if (!html) return '';

    let processed = html;

    // 1. Replace YouTube links with Embeds
    // Pattern 1: Links with youtube.com/watch?v=
    processed = processed.replace(
      /<a[^>]+href="(https?:\/\/(?:www\.)?youtube\.com\/watch\?v=([\w-]{11})(?:[^"]*)?)"[^>]*>([^<]*)<\/a>/gi,
      (match, url, videoId, linkText) => {
        return `
          <div class="video-embed-wrapper">
            <iframe
              src="https://www.youtube.com/embed/${videoId}"
              frameborder="0"
              allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
              allowfullscreen>
            </iframe>
          </div>
          <p><a href="${url}" target="_blank" rel="noopener noreferrer">${linkText || url}</a></p>`;
      }
    );

    // Pattern 2: Links with youtu.be/
    processed = processed.replace(
      /<a[^>]+href="(https?:\/\/(?:www\.)?youtu\.be\/([\w-]{11})(?:[^"]*)?)"[^>]*>([^<]*)<\/a>/gi,
      (match, url, videoId, linkText) => {
        return `
          <div class="video-embed-wrapper">
            <iframe
              src="https://www.youtube.com/embed/${videoId}"
              frameborder="0"
              allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
              allowfullscreen>
            </iframe>
          </div>
          <p><a href="${url}" target="_blank" rel="noopener noreferrer">${linkText || url}</a></p>`;
      }
    );

    // 2. Ensure all other links open in new tab and are styled properly
    processed = processed.replace(
      /<a /g,
      '<a target="_blank" rel="noopener noreferrer" '
    );

    // 3. Bypass security to allow the iframes and links to render
    return this.sanitizer.bypassSecurityTrustHtml(processed);
  }

  getMediaImages(post: CachedPost): MediaAttachment[] {
    return post.media_attachments?.filter(m => m.type === 'image') || [];
  }
}
