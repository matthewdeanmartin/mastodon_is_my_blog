import {
  Component,
  OnInit,
  inject,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
} from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { ApiService } from './api.service';
import { CommonModule } from '@angular/common';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { LinkPreviewComponent } from './link.component';
import { LinkPreviewService } from './link.service';
import { MastodonMediaAttachment, MastodonStatus } from './mastodon';

interface TreeNode {
  post: MastodonStatus;
  children: TreeNode[];
}

/*
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
*/

/*
interface CommentsResponse {
  descendants: Comment[];
}
*/

@Component({
  selector: 'app-public-post',
  standalone: true,
  imports: [CommonModule, LinkPreviewComponent, RouterLink],
  templateUrl: 'post.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
  styles: [
    `
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
    `,
  ],
})
export class PublicPostComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private api = inject(ApiService);
  private sanitizer = inject(DomSanitizer);
  private linkPreviewService = inject(LinkPreviewService);
  private cdr = inject(ChangeDetectorRef);

  private targetId: string | null = null;
  loading = true;
  ancestors: MastodonStatus[] = [];
  target: MastodonStatus | null = null;
  descendantTree: TreeNode[] = [];

  // The account of the blog we are currently viewing (for highlighting)
  blogUserAcct: string | null = null;
  currentFilter = 'all';

  treeNodeContext(node: TreeNode): { node: TreeNode } {
    return { node };
  }

  ngOnInit(): void {
    // Check if we are viewing a specific user's blog context
    this.route.queryParams.subscribe((params) => {
      this.blogUserAcct = params['user'] || null;
      this.currentFilter = params['filter'] || 'storms';
    });

    this.route.paramMap.subscribe((params) => {
      const id = params.get('id');
      if (!id) return;
      this.targetId = id;
      this.loadPost(id);
    });
  }

  loadPost(id: string): void {
    this.loading = true;
    // UPDATED: Pass the current identity ID to context fetch
    const identityId = this.api.getCurrentIdentityId();

    this.api.getPostContext(id, identityId || undefined).subscribe({
      next: (data) => {
        this.ancestors = data.ancestors || [];
        const target = data.target ?? null;
        this.target = target;
        this.descendantTree = target ? this.buildTree(data.descendants || [], target.id) : [];

        this.loading = false;
        this.cdr.markForCheck();

        // Mark as read when viewing the full post
        this.markAsSeen(id);
      },
      error: (err: unknown) => {
        console.error(err);
        this.loading = false;
      },
    });
  }

  private markAsSeen(postId: string): void {
    this.api.markPostSeen(postId).subscribe({
      error: (err: unknown) => {
        console.error('Failed to mark post as seen', err);
      },
    });
  }

  replyToPost(statusId: string): void {
    this.router.navigate(['/write/reply', statusId]);
  }

  /**
   * Constructs a nested tree from the flat descendants list.
   */
  buildTree(flatPosts: MastodonStatus[], targetId: string): TreeNode[] {
    const map = new Map<string, TreeNode>();

    // Initialize all nodes
    flatPosts.forEach((p) => map.set(p.id, { post: p, children: [] }));

    const roots: TreeNode[] = [];

    flatPosts.forEach((p) => {
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
      nodes.forEach((n) => sortNodes(n.children));
    };

    sortNodes(roots);
    return roots;
  }

  isActiveUser(post: MastodonStatus): boolean {
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

  getMediaImages(post: MastodonStatus): MastodonMediaAttachment[] {
    return post.media_attachments?.filter((m) => m.type === 'image') || [];
  }

  getMediaVideos(post: MastodonStatus): MastodonMediaAttachment[] {
    return post.media_attachments?.filter((m) => m.type === 'video' || m.type === 'gifv') || [];
  }

  getOriginalPostUrl(post: MastodonStatus): string | null {
    // Always route through the active identity's home instance so the user
    // can reply/boost/fav while signed in. If the active base URL isn't
    // known, refuse to fabricate one — the template hides the link.
    const acct = post.account.acct;
    if (!acct) return null;
    const base = this.api.getIdentityBaseUrl()?.replace(/\/$/, '');
    if (!base) return null;
    const parts = acct.split('@');
    const username = parts[0];
    const remoteInstance = parts[1];
    if (remoteInstance) {
      return `${base}/@${username}@${remoteInstance}/${post.id}`;
    }
    return `${base}/@${username}/${post.id}`;
  }

  /**
   * Extract URLs from post content for link previews
   */
  getPostUrls(post: MastodonStatus): string[] {
    const content = post.content || '';
    return this.linkPreviewService.extractUrls(content);
  }
}
