import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import {MastodonStatus} from './mastodon';

@Injectable({ providedIn: 'root' })
export class ApiService {
  base = 'http://localhost:8000';

  constructor(private http: HttpClient) {}

  loginUrl() { return `${this.base}/auth/login`; }

  me() { return this.http.get(`${this.base}/api/me`); }
  posts() { return this.http.get<any[]>(`${this.base}/api/posts`); }
  createPost(status: string) { return this.http.post(`${this.base}/api/posts`, { status, visibility: 'public' }); }

  // getPost(id: string) { return this.http.get(`${this.base}/api/posts/${id}`); }
  //
  getPost(id: string) {
    return this.http.get<MastodonStatus>(`${this.base}/api/posts/${id}`);
  }
  comments(id: string) { return this.http.get(`${this.base}/api/posts/${id}/comments`); }
  editPost(id: string, status: string) { return this.http.post(`${this.base}/api/posts/${id}/edit`, { status, delete_old: true }); }
}
