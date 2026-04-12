// src/app/content.component.ts
import { Component, OnInit, OnDestroy, inject } from '@angular/core';
import { RouterLink, RouterOutlet, Router } from '@angular/router';
import { CommonModule } from '@angular/common';
import { ApiService } from './api.service';
import { ContentHubStateService } from './content-hub-state.service';
import { ContentHubGroup } from './mastodon';
import { Subscription } from 'rxjs';

@Component({
  selector: 'app-content',
  standalone: true,
  imports: [RouterLink, RouterOutlet, CommonModule],
  template: `
    <div class="content-layout">
      <div class="content-nav">
        <h2 style="margin: 0 0 16px 0; color: #374151;">Content Hub</h2>

        <!-- "My Follows" section — always visible, clears group selection -->
        <div class="section-label">FROM MY FOLLOWS</div>
        <nav class="content-subnav" style="margin-bottom: 20px;">
          <a routerLink="images"   routerLinkActive="active" (click)="clearGroup()">📷 Images</a>
          <a routerLink="software" routerLinkActive="active" (click)="clearGroup()">💻 Software</a>
          <a routerLink="links"    routerLinkActive="active" (click)="clearGroup()">🔗 Links</a>
          <a routerLink="news"     routerLinkActive="active" (click)="clearGroup()">📰 News</a>
        </nav>

        <!-- Hashtag groups section -->
        <div class="section-label">HASHTAG GROUPS</div>

        @if (loading) {
          <div class="muted" style="font-size: 0.82rem; padding: 4px 0;">Loading...</div>
        }
        @if (!loading && groups.length === 0) {
          <div class="muted" style="font-size: 0.82rem; padding: 4px 0;">
            No groups yet. Add bundles in Admin.
          </div>
        }

        @for (group of groups; track group.id) {
          <div class="group-entry" [class.group-selected]="activeGroup?.id === group.id">
            <!-- Group header — clicking selects the group and navigates to text tab -->
            <button
              class="group-btn"
              [class.active]="activeGroup?.id === group.id"
              (click)="selectGroup(group)">
              <span class="group-name">{{ group.name }}</span>
              @if (group.source_type === 'server_follow') {
                <span class="source-badge follow">follow</span>
              } @else {
                <span class="source-badge bundle">bundle</span>
              }
            </button>

            <!-- Sub-tabs, shown only when this group is selected -->
            @if (activeGroup?.id === group.id) {
              <nav class="group-tabs">
                <a routerLink="images"   routerLinkActive="tab-active">📷 Images</a>
                <a routerLink="software" routerLinkActive="tab-active">💻 Software</a>
                <a routerLink="links"    routerLinkActive="tab-active">🔗 Links</a>
                <a routerLink="news"     routerLinkActive="tab-active">📰 News</a>
                <a routerLink="text"     routerLinkActive="tab-active">📝 Text</a>
                <a routerLink="jobs"     routerLinkActive="tab-active">💼 Jobs</a>
              </nav>
            }
          </div>
        }
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
      font-size: 0.68rem;
      font-weight: 700;
      letter-spacing: 0.07em;
      color: #9ca3af;
      margin-bottom: 6px;
      text-transform: uppercase;
    }

    .content-subnav {
      display: flex;
      flex-direction: column;
      gap: 3px;
    }

    .content-subnav a {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 8px 12px;
      border-radius: 6px;
      text-decoration: none;
      color: #374151;
      transition: all 0.2s;
      font-weight: 500;
      font-size: 0.88rem;
    }

    .content-subnav a:hover { background: #f3f4f6; color: #6366f1; }
    .content-subnav a.active { background: #6366f1; color: white; }

    /* Group entries */
    .group-entry {
      margin-bottom: 2px;
    }

    .group-btn {
      width: 100%;
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 8px 12px;
      border-radius: 6px;
      background: none;
      border: none;
      cursor: pointer;
      color: #374151;
      font-weight: 500;
      font-size: 0.88rem;
      text-align: left;
      transition: all 0.2s;
    }

    .group-btn:hover { background: #f3f4f6; color: #6366f1; }
    .group-btn.active { background: #6366f1; color: white; }
    .group-btn.active .source-badge {
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
      font-size: 0.62rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      padding: 2px 5px;
      border-radius: 3px;
    }

    .source-badge.bundle { background: #eef2ff; color: #4338ca; }
    .source-badge.follow { background: #f0fdf4; color: #166534; }

    /* Sub-tabs under selected group */
    .group-tabs {
      display: flex;
      flex-direction: column;
      gap: 2px;
      margin: 3px 0 6px 12px;
      border-left: 2px solid #e5e7eb;
      padding-left: 8px;
    }

    .group-tabs a {
      display: flex;
      align-items: center;
      padding: 5px 10px;
      border-radius: 5px;
      text-decoration: none;
      color: #6b7280;
      font-size: 0.83rem;
      font-weight: 500;
      transition: all 0.15s;
    }

    .group-tabs a:hover { background: #f3f4f6; color: #6366f1; }
    .group-tabs a.tab-active { background: #eef2ff; color: #4338ca; font-weight: 600; }

    .content-main { min-height: 400px; }

    @media (max-width: 768px) {
      .content-layout { grid-template-columns: 1fr; }
      .content-subnav { flex-direction: row; overflow-x: auto; flex-wrap: nowrap; }
      .group-tabs { flex-direction: row; flex-wrap: wrap; border-left: none; padding-left: 0; margin-left: 0; }
    }
  `]
})
export class ContentComponent implements OnInit, OnDestroy {
  private api = inject(ApiService);
  private router = inject(Router);
  private hubState = inject(ContentHubStateService);

  groups: ContentHubGroup[] = [];
  loading = true;
  activeGroup: ContentHubGroup | null = null;

  private subs: Subscription[] = [];

  ngOnInit(): void {
    this.subs.push(
      this.hubState.activeGroup$.subscribe((g) => (this.activeGroup = g)),
    );
    this.subs.push(
      this.api.identityId$.subscribe((identityId) => {
        if (identityId) this.loadGroups(identityId);
      }),
    );
  }

  ngOnDestroy(): void {
    this.subs.forEach((s) => s.unsubscribe());
  }

  selectGroup(group: ContentHubGroup): void {
    this.hubState.setActiveGroup(group);
    // Navigate to the text tab as the default entry point for a hashtag group
    this.router.navigate(['/content/text']);
  }

  clearGroup(): void {
    this.hubState.setActiveGroup(null);
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
