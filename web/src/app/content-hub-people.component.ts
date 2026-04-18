// src/app/content-hub-people.component.ts
import { Component, OnInit, OnDestroy, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { Subject, combineLatest } from 'rxjs';
import { takeUntil, switchMap } from 'rxjs/operators';
import { ApiService } from './api.service';
import { ContentHubStateService } from './content-hub-state.service';
import { GroupPerson } from './mastodon';

@Component({
  selector: 'app-content-hub-people',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    @if (!activeGroupId) {
      <div class="no-group-prompt">
        <p>Select a hashtag group in the sidebar to see who's posting in it.</p>
      </div>
    } @else {
      <div class="people-panel">
        <div class="people-toolbar">
          <label class="toggle-label">
            <input type="checkbox" [(ngModel)]="excludeFollowed" (change)="reload()" />
            Hide people I already follow
          </label>
          <select [(ngModel)]="sortOrder" (change)="reload()">
            <option value="posts">Sort: Most posts</option>
            <option value="recent">Sort: Most recent</option>
            <option value="engagement">Sort: Most engagement</option>
          </select>
        </div>

        @if (loading) {
          <div class="loading">Loading…</div>
        }
        @if (error) {
          <div class="error-msg">{{ error }}</div>
        }

        <div class="people-list">
          @for (person of people; track person.acct) {
            <div class="person-row">
              <img class="avatar" [src]="person.avatar || 'assets/default-avatar.png'" [alt]="person.display_name" />
              <div class="person-info">
                <span class="display-name">{{ person.display_name }}</span>
                <span class="acct">&#64;{{ person.acct }}</span>
                <span class="stats-line">
                  {{ person.post_count_in_group }} posts in group
                  @if (person.total_engagement_in_group > 0) {
                    · {{ person.total_engagement_in_group }} engagements
                  }
                </span>
              </div>
              <div class="person-actions">
                <button class="filter-btn" (click)="viewDossier(person.acct)">View Dossier</button>
                @if (!person.is_following) {
                  <button class="filter-btn follow-btn" (click)="follow(person)">Follow</button>
                }
              </div>
            </div>
          }
          @if (!loading && people.length === 0) {
            <p class="empty">No people found for this group yet.</p>
          }
        </div>
      </div>
    }
  `,
  styles: [`
    .no-group-prompt {
      padding: 32px;
      text-align: center;
      color: #9ca3af;
    }
    .people-panel { padding: 0; }
    .people-toolbar {
      display: flex;
      align-items: center;
      gap: 16px;
      padding: 12px 0;
      margin-bottom: 12px;
      border-bottom: 1px solid #e1e8ed;
    }
    .toggle-label {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 0.85rem;
      color: #374151;
      cursor: pointer;
    }
    select {
      font-size: 0.82rem;
      border: 1px solid #d1d5db;
      border-radius: 6px;
      padding: 4px 8px;
      background: white;
    }
    .loading, .error-msg, .empty {
      padding: 16px;
      text-align: center;
      color: #9ca3af;
      font-size: 0.85rem;
    }
    .error-msg { color: #dc2626; }
    .people-list { display: flex; flex-direction: column; gap: 10px; }
    .person-row {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 10px;
      background: white;
      border: 1px solid #e1e8ed;
      border-radius: 8px;
    }
    .avatar {
      width: 44px; height: 44px; border-radius: 8px;
      object-fit: cover; flex-shrink: 0;
    }
    .person-info { flex: 1; display: flex; flex-direction: column; min-width: 0; }
    .display-name { font-weight: 600; font-size: 0.88rem; color: #1f2937; }
    .acct { font-size: 0.78rem; color: #6b7280; }
    .stats-line { font-size: 0.75rem; color: #9ca3af; margin-top: 2px; }
    .person-actions { display: flex; gap: 6px; flex-shrink: 0; }
    .filter-btn {
      padding: 5px 12px;
      font-size: 0.8rem;
      border: 1px solid #d1d5db;
      border-radius: 6px;
      background: white;
      cursor: pointer;
      color: #374151;
    }
    .filter-btn:hover { background: #f3f4f6; }
    .follow-btn { border-color: #6366f1; color: #6366f1; }
    .follow-btn:hover { background: #eef2ff; }
  `],
})
export class ContentHubPeopleComponent implements OnInit, OnDestroy {
  private api = inject(ApiService);
  private hubState = inject(ContentHubStateService);
  private router = inject(Router);
  private destroy$ = new Subject<void>();

  people: GroupPerson[] = [];
  loading = false;
  error: string | null = null;
  excludeFollowed = false;
  sortOrder: 'posts' | 'recent' | 'engagement' = 'posts';
  activeGroupId: number | null = null;

  ngOnInit(): void {
    combineLatest([this.api.identityId$, this.hubState.activeGroup$])
      .pipe(takeUntil(this.destroy$))
      .subscribe(([identityId, group]) => {
        this.activeGroupId = group?.id ?? null;
        if (identityId && group) {
          this.loadPeople(group.id, identityId);
        } else {
          this.people = [];
        }
      });
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  reload(): void {
    const id = this.api.getCurrentIdentityId();
    if (id && this.activeGroupId) {
      this.loadPeople(this.activeGroupId, id);
    }
  }

  loadPeople(groupId: number, identityId: number): void {
    this.loading = true;
    this.error = null;
    this.api
      .getContentHubGroupPeople(groupId, identityId, {
        sort: this.sortOrder,
        excludeFollowed: this.excludeFollowed,
      })
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (people) => {
          this.people = people;
          this.loading = false;
        },
        error: (e: unknown) => {
          this.error = 'Failed to load people.';
          this.loading = false;
          console.error(e);
        },
      });
  }

  viewDossier(acct: string): void {
    this.router.navigate(['/peeps/dossier', acct]);
  }

  follow(person: GroupPerson): void {
    const id = this.api.getCurrentIdentityId();
    if (!id) return;
    this.api.followAccount(person.acct, id).subscribe({
      next: () => {
        person.is_following = true;
      },
      error: (e: unknown) => console.error('Follow failed', e),
    });
  }
}
