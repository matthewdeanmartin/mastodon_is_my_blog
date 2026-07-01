import { TestBed, ComponentFixture } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { BehaviorSubject, Observable, of } from 'rxjs';
import { ApiService } from './api.service';
import { ForumComponent } from './forum.component';
import { ForumThread, ForumThreadsResponse } from './mastodon';

function makeThread(rootId: string): ForumThread {
  return {
    root_id: rootId,
    root_post: {
      id: rootId,
      author_acct: 'alice@example.com',
      author_display_name: 'Alice',
      author_avatar: '',
      author_instance: 'example.com',
      content: `<p>${rootId}</p>`,
      created_at: '2026-01-01T00:00:00Z',
      has_question: false,
      tags: [],
    },
    reply_count: 0,
    friend_reply_count: 0,
    friend_repliers: [],
    latest_reply_at: null,
    root_is_partial: false,
  };
}

interface ForumCall {
  identityId: number;
  params: {
    top_filter?: string;
    hashtag?: string[];
    uncommon_word?: string[];
    root_instance?: string[];
    before?: string | null;
    include_content_hub?: boolean;
  };
}

class MockApiService {
  identityId$ = new BehaviorSubject<number | null>(null);
  calls: ForumCall[] = [];
  response: ForumThreadsResponse = {
    items: [makeThread('t1')],
    next_cursor: null,
    facets: { hashtags: [], uncommon_words: [], root_instances: [] },
  };

  getForumThreads(identityId: number, params: ForumCall['params']): Observable<ForumThreadsResponse> {
    this.calls.push({ identityId, params });
    return of(this.response);
  }

  getCurrentIdentityId(): number | null {
    return this.identityId$.value;
  }
}

describe('ForumComponent', () => {
  let fixture: ComponentFixture<ForumComponent>;
  let component: ForumComponent;
  let api: MockApiService;

  beforeEach(async () => {
    api = new MockApiService();

    await TestBed.configureTestingModule({
      imports: [ForumComponent],
      providers: [provideRouter([]), { provide: ApiService, useValue: api }],
    }).compileComponents();

    fixture = TestBed.createComponent(ForumComponent);
    component = fixture.componentInstance;
  });

  it('loads threads once the identity arrives (late async restore)', () => {
    fixture.detectChanges();
    expect(component.loading).toBe(false);
    expect(api.calls.length).toBe(0);

    api.identityId$.next(42);

    expect(api.calls.length).toBe(1);
    expect(api.calls[0].identityId).toBe(42);
    expect(component.threads.map((t) => t.root_id)).toEqual(['t1']);
  });

  it('reloads when the active identity switches', () => {
    api.identityId$.next(42);
    fixture.detectChanges();
    expect(api.calls.length).toBe(1);

    api.identityId$.next(43);

    expect(api.calls.length).toBe(2);
    expect(api.calls[1].identityId).toBe(43);
  });

  it('changing the top filter clears active facets and reloads', () => {
    api.identityId$.next(42);
    fixture.detectChanges();
    component.toggleFacet('hashtags', 'python');
    expect(component.activeFacets.hashtags.has('python')).toBe(true);

    component.setFilter('popular');

    expect(component.activeFacets.hashtags.size).toBe(0);
    const last = api.calls[api.calls.length - 1];
    expect(last.params.top_filter).toBe('popular');
    expect(last.params.hashtag).toEqual([]);
  });

  it('toggling a facet on and off round-trips the request params', () => {
    api.identityId$.next(42);
    fixture.detectChanges();

    component.toggleFacet('root_instances', 'fosstodon.org');
    let last = api.calls[api.calls.length - 1];
    expect(last.params.root_instance).toEqual(['fosstodon.org']);

    component.toggleFacet('root_instances', 'fosstodon.org');
    last = api.calls[api.calls.length - 1];
    expect(last.params.root_instance).toEqual([]);
  });

  it('load more appends threads and passes the cursor', () => {
    api.response = { ...api.response, next_cursor: 'cursor-1' };
    api.identityId$.next(42);
    fixture.detectChanges();

    api.response = {
      items: [makeThread('t2')],
      next_cursor: null,
      facets: { hashtags: [], uncommon_words: [], root_instances: [] },
    };
    component.loadMore();

    const last = api.calls[api.calls.length - 1];
    expect(last.params.before).toBe('cursor-1');
    expect(component.threads.map((t) => t.root_id)).toEqual(['t1', 't2']);
    expect(component.nextCursor).toBeNull();
  });

  it('content hub toggle resets the list and sends the flag', () => {
    api.identityId$.next(42);
    fixture.detectChanges();

    component.toggleContentHub();

    const last = api.calls[api.calls.length - 1];
    expect(last.params.include_content_hub).toBe(true);
  });
});
