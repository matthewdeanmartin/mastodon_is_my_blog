import { Injectable, inject } from '@angular/core';
import {HttpClient, HttpHeaders, HttpParams} from '@angular/common/http';
import {MastodonStatus, MastodonAccount, Identity, AdminStatus, MastodonContext} from './mastodon';
import {RawContentPost} from './content-feed.utils';
import {Observable, throwError, timer, BehaviorSubject, of, Subject} from 'rxjs';
import {catchError, shareReplay, switchMap, tap} from 'rxjs/operators';

export interface Storm {
  root: RawContentPost;
  branches: RawContentPost[];
}

export interface FeedPage<T> {
  items: T[];
  next_cursor: string | null;
}

@Injectable({providedIn: 'root'})
export class ApiService {
  private http = inject(HttpClient);

  base = 'http://localhost:8000';
  private readonly META_KEY = 'meta_account_id';
  private readonly IDENTITY_KEY = 'mastodon_identity_id';

  // Observable to track server status
  private serverDownSubject = new BehaviorSubject(false);
  public serverDown$ = this.serverDownSubject.asObservable();

  // Trigger for components to refresh data (e.g. counts) after write/sync
  public refreshNeeded$ = new Subject<void>();

  private readonly syncInflight = new Map<string, Observable<unknown>>();

  // Meta Account State (The human)
  private metaIdSubject = new BehaviorSubject<string | null>(this.getMetaAccountId());
  public readonly metaId$ = this.metaIdSubject.asObservable();

  // Identity State (The specific Mastodon account context)
  private identityIdSubject = new BehaviorSubject<number | null>(this.getStoredIdentityId());
  public readonly identityId$ = this.identityIdSubject.asObservable();

  constructor() {
    this.startHealthCheck();
  }

  // --- Meta Account / Auth Helpers ---

  setMetaAccountId(id: string) {
    localStorage.setItem(this.META_KEY, id);
    this.metaIdSubject.next(id);
  }

  logout() {
    localStorage.removeItem(this.META_KEY);
    localStorage.removeItem(this.IDENTITY_KEY);
    this.metaIdSubject.next(null);
    this.identityIdSubject.next(null);
  }

  getMetaAccountId(): string | null {
    return localStorage.getItem(this.META_KEY);
  }

  // --- Identity State Helpers ---

  setIdentityId(id: number) {
    localStorage.setItem(this.IDENTITY_KEY, id.toString());
    this.identityIdSubject.next(id);
  }

  getStoredIdentityId(): number | null {
    const stored = localStorage.getItem(this.IDENTITY_KEY);
    return stored ? parseInt(stored, 10) : null;
  }

  getCurrentIdentityId(): number | null {
    return this.identityIdSubject.value;
  }

  private get headers(): HttpHeaders {
    const id = this.getMetaAccountId();
    let headers = new HttpHeaders();
    if (id) {
      headers = headers.set('X-Meta-Account-ID', id);
    }
    return headers;
  }

  // --- Existing Methods Updated with Headers & Identity ---

  private startHealthCheck(): void {
    timer(0, 10000) // Check immediately, then every 10 seconds
      .pipe(
        switchMap(() =>
          this.http.get(`${this.base}/api/status`, {headers: this.headers}).pipe(
            catchError(() => {
              // 1. Mark server as down
              this.serverDownSubject.next(true);
              // 2. Return null to keep the timer alive (throwError kills the stream)
              return of(null);
            }),
          ),
        ),
      )
      .subscribe((response) => {
        // If response is truthy, the request succeeded
        if (response) {
          if (this.serverDownSubject.value) {
            // Server was down, but now it's back!
            this.serverDownSubject.next(false);
            window.location.reload();
          }
        }
      });
  }

  // Wrapper to handle errors consistently
  private handleError(error: unknown): Observable<never> {
    // this.serverDownSubject.next(true);
    return throwError(() => error);
  }

  // --- PUBLIC READ (Context Aware) ---

