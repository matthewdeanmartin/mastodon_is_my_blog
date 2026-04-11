import { TestBed } from '@angular/core/testing';
import { HttpClientTestingModule, HttpTestingController } from '@angular/common/http/testing';
import { LinkPreviewService, LinkPreview } from './link.service';
import { firstValueFrom } from 'rxjs';

describe('LinkPreviewService', () => {
  let service: LinkPreviewService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule],
      providers: [LinkPreviewService],
    });
    service = TestBed.inject(LinkPreviewService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  describe('getPreview', () => {
    const mockPreview: LinkPreview = {
      url: 'https://example.com',
      title: 'Example Title',
      description: 'Example description',
      site_name: 'Example Site',
      image: 'https://example.com/image.png',
      favicon: 'https://example.com/favicon.ico',
    };

    it('should fetch link preview from API', async () => {
      const promise = firstValueFrom(service.getPreview('https://example.com'));

      const req = httpMock.expectOne((r) => r.url.includes('/api/posts/card'));
      expect(req.request.params.get('url')).toBe('https://example.com');
      req.flush(mockPreview);

      const result = await promise;
      expect(result).toEqual(mockPreview);
    });

    it('should cache preview results', () => {
      const url = 'https://cached-example.com';

      service.getPreview(url).subscribe();
      service.getPreview(url).subscribe();

      const requests = httpMock.match((r) => r.url.includes('/api/posts/card'));
      expect(requests.length).toBe(1);
      requests[0].flush(mockPreview);
    });

    it('should return null on error', async () => {
      const promise = firstValueFrom(service.getPreview('https://error.com'));

      const req = httpMock.expectOne((r) => r.url.includes('/api/posts/card'));
      req.flush('Error', { status: 500, statusText: 'Server Error' });

      const result = await promise;
      expect(result).toBeNull();
    });

    it('should cache failed requests as null', () => {
      const url = 'https://cached-error.com';

      service.getPreview(url).subscribe();
      service.getPreview(url).subscribe();

      const requests = httpMock.match((r) => r.url.includes('/api/posts/card'));
      expect(requests.length).toBe(1);
      requests[0].flush('Error', { status: 500, statusText: 'Server Error' });
    });
  });

  describe('extractUrls', () => {
    it('should extract http and https URLs from HTML', () => {
      const html = `
        <p>Check out <a href="https://example.com">this link</a> and 
        <a href="http://another.com/page">this one</a></p>
      `;
      const urls = service.extractUrls(html);
      expect(urls).toEqual(['https://example.com', 'http://another.com/page']);
    });

    it('should exclude hashtag links', () => {
      const html = `
        <p><a class="hashtag" href="https://mastodon.social/tags/test">#test</a></p>
        <p><a href="https://example.com">valid link</a></p>
      `;
      const urls = service.extractUrls(html);
      expect(urls).toEqual(['https://example.com']);
    });

    it('should exclude mention links', () => {
      const html = `
        <p><a class="mention" href="https://mastodon.social/@user">@user</a></p>
        <p><a href="https://example.com">valid link</a></p>
      `;
      const urls = service.extractUrls(html);
      expect(urls).toEqual(['https://example.com']);
    });

    it('should exclude links from blocked domains', () => {
      const html = `
        <p><a href="https://mastodon.social/@user">profile</a></p>
        <p><a href="https://appdot.net/something">appdot</a></p>
        <p><a href="https://example.com">valid link</a></p>
      `;
      const urls = service.extractUrls(html);
      expect(urls).toEqual(['https://example.com']);
    });

    it('should exclude non-http URLs', () => {
      const html = `
        <p><a href="mailto:test@example.com">email</a></p>
        <p><a href="javascript:void(0)">js</a></p>
        <p><a href="ftp://files.example.com">ftp</a></p>
        <p><a href="https://example.com">valid link</a></p>
      `;
      const urls = service.extractUrls(html);
      expect(urls).toEqual(['https://example.com']);
    });

    it('should remove duplicate URLs', () => {
      const html = `
        <p><a href="https://example.com">link 1</a></p>
        <p><a href="https://example.com">link 2</a></p>
        <p><a href="https://example.com">link 3</a></p>
      `;
      const urls = service.extractUrls(html);
      expect(urls).toEqual(['https://example.com']);
    });

    it('should return empty array for HTML with no links', () => {
      const html = '<p>Just some text without links</p>';
      const urls = service.extractUrls(html);
      expect(urls).toEqual([]);
    });

    it('should return empty array for empty string', () => {
      const urls = service.extractUrls('');
      expect(urls).toEqual([]);
    });

    it('should handle links with both hashtag and other classes', () => {
      const html = `
        <p><a class="link hashtag" href="https://example.com/tag">#tag</a></p>
        <p><a class="external mention" href="https://example.com/@user">@user</a></p>
        <p><a class="external" href="https://valid.com">valid</a></p>
      `;
      const urls = service.extractUrls(html);
      expect(urls).toEqual(['https://valid.com']);
    });

    it('should handle complex HTML with nested elements', () => {
      const html = `
        <div>
          <p>Check this out:</p>
          <blockquote>
            <a href="https://example.com/article">
              <span>Article Title</span>
            </a>
          </blockquote>
        </div>
      `;
      const urls = service.extractUrls(html);
      expect(urls).toEqual(['https://example.com/article']);
    });

    it('should preserve URL query parameters', () => {
      const html = `
        <a href="https://example.com/page?param=value&other=123">link</a>
      `;
      const urls = service.extractUrls(html);
      expect(urls).toEqual(['https://example.com/page?param=value&other=123']);
    });

    it('should handle links without href attribute gracefully', () => {
      const html = `
        <p><a name="anchor">no href</a></p>
        <p><a href="https://example.com">valid link</a></p>
      `;
      const urls = service.extractUrls(html);
      expect(urls).toEqual(['https://example.com']);
    });
  });
});
