import { Component, OnInit } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { ApiService } from './api.service';
import {CommonModule} from '@angular/common';
import {FormsModule} from '@angular/forms';

@Component({
  selector: 'app-post',
  standalone: true,
  templateUrl: './post.component.html',
  imports:[CommonModule,FormsModule]
})
export class PostComponent implements OnInit {
  id!: string;
  post: any;
  comments: any;
  editText = '';

  constructor(private route: ActivatedRoute, private router: Router, private api: ApiService) {}

  ngOnInit(): void {
    this.id = this.route.snapshot.paramMap.get('id')!;
    this.load();
  }

  load() {
    this.api.getPost(this.id).subscribe({
      next: p => { this.post = p; this.editText = this.text(p.content); },
      error: e => alert('Load post failed: ' + (e?.error?.detail ?? e.message))
    });
    this.api.comments(this.id).subscribe({
      next: c => this.comments = c,
      error: _ => this.comments = { descendants: [] }
    });
  }

  saveEdit() {
  this.api.editPost(this.id, this.editText).subscribe({
    // Just reuse the current ID, or use r.id (which is the same)
    next: (r: any) => this.router.navigate(['/post', r.id]),
    error: e => alert('Edit failed: ' + (e?.error?.detail ?? e.message))
  });
}

  text(html: string) {
    return (html || '').replace(/<[^>]+>/g, '').trim();
  }

  back() { this.router.navigate(['/']); }
}
