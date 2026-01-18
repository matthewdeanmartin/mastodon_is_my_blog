import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from './api.service';
import { Router } from '@angular/router';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="container" style="max-width: 400px; margin-top: 50px;">
      <h2 class="post-title">Select Meta Account</h2>
      <p class="muted">Enter your Meta Account ID (integer).</p>

      <div style="margin: 20px 0;">
        <input
          type="number"
          [(ngModel)]="metaId"
          placeholder="e.g. 1"
          style="width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 4px;">
      </div>

      <button (click)="login()" [disabled]="!metaId">Enter</button>

      <div style="margin-top: 20px; font-size: 0.8rem; color: #666;">
        If you are running locally without setup, ID <strong>1</strong> is usually the default.
      </div>
    </div>
  `
})
export class LoginComponent {
  metaId: string = '1';

  constructor(private api: ApiService, private router: Router) {}

  login() {
    if (this.metaId) {
      this.api.setMetaAccountId(this.metaId);
      // The service reloads the page, but just in case:
      this.router.navigate(['/']);
    }
  }
}
