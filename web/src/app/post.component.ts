import { Component, OnInit, inject, ChangeDetectionStrategy, ChangeDetectorRef } from '@angular/core';
import {ActivatedRoute, Router} from '@angular/router';
import {ApiService} from './api.service';
import {CommonModule} from '@angular/common';
import {DomSanitizer, SafeHtml} from '@angular/platform-browser';
import {LinkPreviewComponent} from './link.component';
import {LinkPreviewService} from './link.service';
import {MastodonMediaAttachment, MastodonStatus} from './mastodon';

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
  imports: [CommonModule, LinkPreviewComponent],
  templateUrl: 'post.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
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
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private api = inject(ApiService);
  private sanitizer = inject(DomSanitizer);
  private linkPreviewService = inject(LinkPreviewService);
  private cdr = inject(ChangeDetectorRef);

  private feedReady = false;
  private targetId: string | null = null;
  loading = true;
  loadingNext = false;
  ancestors: MastodonStatus[] = [];
  target: MastodonStatus | null = null;
  descendantTree: TreeNode[] = [];

  // The account of the blog we are currently viewing (for highlighting)
  blogUserAcct: string | null = null;
  currentFilter = 'all';

  // For next post functionality
  private allPosts: { id: string; created_at: string }[] = [];
  private currentPostIndex = -1;

  ngOnInit(): void {
    // Check if we are viewing a specific user's blog context
    this.route.queryParams.subscribe(params => {
      this.blogUserAcct = params['user'] || null;
      this.currentFilter = params['filter'] || 'storms';
    });

    this.route.paramMap.subscribe(params => {
      const id = params.get('id');
      if (!id) return;
      this.targetId = id;

      // Load the post details
      this.loadPost(id);

      // Load the surrounding feed (for Next/Prev navigation)
      this.loadFeedForNavigation();
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

        // Find current post index in the feed if feed is already loaded
        this.recomputeIndex();
        this.loading = false;
        this.cdr.markForCheck();

        // Mark as read when viewing the full post
        this.markAsSeen(id);
      },
      error: (err: unknown) => {
        console.error(err);
        this.loading = false;
      }
    });
  }
  
  private markAsSeen(postId: string): void {
    this.api.markPostSeen(postId).subscribe({
      error: (err: unknown) => {
        console.error('Failed to mark post as seen', err);
      }
    });
  }

  loadFeedForNavigation(): void {
    this.feedReady = false;
    this.allPosts = [];

    // NEW: We must have an identity context to know which feed to load.
    const identityId = this.api.getCurrentIdentityId();

    if (!identityId) {
        console.warn('No identity context available for navigation');
        return;
    }

    const isStorms = this.currentFilter === 'storms' || this.currentFilter === 'all';

    const onDone = () => {
      this.feedReady = true;
      this.recomputeIndex();
      this.cdr.markForCheck();
    };

    if (isStorms) {
      this.api.getStorms(identityId, this.blogUserAcct || undefined).subscribe({
        next: page => {
          this.allPosts = page.items.map(storm => ({id: storm.root.id, created_at: storm.root.created_at}));
          onDone();
        },
        error: () => onDone(),
      });
    } else {
      this.api.getPublicPosts(identityId, this.currentFilter, this.blogUserAcct || undefined).subscribe({
        next: page => {
          this.allPosts = page.items.map(p => ({id: p.id, created_at: p.created_at}));
          onDone();
        },
        error: () => onDone(),
      });
    }
  }


  private recomputeIndex(): void {
    if (!this.targetId || this.allPosts.length === 0) {
      this.currentPostIndex = -1;
      return;
    }
    this.currentPostIndex = this.allPosts.findIndex(p => p.id === this.targetId);
  }

  nextPost(): void {
    if (this.allPosts.length === 0 || this.loadingNext) return;

    // Find next index (wrap around to 0 if at end)
    const nextIndex = (this.currentPostIndex + 1) % this.allPosts.length;
    const nextPost = this.allPosts[nextIndex];

    if (!nextPost) return;

    this.loadingNext = true;

    // Navigate to next post with same query params
    this.router.navigate(['/p', nextPost.id], {
      queryParamsHandling: 'preserve'
    }).then(() => {
      this.loadingNext = false;
      window.scrollTo({top: 0, behavior: 'smooth'});
    });
  }

  goBack(): void {
    // Navigate back to feed with preserved query params
    this.router.navigate(['/'], {
      queryParamsHandling: 'preserve'
    });
  }

  /**
   * Constructs a nested tree from the flat descendants list.
   */
  buildTree(flatPosts: MastodonStatus[], targetId: string): TreeNode[] {
    const map = new Map<string, TreeNode>();

    // Initialize all nodes
    flatPosts.forEach(p => map.set(p.id, {post: p, children: []}));

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

  getOriginalPostUrl(post: MastodonStatus): string {
    const acct = post.account.acct;
    if (!acct) return '#';

    const parts = acct.split('@');
    const username = parts[0];
    const instance = parts[1] || 'mastodon.social';
    const canonicalUrl = `https://${instance}/@${username}/${post.id}`;

    const localBaseUrl = this.api.getIdentityBaseUrl();
    if (localBaseUrl && parts[1]) {
      return `${localBaseUrl.replace(/\/$/, '')}/@${username}@${parts[1]}/${post.id}`;
    }
    return canonicalUrl;
  }

  /**
   * Extract URLs from post content for link previews
   */
  getPostUrls(post: MastodonStatus): string[] {
    const content = post.content || '';
    return this.linkPreviewService.extractUrls(content);
  }
}