  getPublicPosts(
    identityId: number,
    filter = 'all',
    user?: string,
    before?: string | null,
    limit = 30,
  ): Observable<FeedPage<RawContentPost>> {
    let params = new HttpParams()
      .set('identity_id', identityId.toString())
      .set('filter_type', filter)
      .set('limit', limit.toString());
    if (user) {
      params = params.set('user', user);
    }
    if (before) {
      params = params.set('before', before);
    }
    return this.http
      .get<FeedPage<RawContentPost>>(`${this.base}/api/posts`, {params, headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  getStorms(
    identityId: number,
    user?: string,
    before?: string | null,
    limit = 30,
  ): Observable<FeedPage<Storm>> {
    let params = new HttpParams()
      .set('identity_id', identityId.toString())
      .set('limit', limit.toString());
    if (user) {
      params = params.set('user', user);
    }
    if (before) {
      params = params.set('before', before);
    }
    return this.http
      .get<FeedPage<Storm>>(`${this.base}/api/posts/storms`, {params, headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  getShorts(
    identityId: number,
    user?: string,
    before?: string | null,
    limit = 30,
  ): Observable<FeedPage<RawContentPost>> {
    let params = new HttpParams()
      .set('identity_id', identityId.toString())
      .set('limit', limit.toString());
    if (user) {
      params = params.set('user', user);
    }
    if (before) {
      params = params.set('before', before);
    }
    return this.http
      .get<FeedPage<RawContentPost>>(`${this.base}/api/posts/shorts`, {params, headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  getBlogRoll(identityId: number, filter = 'all'): Observable<MastodonAccount[]> {
    const params = new HttpParams()
      .set('identity_id', identityId.toString())
      .set('filter_type', filter);

    return this.http
      .get<MastodonAccount[]>(`${this.base}/api/accounts/blogroll`, {params, headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  getCounts(identityId: number, user?: string): Observable<unknown> {
    let params = new HttpParams().set('identity_id', identityId.toString());
    if (user) params = params.set('user', user);
    return this.http
      .get<unknown>(`${this.base}/api/posts/counts`, {params, headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  getAccountInfo(acct: string, identityId: number): Observable<MastodonAccount> {
    const params = new HttpParams().set('identity_id', identityId.toString());
    return this.http
      .get<MastodonAccount>(`${this.base}/api/accounts/${acct}`, {params, headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  syncAccount(acct: string, identityId: number): Observable<unknown> {
    const params = new HttpParams().set('identity_id', identityId.toString());
    return this.http
      .post<unknown>(`${this.base}/api/accounts/${acct}/sync`, {}, {params, headers: this.headers})
      .pipe(
        tap(() => this.refreshNeeded$.next()), // Notify listeners to refresh data/counts
        catchError((err) => this.handleError(err))
      );
  }

  syncAccountDedup(acct: string, identityId: number): Observable<unknown> {
    const key = `${identityId}:${acct.trim()}`;
    const existing = this.syncInflight.get(key);
    if (existing) return existing;

    const req$ = this.syncAccount(acct, identityId).pipe(
      catchError(err => throwError(() => err)),
      shareReplay(1)
    );

    req$.subscribe({
      next: () => this.syncInflight.delete(key),
      error: () => this.syncInflight.delete(key),
    });

    this.syncInflight.set(key, req$);
    return req$;
  }

  // --- Single Item Reads (Less Context Sensitive) ---

  getPublicPost(id: string): Observable<MastodonStatus> {
    return this.http
      .get<MastodonStatus>(`${this.base}/api/posts/${id}`, {headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  // UPDATED: Now accepts identityId to correctly resolve post status/visibility
  getPostContext(id: string, identityId?: number): Observable<MastodonContext> {
    let params = new HttpParams();
    if (identityId) {
      params = params.set('identity_id', identityId.toString());
    }
    return this.http
      .get<MastodonContext>(`${this.base}/api/posts/${id}/context`, {params, headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  // --- Admin / Write ---

  getIdentities(): Observable<Identity[]> {
    return this.http
      .get<Identity[]>(`${this.base}/api/admin/identities`, {headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  loginUrl(): string {
    return `${this.base}/auth/login`;
  }

  getAdminStatus(): Observable<AdminStatus> {
    return this.http
      .get<AdminStatus>(`${this.base}/api/admin/status`, {headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  triggerSync(force = false): Observable<unknown> {
    return this.http
      .post<unknown>(`${this.base}/api/admin/sync?force=${force}`, {}, {headers: this.headers})
      .pipe(
          tap(() => this.refreshNeeded$.next()),
          catchError((err) => this.handleError(err))
      );
  }

  me(): Observable<unknown> {
    return this.http.get<unknown>(`${this.base}/api/me`, {headers: this.headers}).pipe(catchError((err) => this.handleError(err)));
  }

  // posts() {
  //   return this.http
  //     .get<any[]>(`${this.base}/api/posts`, {headers: this.headers})
  //     .pipe(catchError((err) => this.handleError(err)));
  // }

  createPost(status: string): Observable<unknown> {
    return this.http
      .post<unknown>(`${this.base}/api/posts`, {status, visibility: 'public'}, {headers: this.headers})
      .pipe(
          tap(() => this.refreshNeeded$.next()),
          catchError((err) => this.handleError(err))
      );
  }

  getPost(id: string): Observable<MastodonStatus> {
    return this.http
      .get<MastodonStatus>(`${this.base}/api/posts/${id}`, {headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  editPost(id: string, status: string): Observable<unknown> {
    return this.http
      .post<unknown>(`${this.base}/api/posts/${id}/edit`, {status}, {headers: this.headers})
      .pipe(
          tap(() => this.refreshNeeded$.next()),
          catchError((err) => this.handleError(err))
      );
  }

  getAnalytics(): Observable<unknown> {
    return this.http
      .get<unknown>(`${this.base}/api/posts/analytics`, {headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  // --- Seen Posts ---

  markPostSeen(postId: string): Observable<unknown> {
    return this.http
      .post<unknown>(`${this.base}/api/posts/${postId}/read`, {}, {headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  markPostsSeen(postIds: string[]): Observable<unknown> {
    return this.http
      .post<unknown>(`${this.base}/api/posts/read`, postIds, {headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  getSeenPosts(postIds: string[]): Observable<{seen: string[]}> {
    const params = new HttpParams().set('ids', postIds.join(','));
    return this.http
      .get<{seen: string[]}>(`${this.base}/api/posts/seen`, {params, headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  getUnreadCount(identityId: number): Observable<{unread_count: number}> {
    const params = new HttpParams().set('identity_id', identityId.toString());
    return this.http
      .get<{unread_count: number}>(`${this.base}/api/posts/unread-count`, {params, headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }
}
