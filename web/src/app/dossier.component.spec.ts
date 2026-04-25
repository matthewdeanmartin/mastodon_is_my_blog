import { HttpErrorResponse } from '@angular/common/http';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { BehaviorSubject, Observable, of, throwError } from 'rxjs';
import { ApiService } from './api.service';
import { DossierComponent } from './dossier.component';
import { AccountCatchupStatus, Dossier, HeatmapCell, QuickDossier } from './mastodon';

class MockApiService {
  identityId$ = new BehaviorSubject<number | null>(42);
  quickLookupCandidates: string[] = [];
  dossierResult: Observable<Dossier> = throwError(() => new HttpErrorResponse({ status: 404 }));
  quickResults = new Map<string, Observable<QuickDossier>>();
  catchupStatus: AccountCatchupStatus = {
    running: false,
    finished: false,
    acct: 'alice',
    mode: 'recent',
    stage: 'idle',
    pages_fetched: 0,
    posts_fetched: 0,
    new_posts: 0,
    updated_posts: 0,
    started_at: '',
    finished_at: null,
    error: null,
    cancel_requested: false,
  };

  getDossier(acct: string, identityId: number): Observable<Dossier> {
    void acct;
    void identityId;
    return this.dossierResult;
  }

  getQuickDossier(acct: string, identityId: number): Observable<QuickDossier> {
    void identityId;
    this.quickLookupCandidates.push(acct);
    return (
      this.quickResults.get(acct) ??
      throwError(() => new HttpErrorResponse({ status: 404, statusText: `Missing ${acct}` }))
    );
  }

  getAccountCatchupStatus(): Observable<AccountCatchupStatus> {
    return of(this.catchupStatus);
  }

  getPostingHeatmap(): Observable<HeatmapCell[]> {
    return of([]);
  }

  getActivityCalendar(): Observable<{ date: string; count: number }[]> {
    return of([]);
  }

  getPublicPosts(): Observable<{ items: [] }> {
    return of({ items: [] });
  }

  getDossierInteractions(): Observable<[]> {
    return of([]);
  }

  getCurrentIdentityId(): number {
    return 42;
  }

  deepFetchDossier(): Observable<null> {
    return of(null);
  }

  startAccountCatchup(): Observable<null> {
    return of(null);
  }

  cancelAccountCatchup(): Observable<null> {
    return of(null);
  }

  followAccount(): Observable<null> {
    return of(null);
  }

  unfollowAccount(): Observable<null> {
    return of(null);
  }
}

function buildHeatmapWithSleepWindow(startHour: number, duration = 6): HeatmapCell[] {
  const cells: HeatmapCell[] = [];
  for (let dow = 0; dow < 7; dow++) {
    for (let hour = 0; hour < 24; hour++) {
      const inSleepWindow = hour >= startHour && hour < startHour + duration;
      cells.push({ dow, hour, count: inSleepWindow ? 0 : 10 });
    }
  }
  return cells;
}

describe('DossierComponent', () => {
  let fixture: ComponentFixture<DossierComponent>;
  let component: DossierComponent;
  let api: MockApiService;

  beforeEach(async () => {
    api = new MockApiService();

    await TestBed.configureTestingModule({
      imports: [DossierComponent],
      providers: [
        provideRouter([]),
        { provide: ApiService, useValue: api },
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: {
              paramMap: convertToParamMap({ acct: 'alice' }),
            },
          },
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(DossierComponent);
    component = fixture.componentInstance;
  });

  afterEach(() => {
    history.replaceState(null, '', '/');
  });

  it('tries a canonical acct from thread navigation state when quick dossier fallback needs it', () => {
    history.replaceState(
      {
        account: {
          id: '1',
          username: 'alice',
          acct: 'alice',
          display_name: 'Alice',
          avatar: 'https://example.social/avatar.png',
          bot: false,
          note: '',
          url: 'https://example.social/@alice',
        },
      },
      '',
      '/',
    );
    api.quickResults.set(
      'alice@example.social',
      of({
        id: '1',
        acct: 'alice@example.social',
        display_name: 'Alice',
        avatar: 'https://example.social/avatar.png',
        header: '',
        url: 'https://example.social/@alice',
        note: '',
        bot: false,
        locked: false,
        followers_count: 10,
        following_count: 5,
        statuses_count: 42,
        created_at: null,
        featured_hashtags: [],
        fields: [],
      }),
    );

    fixture.detectChanges();

    expect(api.quickLookupCandidates).toEqual(['alice', 'alice@example.social']);
    expect(component.quickDossier?.acct).toBe('alice@example.social');
    expect(component.cacheMissMessage).toContain('quick API lookup');
    expect(component.error).toBeNull();
  });

  it('keeps inferred timezone text stable when the display offset changes', () => {
    component.heatmapCells = buildHeatmapWithSleepWindow(7);

    component.inferTimezoneFromHeatmap();
    const inferred = component.inferredTimezoneDescription;

    component.heatmapTzOffset = 9;

    expect(inferred).toContain('UTC-5');
    expect(inferred).toContain('Eastern / New York');
    expect(component.inferredTimezoneDescription).toBe(inferred);
  });
});
