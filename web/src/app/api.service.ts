import {Injectable} from '@angular/core';
import {HttpClient, HttpParams} from '@angular/common/http';
import {MastodonStatus} from './mastodon';
import { Observable } from 'rxjs';

@Injectable({providedIn: 'root'})
export class ApiService {
  base = 'http://localhost:8000';

  constructor(private http: HttpClient) {
  }

  // Public Read
  getPublicPosts(filter: string = 'all', user?: string): Observable<any[]> {
    let params = new HttpParams().set('filter_type', filter);
    if (user) {
      params = params.set('user', user);
    }
    return this.http.get<any[]>(`${this.base}/api/public/posts`, { params });
  }

  getPublicPost(id: string) {
    return this.http.get<any>(`${this.base}/api/public/posts/${id}`);
  }

  getComments(id: string) {
    return this.http.get<any>(`${this.base}/api/public/posts/${id}/comments`);
  }

  getAccountInfo(acct: string): Observable<any> {
    return this.http.get<any>(`${this.base}/api/public/accounts/${acct}`);
  }

  syncAccount(acct: string): Observable<any> {
    return this.http.post<any>(`${this.base}/api/public/accounts/${acct}/sync`, {});
  }

  comments(id: string) {
    return this.http.get(`${this.base}/api/posts/${id}/comments`);
  }

  // Admin / Auth
  loginUrl() { return `${this.base}/auth/login`; }

  getAdminStatus() {
    return this.http.get<{connected: boolean, last_sync: string, current_user: any}>(`${this.base}/api/admin/status`);
  }

  triggerSync(force: boolean = false) {
    return this.http.post(`${this.base}/api/admin/sync?force=${force}`, {});
  }

  me() {
    return this.http.get(`${this.base}/api/me`);
  }

  posts() {
    return this.http.get<any[]>(`${this.base}/api/posts`);
  }

  createPost(status: string) {
    return this.http.post(`${this.base}/api/posts`, {status, visibility: 'public'});
  }

  getPost(id: string) {
    return this.http.get<MastodonStatus>(`${this.base}/api/posts/${id}`);
  }


  editPost(id: string, status: string) {
    return this.http.post(`${this.base}/api/posts/${id}/edit`, {status});
  }

  getStorms(user?: string): Observable<any[]> {
    let params = new HttpParams();
    if (user) {
      params = params.set('user', user);
    }
    return this.http.get<any[]>(`${this.base}/api/public/storms`, { params });
  }

  getBlogRoll(): Observable<any[]> {
    return this.http.get<any[]>(`${this.base}/api/public/accounts/blogroll`);
  }

  getAnalytics(): Observable<any> {
    return this.http.get<any>(`${this.base}/api/public/analytics`);
  }
}
