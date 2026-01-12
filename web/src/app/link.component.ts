import { Component, Input, OnInit, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { LinkPreviewService, LinkPreview } from './link.service';

@Component({
  selector: 'app-link-preview',
  standalone: true,
  imports: [CommonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div *ngIf="preview" class="link-preview-card">
      <a [href]="preview.url" target="_blank" rel="noopener noreferrer" class="preview-link">
        <div class="preview-content">
          <img *ngIf="preview.image"
               [src]="preview.image"
               [alt]="preview.title || 'Preview image'"
               class="preview-image"
               (error)="onImageError($event)">

          <div class="preview-text">
            <div class="preview-header">
              <img *ngIf="preview.favicon && !faviconError"
                   [src]="preview.favicon"
                   alt="Site icon"
                   class="preview-favicon"
                   (error)="onFaviconError()">
              <span *ngIf="preview.site_name" class="preview-site">{{ preview.site_name }}</span>
            </div>

            <h4 *ngIf="preview.title" class="preview-title">{{ preview.title }}</h4>
            <p *ngIf="preview.description" class="preview-description">{{ preview.description }}</p>

            <div class="preview-url">{{ getDisplayUrl(preview.url) }}</div>
          </div>
        </div>
      </a>
    </div>
  `,
  styles: [`
    .link-preview-card {
      margin: 12px 0;
      border: 1px solid #e1e8ed;
      border-radius: 8px;
      overflow: hidden;
      transition: all 0.2s;
      background: white;
    }

    .link-preview-card:hover {
      border-color: #6366f1;
      box-shadow: 0 2px 8px rgba(99, 102, 241, 0.1);
    }

    .preview-link {
      text-decoration: none;
      color: inherit;
      display: block;
    }

    .preview-content {
      display: flex;
      flex-direction: column;
    }

    .preview-image {
      width: 100%;
      height: 200px;
      object-fit: cover;
      background: #f3f4f6;
    }

    .preview-text {
      padding: 12px;
    }

    .preview-header {
      display: flex;
      align-items: center;
      gap: 6px;
      margin-bottom: 8px;
    }

    .preview-favicon {
      width: 16px;
      height: 16px;
      object-fit: contain;
    }

    .preview-site {
      font-size: 0.75rem;
      color: #6b7280;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      font-weight: 600;
    }

    .preview-title {
      font-size: 1rem;
      font-weight: 600;
      margin: 0 0 6px 0;
      color: #1f2937;
      line-height: 1.3;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }

    .preview-description {
      font-size: 0.875rem;
      color: #6b7280;
      margin: 0 0 8px 0;
      line-height: 1.4;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }

    .preview-url {
      font-size: 0.75rem;
      color: #9ca3af;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    @media (max-width: 768px) {
      .preview-image {
        height: 150px;
      }

      .preview-title {
        font-size: 0.9rem;
      }

      .preview-description {
        font-size: 0.8rem;
      }
    }
  `]
})
export class LinkPreviewComponent implements OnInit {
  @Input() url: string = '';

  preview: LinkPreview | null = null;
  faviconError = false;

  constructor(private previewService: LinkPreviewService) {}

  ngOnInit(): void {
    if (this.url) {
      this.previewService.getPreview(this.url).subscribe({
        next: (preview) => {
          this.preview = preview;
        },
        error: (err) => {
          console.error('Preview fetch error:', err);
        }
      });
    }
  }

  getDisplayUrl(url: string): string {
    try {
      const urlObj = new URL(url);
      return urlObj.hostname + urlObj.pathname;
    } catch {
      return url;
    }
  }

  onImageError(event: Event): void {
    const img = event.target as HTMLImageElement;
    img.style.display = 'none';
  }

  onFaviconError(): void {
    this.faviconError = true;
  }
}
