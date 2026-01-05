// app.component.ts
import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink, RouterOutlet, Router } from '@angular/router';
import { ApiService } from './api.service';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, RouterOutlet, RouterLink],
  templateUrl: './app.component.html'
})
export class AppComponent implements OnInit {
  currentFilter = 'all';
  blogRoll: any[] = [];

  constructor(private api: ApiService, private router: Router) {}

  ngOnInit() {
    // 1. Fetch Blog Roll
    this.api.getBlogRoll().subscribe(accounts => {
      this.blogRoll = accounts;
    });
  }

  setFilter(filter: string) {
    this.currentFilter = filter;
    // Use 'merge' to preserve the 'user' param if it exists
    this.router.navigate(['/'], {
      queryParams: { filter: filter },
      queryParamsHandling: 'merge'
    });
  }
}
