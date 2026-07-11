import { TestBed, ComponentFixture } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { BehaviorSubject, Observable, of } from 'rxjs';
import { ApiService } from './api.service';
import { ContentHubStateService } from './content-hub-state.service';
import { ContentHubTextComponent } from './content-hub-tabs.component';
import { ContentHubGroup, ContentHubGroupPostsResponse, ContentHubPost } from './mastodon';

function makeGroup(id: number, name: string): ContentHubGroup {
  return {
    id,
    name,
    slug: name.replace('#', ''),
    source_type: 'client_bundle',
    is_read_only: false,
    last_fetched_at: null,
    terms: [],
  };
}

function makeHubPost(
  id: string,
  createdAt: string,
  counts: Partial<{ replies: number; reblogs: number; likes: number }> = {},
): ContentHubPost {
  return {
    id,
    content: `<p>${id}</p>`,
    author_acct: `${id}@example.com`,
    author_avatar: '',
    author_display_name: id,
    created_at: createdAt,
    media_attachments: [],
    tags: [],
    counts: { replies: 0, reblogs: 0, likes: 0, ...counts },
    has_video: false,
    has_link: false,
    is_reblog: false,
    is_reply: false,
  };
}

interface RecordedCall {
  groupId: number;
  identityId: number;
  tab: string;
  before: string | null | undefined;
  limit: number;
  shuffle: boolean;
}

class MockApiService {
  identityId$ = new BehaviorSubject<number | null>(42);
  calls: RecordedCall[] = [];
  response: ContentHubGroupPostsResponse = {
    items: [],
    next_cursor: null,
    stale: false,
    group: { id: 7, name: '#dogs', last_fetched_at: null },
  };
  refreshCount = 0;

  getContentHubGroupPosts(
    groupId: number,
    identityId: number,
    tab = 'text',
    before?: string | null,
    limit = 30,
    shuffle = false,
  ): Observable<ContentHubGroupPostsResponse> {
    this.calls.push({ groupId, identityId, tab, before, limit, shuffle });
    return of(this.response);
  }

  refreshContentHubGroup(): Observable<unknown> {
    this.refreshCount++;
    return of({});
  }

  getCurrentIdentityId(): number | null {
    return this.identityId$.value;
  }
}

describe('ContentHubTextComponent', () => {
  let fixture: ComponentFixture<ContentHubTextComponent>;
  let component: ContentHubTextComponent;
  let api: MockApiService;
  let hubState: ContentHubStateService;

  beforeEach(async () => {
    api = new MockApiService();
    hubState = new ContentHubStateService();

    await TestBed.configureTestingModule({
      imports: [ContentHubTextComponent],
      providers: [
        provideRouter([]),
        { provide: ApiService, useValue: api },
        { provide: ContentHubStateService, useValue: hubState },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(ContentHubTextComponent);
    component = fixture.componentInstance;
  });

  it('shows nothing and skips the API when no group is selected', () => {
    fixture.detectChanges();

    expect(component.posts).toEqual([]);
    expect(api.calls.length).toBe(0);
  });

  it('loads posts when a group becomes active', () => {
    hubState.setActiveGroup(makeGroup(7, '#dogs'));
    api.response = {
      ...api.response,
      items: [makeHubPost('a', '2026-01-02T00:00:00Z'), makeHubPost('b', '2026-01-01T00:00:00Z')],
    };

    fixture.detectChanges();

    expect(api.calls.length).toBe(1);
    expect(api.calls[0]).toMatchObject({ groupId: 7, identityId: 42, tab: 'text' });
    expect(component.posts.map((p) => p.id)).toEqual(['a', 'b']);
  });

  it('re-sorts posts by engagement when the Popular filter button is clicked', () => {
    hubState.setActiveGroup(makeGroup(7, '#dogs'));
    api.response = {
      ...api.response,
      items: [
        // Server returns newest-first; "hot" is older but far more engaged.
        makeHubPost('fresh', '2026-01-03T00:00:00Z', { likes: 1 }),
        makeHubPost('hot', '2026-01-01T00:00:00Z', { likes: 10, replies: 5, reblogs: 3 }),
      ],
    };
    fixture.detectChanges();
    expect(component.posts.map((p) => p.id)).toEqual(['fresh', 'hot']);

    const popularBtn = Array.from(
      fixture.nativeElement.querySelectorAll(
        '.filter-buttons button',
      ) as NodeListOf<HTMLButtonElement>,
    ).find((b) => b.textContent?.trim() === 'Popular');
    expect(popularBtn).toBeDefined();
    popularBtn!.click();
    fixture.detectChanges();

    expect(component.currentFilter).toBe('popular');
    expect(component.posts.map((p) => p.id)).toEqual(['hot', 'fresh']);
    expect(popularBtn!.classList.contains('active')).toBe(true);
  });

  it('only offers filters the group-posts endpoint can honor (no Following/Everyone)', () => {
    const values = component.filters.map((f) => f.value);
    expect(values).toEqual(['recent', 'popular']);
  });

  it('passes shuffle=true to the API and resets pagination when Shuffle is clicked', () => {
    hubState.setActiveGroup(makeGroup(7, '#dogs'));
    api.response = { ...api.response, next_cursor: 'cursor-1' };
    fixture.detectChanges();

    component.nextPage();
    expect(component.cursorStack).toEqual(['cursor-1']);

    component.shuffle();

    const last = api.calls[api.calls.length - 1];
    expect(last.shuffle).toBe(true);
    expect(last.before).toBeNull();
    expect(component.cursorStack).toEqual([]);
  });

  it('walks cursors forward and back with Next/Prev', () => {
    hubState.setActiveGroup(makeGroup(7, '#dogs'));
    api.response = { ...api.response, next_cursor: 'c1' };
    fixture.detectChanges();

    api.response = { ...api.response, next_cursor: 'c2' };
    component.nextPage();
    expect(api.calls[api.calls.length - 1].before).toBe('c1');

    api.response = { ...api.response, next_cursor: 'c3' };
    component.nextPage();
    expect(api.calls[api.calls.length - 1].before).toBe('c2');
    expect(component.cursorStack).toEqual(['c1', 'c2']);

    component.prevPage();
    expect(api.calls[api.calls.length - 1].before).toBe('c1');
    expect(component.cursorStack).toEqual(['c1']);

    component.prevPage();
    expect(api.calls[api.calls.length - 1].before).toBeNull();
    expect(component.cursorStack).toEqual([]);
  });

  it('changing filter resets pagination state', () => {
    hubState.setActiveGroup(makeGroup(7, '#dogs'));
    api.response = { ...api.response, next_cursor: 'c1' };
    fixture.detectChanges();
    component.nextPage();
    expect(component.cursorStack.length).toBe(1);

    component.setFilter('popular');

    expect(component.cursorStack).toEqual([]);
    const last = api.calls[api.calls.length - 1];
    expect(last.before).toBeNull();
  });

  it('Fetch New refreshes the group then reloads from page one', () => {
    hubState.setActiveGroup(makeGroup(7, '#dogs'));
    fixture.detectChanges();
    const callsBefore = api.calls.length;

    component.fetchNew();

    expect(api.refreshCount).toBe(1);
    expect(api.calls.length).toBe(callsBefore + 1);
    expect(api.calls[api.calls.length - 1].before).toBeNull();
    expect(component.refreshing).toBe(false);
  });
});
