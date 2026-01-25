// src/app/content.component.ts
import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink, RouterOutlet } from '@angular/router';

@Component({
  selector: 'app-content',
  standalone: true,
  imports: [CommonModule, RouterLink, RouterOutlet],
  template: `
    <div class="content-layout">
      <div class="content-nav">
        <h2 style="margin: 0 0 20px 0; color: #374151;">Content Hub</h2>
        <nav class="content-subnav">
          <a routerLink="images" routerLinkActive="active">📷 Images</a>
          <a routerLink="software" routerLinkActive="active">💻 Software</a>
          <a routerLink="links" routerLinkActive="active">🔗 Links</a>
          <a routerLink="news" routerLinkActive="active">📰 News</a>
        </nav>
      </div>

      <div class="content-main">
        <router-outlet></router-outlet>
      </div>
    </div>
  `,
  styles: [`
    .content-layout {
      display: grid;
      grid-template-columns: 200px 1fr;
      gap: 20px;
      min-height: 60vh;
    }

    .content-nav {
      background: white;
      padding: 20px;
      border-radius: 8px;
      border: 1px solid #e1e8ed;
      height: fit-content;
    }

    .content-subnav {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .content-subnav a {
      padding: 10px 15px;
      border-radius: 6px;
      text-decoration: none;
      color: #374151;
      transition: all 0.2s;
      font-weight: 500;
    }

    .content-subnav a:hover {
      background: #f3f4f6;
      color: #6366f1;
    }

    .content-subnav a.active {
      background: #6366f1;
      color: white;
    }

    .content-main {
      min-height: 400px;
    }

    @media (max-width: 768px) {
      .content-layout {
        grid-template-columns: 1fr;
      }

      .content-subnav {
        flex-direction: row;
        overflow-x: auto;
      }
    }
  `]
})
export class ContentComponent {}
