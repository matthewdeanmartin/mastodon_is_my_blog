import {Injectable} from '@angular/core';
import {HttpClient, HttpHeaders, HttpParams} from '@angular/common/http';
import {MastodonStatus} from './mastodon';
import {Observable, throwError, timer, BehaviorSubject, of, Subject} from 'rxjs';
import {catchError, shareReplay, switchMap, tap} from 'rxjs/operators';

@Injectable({providedIn: 'root'})
export class ApiService {
  base = 'http://localhost:8000';
  private META_KEY = 'meta_account_id';
  private IDENTITY_KEY = 'mastodon_identity_id';

  // Observable to track server status
  private serverDownSubject = new BehaviorSubject<boolean>(false);
  public serverDown$ = this.serverDownSubject.asObservable();

  // Trigger for components to refresh data (e.g. counts) after write/sync
  public refreshNeeded$ = new Subject<void>();

  private pollingSubscription: any = null;

  private readonly syncInflight = new Map<string, Observable<any>>();

  // Meta Account State (The human)
  private metaIdSubject = new BehaviorSubject<string | null>(this.getMetaAccountId());
  public readonly metaId$ = this.metaIdSubject.asObservable();

  // Identity State (The specific Mastodon account context)
  private identityIdSubject = new BehaviorSubject<number | null>(this.getStoredIdentityId());
  public readonly identityId$ = this.identityIdSubject.asObservable();

  constructor(private http: HttpClient) {
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
  private handleError(error: any): Observable<never> {
    this.serverDownSubject.next(true);
    return throwError(() => error);
  }

  // --- PUBLIC READ (Context Aware) ---

  getPublicPosts(identityId: number, filter: string = 'all', user?: string): Observable<any[]> {
    let params = new HttpParams()
      .set('identity_id', identityId.toString())
      .set('filter_type', filter);
    if (user) {
      params = params.set('user', user);
    }
    return this.http
      .get<any[]>(`${this.base}/api/posts`, {params, headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  getStorms(identityId: number, user?: string): Observable<any[]> {
    let params = new HttpParams().set('identity_id', identityId.toString());
    if (user) {
      params = params.set('user', user);
    }
    return this.http
      .get<any[]>(`${this.base}/api/posts/storms`, {params, headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  getShorts(identityId: number, user?: string): Observable<any[]> {
    let params = new HttpParams().set('identity_id', identityId.toString());
    if (user) {
      params = params.set('user', user);
    }
    return this.http
      .get<any[]>(`${this.base}/api/posts/shorts`, {params, headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  getBlogRoll(identityId: number, filter: string = 'all'): Observable<any[]> {
    let params = new HttpParams()
      .set('identity_id', identityId.toString())
      .set('filter_type', filter);

    return this.http
      .get<any[]>(`${this.base}/api/accounts/blogroll`, {params, headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  getCounts(identityId: number, user?: string): Observable<any> {
    let params = new HttpParams().set('identity_id', identityId.toString());
    if (user) params = params.set('user', user);
    return this.http
      .get<any>(`${this.base}/api/posts/counts`, {params, headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  getAccountInfo(acct: string, identityId: number): Observable<any> {
    const params = new HttpParams().set('identity_id', identityId.toString());
    return this.http
      .get<any>(`${this.base}/api/accounts/${acct}`, {params, headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  syncAccount(acct: string, identityId: number): Observable<any> {
    const params = new HttpParams().set('identity_id', identityId.toString());
    return this.http
      .post<any>(`${this.base}/api/accounts/${acct}/sync`, {}, {params, headers: this.headers})
      .pipe(
        tap(() => this.refreshNeeded$.next()), // Notify listeners to refresh data/counts
        catchError((err) => this.handleError(err))
      );
  }

  syncAccountDedup(acct: string, identityId: number): Observable<any> {
    const key = `${identityId}:${acct.trim()}`;
    const existing = this.syncInflight.get(key);
    if (existing) return existing;

    const req$ = this.syncAccount(acct, identityId).pipe(
      tap({next: () => {}, error: () => {}}),
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

  getPublicPost(id: string) {
    return this.http
      .get<any>(`${this.base}/api/posts/${id}`, {headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  // UPDATED: Now accepts identityId to correctly resolve post status/visibility
  getPostContext(id: string, identityId?: number): Observable<any> {
    let params = new HttpParams();
    if (identityId) {
      params = params.set('identity_id', identityId.toString());
    }
    return this.http
      .get<any>(`${this.base}/api/posts/${id}/context`, {params, headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  // --- Admin / Write ---

  getIdentities(): Observable<any[]> {
    return this.http
      .get<any[]>(`${this.base}/api/admin/identities`, {headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  loginUrl() {
    return `${this.base}/auth/login`;
  }

  getAdminStatus() {
    return this.http
      .get<{
        connected: boolean;
        last_sync: string;
        current_user: any;
      }>(`${this.base}/api/admin/status`, {headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  triggerSync(force: boolean = false) {
    return this.http
      .post(`${this.base}/api/admin/sync?force=${force}`, {}, {headers: this.headers})
      .pipe(
          tap(() => this.refreshNeeded$.next()),
          catchError((err) => this.handleError(err))
      );
  }

  me() {
    return this.http.get(`${this.base}/api/me`, {headers: this.headers}).pipe(catchError((err) => this.handleError(err)));
  }

  // posts() {
  //   return this.http
  //     .get<any[]>(`${this.base}/api/posts`, {headers: this.headers})
  //     .pipe(catchError((err) => this.handleError(err)));
  // }

  createPost(status: string) {
    return this.http
      .post(`${this.base}/api/posts`, {status, visibility: 'public'}, {headers: this.headers})
      .pipe(
          tap(() => this.refreshNeeded$.next()),
          catchError((err) => this.handleError(err))
      );
  }

  getPost(id: string) {
    return this.http
      .get<MastodonStatus>(`${this.base}/api/posts/${id}`, {headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  editPost(id: string, status: string) {
    return this.http
      .post(`${this.base}/api/posts/${id}/edit`, {status}, {headers: this.headers})
      .pipe(
          tap(() => this.refreshNeeded$.next()),
          catchError((err) => this.handleError(err))
      );
  }

  getAnalytics(): Observable<any> {
    return this.http
      .get<any>(`${this.base}/api/posts/analytics`, {headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }
}
