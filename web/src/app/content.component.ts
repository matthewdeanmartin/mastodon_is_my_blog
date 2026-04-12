// src/app/content.component.ts
import { Component, OnInit, inject } from '@angular/core';
import { RouterLink, RouterOutlet } from '@angular/router';
import { CommonModule } from '@angular/common';
import { ApiService } from './api.service';
import { ContentHubGroup } from './mastodon';

@Component({
  selector: 'app-content',
  standalone: true,
  imports: [RouterLink, RouterOutlet, CommonModule],
  template: `
    <div class="content-layout">
      <div class="content-nav">
        <h2 style="margin: 0 0 16px 0; color: #374151;">Content Hub</h2>

        <!-- Fixed content-type filters: cached posts from people you follow -->
        <div class="section-label">FROM YOUR FOLLOWS</div>
        <nav class="content-subnav" style="margin-bottom: 20px;">
          <a routerLink="images" routerLinkActive="active">📷 Images</a>
          <a routerLink="software" routerLinkActive="active">💻 Software</a>
          <a routerLink="links" routerLinkActive="active">🔗 Links</a>
          <a routerLink="news" routerLinkActive="active">📰 News</a>
        </nav>

        <!-- Dynamic hashtag groups -->
        <div class="section-label">HASHTAG GROUPS</div>
        @if (loading) {
          <div class="muted" style="font-size: 0.82rem; padding: 4px 0;">Loading...</div>
        }
        @if (!loading && groups.length === 0) {
          <div class="muted" style="font-size: 0.82rem; padding: 4px 0;">
            No groups yet. Add bundles in Admin.
          </div>
        }
        <nav class="content-subnav">
          @for (group of groups; track group.id) {
            <a [routerLink]="['group', group.id]" routerLinkActive="active">
              <span class="group-name">{{ group.name }}</span>
              @if (group.source_type === 'server_follow') {
                <span class="source-badge follow">follow</span>
              } @else {
                <span class="source-badge bundle">bundle</span>
              }
            </a>
          }
        </nav>
      </div>

      <div class="content-main">
        <router-outlet></router-outlet>
      </div>
    </div>
  `,
  styles: [`
    .content-layout {
      display: grid;
      grid-template-columns: 220px 1fr;
      gap: 20px;
      min-height: 60vh;
    }

    .content-nav {
      background: white;
      padding: 20px;
      border-radius: 8px;
      border: 1px solid #e1e8ed;
      height: fit-content;
    }

    .section-label {
      font-size: 0.7rem;
      font-weight: 700;
      letter-spacing: 0.06em;
      color: #9ca3af;
      margin-bottom: 6px;
      text-transform: uppercase;
    }

    .content-subnav {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }

    .content-subnav a {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 9px 12px;
      border-radius: 6px;
      text-decoration: none;
      color: #374151;
      transition: all 0.2s;
      font-weight: 500;
      font-size: 0.9rem;
    }

    .content-subnav a:hover {
      background: #f3f4f6;
      color: #6366f1;
    }

    .content-subnav a.active {
      background: #6366f1;
      color: white;
    }

    .content-subnav a.active .source-badge {
      background: rgba(255,255,255,0.25);
      color: white;
    }

    .group-name {
      flex: 1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .source-badge {
      flex-shrink: 0;
      font-size: 0.65rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      padding: 2px 5px;
      border-radius: 3px;
    }

    .source-badge.bundle {
      background: #eef2ff;
      color: #4338ca;
    }

    .source-badge.follow {
      background: #f0fdf4;
      color: #166534;
    }

    .content-main {
      min-height: 400px;
    }

    @media (max-width: 768px) {
      .content-layout {
        grid-template-columns: 1fr;
      }

      .content-subnav {
        flex-direction: row;
        overflow-x: auto;
        flex-wrap: nowrap;
      }
    }
  `]
})
export class ContentComponent implements OnInit {
  private api = inject(ApiService);

  groups: ContentHubGroup[] = [];
  loading = true;

  ngOnInit(): void {
    this.api.identityId$.subscribe((identityId) => {
      if (identityId) {
        this.loadGroups(identityId);
      }
    });
  }

  private loadGroups(identityId: number): void {
    this.loading = true;
    this.api.getContentHubGroups(identityId).subscribe({
      next: (groups) => {
        this.groups = groups;
        this.loading = false;
      },
      error: () => {
        this.groups = [];
        this.loading = false;
      },
    });
  }
}
