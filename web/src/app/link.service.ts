import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable, of } from 'rxjs';
import { catchError, shareReplay } from 'rxjs/operators';

export interface LinkPreview {
  url: string;
  title: string | null;
  description: string | null;
  site_name: string | null;
  image: string | null;
  favicon: string | null;
}

@Injectable({ providedIn: 'root' })
export class LinkPreviewService {
  private base = 'http://localhost:8000';
  private cache = new Map<string, Observable<LinkPreview | null>>();

  constructor(private http: HttpClient) {}

  /**
   * Fetches link preview/card data for a given URL.
   * Results are cached to avoid duplicate requests.
   */
  getPreview(url: string): Observable<LinkPreview | null> {
    // Check cache first
    if (this.cache.has(url)) {
      return this.cache.get(url)!;
    }

    // Make request and cache the observable
    const params = new HttpParams().set('url', url);
    const request$ = this.http.get<LinkPreview>(`${this.base}/api/posts/card`, { params }).pipe(
      catchError((error) => {
        console.warn('Failed to fetch preview for:', url, error);
        return of(null);
      }),
      shareReplay(1) // Share the result among multiple subscribers
    );

    this.cache.set(url, request$);
    return request$;
  }

  /**
   * Extracts URLs from HTML content, ignoring hashtags and mentions.
   */
  extractUrls(html: string): string[] {
    const parser = new DOMParser();
    const doc = parser.parseFromString(html, 'text/html');

    // Cast to HTMLAnchorElement[] to access properties like classList
    const anchors = Array.from(doc.querySelectorAll('a[href]')) as HTMLAnchorElement[];

    return anchors
      .filter(anchor => {
        // 1. EXCLUDE HASHTAGS & MENTIONS
        // The JSON payload shows these links have "mention" and "hashtag" classes.
        if (anchor.classList.contains('hashtag') || anchor.classList.contains('mention')) {
          return false;
        }

        // 2. (Optional) EXCLUDE SPECIFIC DOMAINS
        // If you want to strictly block 'mastodon.social' or others regardless of class:
        const href = anchor.getAttribute('href');
        if (href) {
           // simple check against a blocklist
           const ignoredDomains = ['mastodon.social', 'appdot.net'];
           if (ignoredDomains.some(d => href.includes(d))) {
             return false;
           }
        }

        return true;
      })
      .map(anchor => anchor.getAttribute('href'))
      .filter((href): href is string => {
        if (!href) return false;
        // Only include http/https URLs
        return href.startsWith('http://') || href.startsWith('https://');
      })
      .filter((href, index, self) => self.indexOf(href) === index); // Remove duplicates
  }
}
