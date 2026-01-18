import {Injectable} from '@angular/core';
import {HttpClient, HttpHeaders, HttpParams} from '@angular/common/http';
import {MastodonStatus} from './mastodon';
import {Observable, throwError, timer, BehaviorSubject, of} from 'rxjs';
import {catchError, shareReplay, switchMap, tap} from 'rxjs/operators';

@Injectable({providedIn: 'root'})
export class ApiService {
  base = 'http://localhost:8000';
  private META_KEY = 'meta_account_id';

  // Observable to track server status
  private serverDownSubject = new BehaviorSubject<boolean>(false);
  public serverDown$ = this.serverDownSubject.asObservable();

  private pollingSubscription: any = null;

  constructor(private http: HttpClient) {
    this.startHealthCheck();
  }

  // --- Meta Account / Auth Helpers ---

  setMetaAccountId(id: string) {
    localStorage.setItem(this.META_KEY, id);
    window.location.reload(); // Simple reload to refresh app state
  }

  getMetaAccountId(): string | null {
    return localStorage.getItem(this.META_KEY);
  }

  logout() {
    localStorage.removeItem(this.META_KEY);
    window.location.reload();
  }

  private get headers(): HttpHeaders {
    const id = this.getMetaAccountId();
    let headers = new HttpHeaders();
    if (id) {
      headers = headers.set('X-Meta-Account-ID', id);
    }
    return headers;
  }

  // --- Existing Methods Updated with Headers ---

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

  // Public Read
  getPublicPosts(filter: string = 'all', user?: string): Observable<any[]> {
    let params = new HttpParams().set('filter_type', filter);
    if (user) {
      params = params.set('user', user);
    }
    return this.http
      .get<any[]>(`${this.base}/api/posts`, {params, headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  getPublicPost(id: string) {
    return this.http
      .get<any>(`${this.base}/api/posts/${id}`, {headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  getComments(id: string) {
    return this.http
      .get<any>(`${this.base}/api/posts/${id}/comments`, {headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  // NEW: Fetch full context (ancestors + descendants)
  getPostContext(id: string): Observable<any> {
    return this.http
      .get<any>(`${this.base}/api/posts/${id}/context`, {headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  getAccountInfo(acct: string): Observable<any> {
    return this.http
      .get<any>(`${this.base}/api/accounts/${acct}`, {headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  syncAccount(acct: string): Observable<any> {
    return this.http
      .post<any>(`${this.base}/api/accounts/${acct}/sync`, {}, {headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  comments(id: string) {
    return this.http
      .get(`${this.base}/api/posts/${id}/comments`, {headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  // Admin / Auth

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
      .pipe(catchError((err) => this.handleError(err)));
  }

  me() {
    return this.http.get(`${this.base}/api/me`, {headers: this.headers}).pipe(catchError((err) => this.handleError(err)));
  }

  posts() {
    return this.http
      .get<any[]>(`${this.base}/api/posts`, {headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  createPost(status: string) {
    return this.http
      .post(`${this.base}/api/posts`, {status, visibility: 'public'}, {headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  getPost(id: string) {
    return this.http
      .get<MastodonStatus>(`${this.base}/api/posts/${id}`, {headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  editPost(id: string, status: string) {
    return this.http
      .post(`${this.base}/api/posts/${id}/edit`, {status}, {headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  getStorms(user?: string): Observable<any[]> {
    let params = new HttpParams();
    if (user) {
      params = params.set('user', user);
    }
    return this.http
      .get<any[]>(`${this.base}/api/posts/storms`, {params, headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  getShorts(user?: string): Observable<any[]> {
    let params = new HttpParams();
    if (user) {
      params = params.set('user', user);
    }
    return this.http
      .get<any[]>(`${this.base}/api/posts/shorts`, {params, headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  getBlogRoll(filter: string = 'all'): Observable<any[]> {
    // Always send the filter_type parameter
    let params = new HttpParams().set('filter_type', filter);

    return this.http
      .get<any[]>(`${this.base}/api/accounts/blogroll`, {params, headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  // getBlogRoll(filter: string = 'all'): Observable<any[]> {
  //   let params = new HttpParams();
  //   if (filter && filter !== 'all') {
  //     params = params.set('filter_type', filter);
  //   }
  //   return this.http
  //     .get<any[]>(`${this.base}/api/accounts/blogroll`, { params })
  //     .pipe(catchError((err) => this.handleError(err)));
  // }

  getAnalytics(): Observable<any> {
    return this.http
      .get<any>(`${this.base}/api/posts/analytics`, {headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }

  getCounts(user?: string): Observable<any> {
    let params = new HttpParams();
    if (user) params = params.set('user', user);
    return this.http
      .get<any>(`${this.base}/api/posts/counts`, {params, headers: this.headers})
      .pipe(catchError((err) => this.handleError(err)));
  }
}
