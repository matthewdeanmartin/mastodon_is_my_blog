import {Injectable} from '@angular/core';
import {HttpClient} from '@angular/common/http';
import {MastodonStatus} from './mastodon';

@Injectable({providedIn: 'root'})
export class ApiService {
  base = 'http://localhost:8000';

  constructor(private http: HttpClient) {
  }
  // Public Read
  getPublicPosts(filter: string = 'all') {
    return this.http.get<any[]>(`${this.base}/api/public/posts?filter_type=${filter}`);
  }

  getPublicPost(id: string) {
    return this.http.get<any>(`${this.base}/api/public/posts/${id}`);
  }

  getComments(id: string) {
    return this.http.get<any>(`${this.base}/api/public/posts/${id}/comments`);
  }


  comments(id: string) {
    return this.http.get(`${this.base}/api/posts/${id}/comments`);
  }

  // Admin / Auth
  loginUrl() { return `${this.base}/auth/login`; }

  getAdminStatus() {
    return this.http.get<{connected: boolean, last_sync: string}>(`${this.base}/api/admin/status`);
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
}
