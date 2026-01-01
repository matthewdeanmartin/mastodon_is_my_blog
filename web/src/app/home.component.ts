import { Component, OnInit } from '@angular/core';
import { ApiService } from './api.service';
import {CommonModule} from '@angular/common';
import {FormsModule} from '@angular/forms';
import {RouterModule} from '@angular/router';

@Component({
  selector: 'app-home',
  standalone: true,
  templateUrl: './home.component.html',
  imports:[CommonModule,FormsModule,RouterModule]
})
export class HomeComponent implements OnInit {
  me: any;
  posts: any[] = [];
  draft = '';

  constructor(public api: ApiService) {}

  ngOnInit(): void {
    this.load();
  }

  load() {
    this.api.me().subscribe({ next: v => this.me = v, error: _ => this.me = null });
    this.api.posts().subscribe({ next: v => this.posts = v, error: _ => this.posts = [] });
  }

  publish() {
    this.api.createPost(this.draft).subscribe({
      next: _ => { this.draft = ''; this.load(); },
      error: e => alert('Publish failed: ' + (e?.error?.detail ?? e.message))
    });
  }

  stripHtml(html: string) {
    return (html || '').replace(/<[^>]+>/g, '').trim();
  }
}
