// web/src/app/content-hub-state.service.ts
import { Injectable } from '@angular/core';
import { BehaviorSubject } from 'rxjs';
import { ContentHubGroup } from './mastodon';

/**
 * Holds which Content Hub group is currently selected.
 * null = "my follows" mode (the original fixed content-type views).
 * non-null = hashtag group mode (all tab views filter by that group).
 */
@Injectable({ providedIn: 'root' })
export class ContentHubStateService {
  private activeGroupSubject = new BehaviorSubject<ContentHubGroup | null>(null);
  public readonly activeGroup$ = this.activeGroupSubject.asObservable();

  setActiveGroup(group: ContentHubGroup | null): void {
    this.activeGroupSubject.next(group);
  }

  getActiveGroup(): ContentHubGroup | null {
    return this.activeGroupSubject.value;
  }
}
