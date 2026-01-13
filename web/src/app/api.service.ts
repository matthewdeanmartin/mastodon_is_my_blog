import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { MastodonStatus } from './mastodon';
import { Observable, throwError, timer, BehaviorSubject, of } from 'rxjs';
import { catchError, retry, switchMap, tap } from 'rxjs/operators';

@Injectable({ providedIn: 'root' })
export class ApiService {
  base = 'http://localhost:8000';

  // Observable to track server status
  private serverDownSubject = new BehaviorSubject<boolean>(false);
  public serverDown$ = this.serverDownSubject.asObservable();

  private pollingSubscription: any = null;

  constructor(private http: HttpClient) {
    this.startHealthCheck();
  }

  // Start periodic health check
  private startHealthCheck(): void {
    timer(0, 10000) // Check immediately, then every 10 seconds
      .pipe(
        switchMap(() =>
          this.http.get(`${this.base}/api/status`).pipe(
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
      .get<any[]>(`${this.base}/api/public/posts`, { params })
      .pipe(catchError((err) => this.handleError(err)));
  }

  getPublicPost(id: string) {
    return this.http
      .get<any>(`${this.base}/api/public/posts/${id}`)
      .pipe(catchError((err) => this.handleError(err)));
  }

  getComments(id: string) {
    return this.http
      .get<any>(`${this.base}/api/public/posts/${id}/comments`)
      .pipe(catchError((err) => this.handleError(err)));
  }

  // NEW: Fetch full context (ancestors + descendants)
  getPostContext(id: string): Observable<any> {
    return this.http
      .get<any>(`${this.base}/api/public/posts/${id}/context`)
      .pipe(catchError((err) => this.handleError(err)));
  }

  getAccountInfo(acct: string): Observable<any> {
    return this.http
      .get<any>(`${this.base}/api/public/accounts/${acct}`)
      .pipe(catchError((err) => this.handleError(err)));
  }

  syncAccount(acct: string): Observable<any> {
    return this.http
      .post<any>(`${this.base}/api/public/accounts/${acct}/sync`, {})
      .pipe(catchError((err) => this.handleError(err)));
  }

  comments(id: string) {
    return this.http
      .get(`${this.base}/api/posts/${id}/comments`)
      .pipe(catchError((err) => this.handleError(err)));
  }

  // Admin / Auth
  loginUrl() {
    return `${this.base}/auth/login`;
  }

  getAdminStatus() {
    return this.http
      .get<{
        connected: boolean;
        last_sync: string;
        current_user: any;
      }>(`${this.base}/api/admin/status`)
      .pipe(catchError((err) => this.handleError(err)));
  }

  triggerSync(force: boolean = false) {
    return this.http
      .post(`${this.base}/api/admin/sync?force=${force}`, {})
      .pipe(catchError((err) => this.handleError(err)));
  }

  me() {
    return this.http.get(`${this.base}/api/me`).pipe(catchError((err) => this.handleError(err)));
  }

  posts() {
    return this.http
      .get<any[]>(`${this.base}/api/posts`)
      .pipe(catchError((err) => this.handleError(err)));
  }

  createPost(status: string) {
    return this.http
      .post(`${this.base}/api/posts`, { status, visibility: 'public' })
      .pipe(catchError((err) => this.handleError(err)));
  }

  getPost(id: string) {
    return this.http
      .get<MastodonStatus>(`${this.base}/api/posts/${id}`)
      .pipe(catchError((err) => this.handleError(err)));
  }

  editPost(id: string, status: string) {
    return this.http
      .post(`${this.base}/api/posts/${id}/edit`, { status })
      .pipe(catchError((err) => this.handleError(err)));
  }

  getStorms(user?: string): Observable<any[]> {
    let params = new HttpParams();
    if (user) {
      params = params.set('user', user);
    }
    return this.http
      .get<any[]>(`${this.base}/api/public/storms`, { params })
      .pipe(catchError((err) => this.handleError(err)));
  }

  getShorts(user?: string): Observable<any[]> {
    let params = new HttpParams();
    if (user) {
      params = params.set('user', user);
    }
    return this.http
      .get<any[]>(`${this.base}/api/public/shorts`, { params })
      .pipe(catchError((err) => this.handleError(err)));
  }

  getBlogRoll(filter: string = 'all'): Observable<any[]> {
    let params = new HttpParams();
    if (filter && filter !== 'all') {
      params = params.set('filter_type', filter);
    }
    return this.http
      .get<any[]>(`${this.base}/api/public/accounts/blogroll`, { params })
      .pipe(catchError((err) => this.handleError(err)));
  }

  getAnalytics(): Observable<any> {
    return this.http
      .get<any>(`${this.base}/api/public/analytics`)
      .pipe(catchError((err) => this.handleError(err)));
  }

  getCounts(user?: string): Observable<any> {
    let params = new HttpParams();
    if (user) params = params.set('user', user);
    return this.http
      .get<any>(`${this.base}/api/public/counts`, { params })
      .pipe(catchError((err) => this.handleError(err)));
  }
}
