import { Component } from '@angular/core';
import {Router, RouterLink, RouterOutlet} from '@angular/router';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-root',
  standalone: true,
  templateUrl: './app.component.html',
  imports: [RouterOutlet, RouterLink, CommonModule]
})
export class AppComponent {
  currentFilter = 'all';

  constructor(private router: Router) {}

  setFilter(filter: string) {
    this.currentFilter = filter;
    // We pass the filter via query params or state to the feed component
    this.router.navigate(['/'], { queryParams: { filter: filter } });
  }
}
