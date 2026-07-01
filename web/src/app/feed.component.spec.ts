import { TestBed, ComponentFixture } from '@angular/core/testing';
import { ActivatedRoute, provideRouter } from '@angular/router';
import { BehaviorSubject, Observable, of, Subject } from 'rxjs';
import { ApiService, FeedPage, Storm } from './api.service';
import { PublicFeedComponent } from './feed.component';
import { RawContentPost } from './content-feed.utils';

function makePost(id: string, createdAt = '2026-01-01T00:00:00Z'): RawContentPost {
  return {
    id,
    content: `<p>${id}</p>`,
    created_at: createdAt,
    author_acct: `${id}@example.com`,
  };
}

class MockApiService {
  identityId$ = new BehaviorSubject<number | null>(42);
  refreshNeeded$ = new Subject<void>();

  stormsPages: FeedPage<Storm>[] = [];
  shortsPages: FeedPage<RawContentPost>[] = [];
  postsPages: FeedPage<RawContentPost>[] = [];
  seenResponses: string[][] = [];
  seenQueries: string[][] = [];
  markedSeen: string[][] = [];

  getIdentityBaseUrl(): string | null {
    return 'https://home.social';
  }

  getStorms(): Observable<FeedPage<Storm>> {
    return of(this.stormsPages.shift() ?? { items: [], next_cursor: null });
  }

  getShorts(): Observable<FeedPage<RawContentPost>> {
    return of(this.shortsPages.shift() ?? { items: [], next_cursor: null });
  }

  getPublicPosts(): Observable<FeedPage<RawContentPost>> {
    return of(this.postsPages.shift() ?? { items: [], next_cursor: null });
  }

  getSeenPosts(postIds: string[]): Observable<{ seen: string[] }> {
    this.seenQueries.push(postIds);
    return of({ seen: this.seenResponses.shift() ?? [] });
  }

  markPostsSeen(postIds: string[]): Observable<unknown> {
    this.markedSeen.push(postIds);
    return of({});
  }
}

describe('PublicFeedComponent seen/unread tracking', () => {
  let fixture: ComponentFixture<PublicFeedComponent>;
  let component: PublicFeedComponent;
  let api: MockApiService;

  beforeEach(async () => {
    api = new MockApiService();

    await TestBed.configureTestingModule({
      imports: [PublicFeedComponent],
      providers: [
        provideRouter([]),
        { provide: ApiService, useValue: api },
        {
          provide: ActivatedRoute,
          useValue: { queryParams: new BehaviorSubject({ filter: 'shorts' }) },
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(PublicFeedComponent);
    component = fixture.componentInstance;
  });

  it('keeps seen state from earlier pages when loading more (no set replacement)', () => {
    api.shortsPages = [
      { items: [makePost('p1'), makePost('p2')], next_cursor: 'c1' },
      { items: [makePost('p3'), makePost('p4')], next_cursor: null },
    ];
    api.seenResponses = [['p1'], ['p3']];

    component.ngOnInit();
    expect(component.seenPostIds.has('p1')).toBe(true);
    expect(component.unreadCount).toBe(1);

    component.loadMore();

    // p1 (page 1) must survive the page-2 seen lookup, which only returns p3.
    expect(component.seenPostIds.has('p1')).toBe(true);
    expect(component.seenPostIds.has('p3')).toBe(true);
    expect(component.unreadCount).toBe(2); // p2 and p4
  });

  it('only queries seen state for the newly loaded page', () => {
    api.shortsPages = [
      { items: [makePost('p1')], next_cursor: 'c1' },
      { items: [makePost('p2')], next_cursor: null },
    ];
    api.seenResponses = [[], []];

    component.ngOnInit();
    component.loadMore();

    expect(api.seenQueries).toEqual([['p1'], ['p2']]);
  });

  it('counts storm branches individually in the unread count', () => {
    const storm: Storm = {
      root: makePost('root1'),
      branches: [makePost('b1'), makePost('b2')],
    };
    api.stormsPages = [{ items: [storm], next_cursor: null }];
    api.seenResponses = [['root1']];

    component.load('storms', undefined, 42);

    // One feed item but three posts; only the root is seen.
    expect(component.unreadCount).toBe(2);
  });

  it('does not call the seen endpoint for an empty feed', () => {
    api.shortsPages = [{ items: [], next_cursor: null }];

    component.ngOnInit();

    expect(api.seenQueries).toEqual([]);
    expect(component.unreadCount).toBe(0);
  });

  it('ignores stale seen ids that are not part of the current feed', () => {
    api.shortsPages = [{ items: [makePost('p1')], next_cursor: null }];
    api.seenResponses = [[]];
    component.seenPostIds.add('ghost-from-previous-feed');

    component.ngOnInit();

    expect(component.unreadCount).toBe(1);
  });
});
