import { Component, OnInit } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { ApiService } from './api.service';
import { CommonModule } from '@angular/common';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';

// Interfaces for Mastodon API shape (returned by Context)
interface Account {
  id: string;
  acct: string;
  display_name: string;
  avatar: string;
  url: string;
}

interface Status {
  id: string;
  content: string;
  created_at: string;
  account: Account;
  in_reply_to_id: string | null;
  media_attachments: any[];
  replies_count: number;
  favourites_count: number;
  reblogs_count: number;
  visibility: string;
}

interface TreeNode {
  post: Status;
  children: TreeNode[];
}

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
  templateUrl: 'post.component.html',
  styles: [`
    .tree-line {
      position: absolute;
      left: 20px;
      top: 50px;
      bottom: 0;
      width: 2px;
      background: #e1e8ed;
      z-index: 0;
    }
    .post-wrapper {
      position: relative;
    }
  `]
})
export class PublicPostComponent implements OnInit {
  loading = true;
  ancestors: Status[] = [];
  target: Status | null = null;
  descendantTree: TreeNode[] = [];

  // The account of the blog we are currently viewing (for highlighting)
  blogUserAcct: string | null = null;

  constructor(
    private route: ActivatedRoute,
    private api: ApiService,
    private sanitizer: DomSanitizer,
  ) {}

  ngOnInit(): void {
    // Check if we are viewing a specific user's blog context
    this.route.queryParams.subscribe(params => {
      this.blogUserAcct = params['user'] || null;
    });

    this.route.paramMap.subscribe(params => {
      const id = params.get('id');
      if (id) this.loadPost(id);
    });
  }

  loadPost(id: string) {
    this.loading = true;
    this.api.getPostContext(id).subscribe({
      next: (data) => {
        this.ancestors = data.ancestors || [];
        this.target = data.target;
        this.descendantTree = this.buildTree(data.descendants || [], this.target!.id);
        this.loading = false;
      },
      error: (err) => {
        console.error(err);
        this.loading = false;
      }
    });
  }

  /**
   * Constructs a nested tree from the flat descendants list.
   */
  buildTree(flatPosts: Status[], targetId: string): TreeNode[] {
    const map = new Map<string, TreeNode>();

    // Initialize all nodes
    flatPosts.forEach(p => map.set(p.id, { post: p, children: [] }));

    const roots: TreeNode[] = [];

    flatPosts.forEach(p => {
      const node = map.get(p.id)!;
      // If it replies to the target, it's a root of our descendants tree
      if (p.in_reply_to_id === targetId) {
        roots.push(node);
      }
      // If it replies to another descendant, add it to that descendant's children
      else if (p.in_reply_to_id && map.has(p.in_reply_to_id)) {
        map.get(p.in_reply_to_id)!.children.push(node);
      }
      // Note: Orphans (replies to missing posts) are excluded from the tree
      // unless we explicitly handle them, but context usually provides a connected graph.
    });

    // Helper to sort nodes chronologically
    const sortNodes = (nodes: TreeNode[]) => {
      nodes.sort((a, b) => a.post.created_at.localeCompare(b.post.created_at));
      nodes.forEach(n => sortNodes(n.children));
    };

    sortNodes(roots);
    return roots;
  }

  isActiveUser(post: Status): boolean {
    if (!this.blogUserAcct) return false;
    return post.account.acct === this.blogUserAcct;
  }

  // HTML Processing (Embeds & Security)
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
      },
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
      },
    );

    // 2. Open links in new tab
    processed = processed.replace(/<a /g, '<a target="_blank" rel="noopener noreferrer" ');

    // 3. Bypass security to allow the iframes and links to render
    return this.sanitizer.bypassSecurityTrustHtml(processed);
  }

  getMediaImages(post: Status): any[] {
    return post.media_attachments?.filter((m) => m.type === 'image') || [];
  }
}
