import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  ElementRef,
  Input,
  OnDestroy,
  OnInit,
  inject,
} from '@angular/core';

import { LinkPreviewService, LinkPreview } from './link.service';

@Component({
  selector: 'app-link-preview',
  standalone: true,
  imports: [],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (loading) {
      <div class="link-preview-skeleton" aria-label="Loading preview…">
        <div class="skeleton-image"></div>
        <div class="skeleton-text">
          <div class="skeleton-line wide"></div>
          <div class="skeleton-line narrow"></div>
        </div>
      </div>
    } @else if (preview) {
      <div class="link-preview-card">
        <a [href]="preview.url" target="_blank" rel="noopener noreferrer" class="preview-link">
          <div class="preview-content">
            @if (preview.image) {
              <img
                [src]="preview.image"
                [alt]="preview.title || 'Preview image'"
                class="preview-image"
                loading="lazy"
                decoding="async"
                (error)="onImageError($event)">
            }
            <div class="preview-text">
              <div class="preview-header">
                @if (preview.favicon && !faviconError) {
                  <img
                    [src]="preview.favicon"
                    alt="Site icon"
                    class="preview-favicon"
                    loading="lazy"
                    decoding="async"
                    (error)="onFaviconError()">
                }
                @if (preview.site_name) {
                  <span class="preview-site">{{ preview.site_name }}</span>
                }
              </div>
              @if (preview.title) {
                <h4 class="preview-title">{{ preview.title }}</h4>
              }
              @if (preview.description) {
                <p class="preview-description">{{ preview.description }}</p>
              }
              <div class="preview-url">{{ getDisplayUrl(preview.url) }}</div>
            </div>
          </div>
        </a>
      </div>
    }
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

    /* Skeleton */
    .link-preview-skeleton {
      margin: 12px 0;
      border: 1px solid #e1e8ed;
      border-radius: 8px;
      overflow: hidden;
      background: white;
    }

    .skeleton-image {
      width: 100%;
      height: 80px;
      background: linear-gradient(90deg, #f3f4f6 25%, #e9ebee 50%, #f3f4f6 75%);
      background-size: 200% 100%;
      animation: shimmer 1.2s infinite;
    }

    .skeleton-text {
      padding: 12px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .skeleton-line {
      height: 12px;
      border-radius: 4px;
      background: linear-gradient(90deg, #f3f4f6 25%, #e9ebee 50%, #f3f4f6 75%);
      background-size: 200% 100%;
      animation: shimmer 1.2s infinite;
    }

    .skeleton-line.wide { width: 80%; }
    .skeleton-line.narrow { width: 50%; }

    @keyframes shimmer {
      0% { background-position: 200% 0; }
      100% { background-position: -200% 0; }
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
export class LinkPreviewComponent implements OnInit, OnDestroy {
  private previewService = inject(LinkPreviewService);
  private elRef = inject(ElementRef);
  private cdr = inject(ChangeDetectorRef);

  @Input() url = '';

  preview: LinkPreview | null = null;
  loading = false;
  faviconError = false;

  private observer: IntersectionObserver | null = null;
  private fetched = false;

  ngOnInit(): void {
    if (!this.url) return;

    this.observer = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        if (entry.isIntersecting && !this.fetched) {
          this.fetched = true;
          this.observer?.disconnect();
          this.loadPreview();
        }
      },
      { rootMargin: '200px' }  // start loading 200px before entering viewport
    );

    this.observer.observe(this.elRef.nativeElement);
  }

  ngOnDestroy(): void {
    this.observer?.disconnect();
  }

  private loadPreview(): void {
    this.loading = true;
    this.cdr.markForCheck();

    this.previewService.getPreview(this.url).subscribe({
      next: (preview) => {
        this.preview = preview;
        this.loading = false;
        this.cdr.markForCheck();
      },
      error: (err) => {
        console.error('Preview fetch error:', err);
        this.loading = false;
        this.cdr.markForCheck();
      },
    });
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
