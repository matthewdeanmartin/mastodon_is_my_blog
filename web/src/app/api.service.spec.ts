import { TestBed } from '@angular/core/testing';
import { HttpClientTestingModule, HttpTestingController } from '@angular/common/http/testing';
import { ApiService } from './api.service';
import { take, firstValueFrom } from 'rxjs';

describe('ApiService', () => {
  let service: ApiService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule],
      providers: [ApiService],
    });
    service = TestBed.inject(ApiService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  describe('Meta Account / Auth', () => {
    it('should start with null meta account id', async () => {
      const id = await firstValueFrom(service.metaId$.pipe(take(1)));
      expect(id).toBeNull();
    });

    it('should set and get meta account id', async () => {
      service.setMetaAccountId('test-account-123');

      expect(service.getMetaAccountId()).toBe('test-account-123');

      const id = await firstValueFrom(service.metaId$.pipe(take(1)));
      expect(id).toBe('test-account-123');
    });

    it('should emit new value when meta account id changes', async () => {
      const values: (string | null)[] = [];
      const subscription = service.metaId$.subscribe((id) => values.push(id));

      service.setMetaAccountId('account-1');
      service.setMetaAccountId('account-2');
      subscription.unsubscribe();

      expect(values).toEqual([null, 'account-1', 'account-2']);
    });

    it('should clear storage on logout', async () => {
      service.setMetaAccountId('test-account');
      service.setIdentityId(42);

      service.logout();

      expect(service.getMetaAccountId()).toBeNull();
      expect(service.getStoredIdentityId()).toBeNull();

      const id = await firstValueFrom(service.metaId$.pipe(take(1)));
      expect(id).toBeNull();
    });
  });

  describe('Identity State', () => {
    it('should start with null identity id', async () => {
      const id = await firstValueFrom(service.identityId$.pipe(take(1)));
      expect(id).toBeNull();
    });

    it('should set and get identity id', async () => {
      service.setIdentityId(123);

      expect(service.getStoredIdentityId()).toBe(123);
      expect(service.getCurrentIdentityId()).toBe(123);

      const id = await firstValueFrom(service.identityId$.pipe(take(1)));
      expect(id).toBe(123);
    });

    it('should parse stored identity id as number', () => {
      localStorage.setItem('mastodon_identity_id', '456');
      const newService = TestBed.inject(ApiService);
      expect(newService.getStoredIdentityId()).toBe(456);
    });
  });

  describe('HTTP Headers', () => {
    it('should include X-Meta-Account-ID header when meta account is set', () => {
      service.setMetaAccountId('meta-123');
      service.getPublicPosts(1).subscribe();

      const req = httpMock.expectOne((r) => r.url.includes('/api/posts'));
      expect(req.request.headers.get('X-Meta-Account-ID')).toBe('meta-123');
      req.flush([]);
    });

    it('should not include X-Meta-Account-ID header when meta account is not set', () => {
      service.getPublicPosts(1).subscribe();

      const req = httpMock.expectOne((r) => r.url.includes('/api/posts'));
      expect(req.request.headers.get('X-Meta-Account-ID')).toBeNull();
      req.flush([]);
    });
  });

  describe('Public Read Methods', () => {
    it('should get public posts with identity_id and filter params', () => {
      service.getPublicPosts(42, 'unread', 'user@domain').subscribe();

      const req = httpMock.expectOne((r) => r.url.includes('/api/posts'));
      expect(req.request.params.get('identity_id')).toBe('42');
      expect(req.request.params.get('filter_type')).toBe('unread');
      expect(req.request.params.get('user')).toBe('user@domain');
      req.flush([]);
    });

    it('should get storms with identity_id param', () => {
      service.getStorms(42, 'user@domain').subscribe();

      const req = httpMock.expectOne((r) => r.url.includes('/api/posts/storms'));
      expect(req.request.params.get('identity_id')).toBe('42');
      expect(req.request.params.get('user')).toBe('user@domain');
      req.flush([]);
    });

    it('should get shorts with identity_id param', () => {
      service.getShorts(42).subscribe();

      const req = httpMock.expectOne((r) => r.url.includes('/api/posts/shorts'));
      expect(req.request.params.get('identity_id')).toBe('42');
      req.flush([]);
    });

    it('should get blog roll with identity_id and filter params', () => {
      service.getBlogRoll(42, 'active').subscribe();

      const req = httpMock.expectOne((r) => r.url.includes('/api/accounts/blogroll'));
      expect(req.request.params.get('identity_id')).toBe('42');
      expect(req.request.params.get('filter_type')).toBe('active');
      req.flush([]);
    });

    it('should get counts with identity_id param', () => {
      service.getCounts(42, 'user@domain').subscribe();

      const req = httpMock.expectOne((r) => r.url.includes('/api/posts/counts'));
      expect(req.request.params.get('identity_id')).toBe('42');
      expect(req.request.params.get('user')).toBe('user@domain');
      req.flush({});
    });

    it('should get account info with identity_id param', () => {
      service.getAccountInfo('user@domain', 42).subscribe();

      const req = httpMock.expectOne((r) => r.url.includes('/api/accounts/user@domain'));
      expect(req.request.params.get('identity_id')).toBe('42');
      req.flush({});
    });

    it('should get post context with optional identity_id', () => {
      service.getPostContext('post-123', 42).subscribe();

      const req = httpMock.expectOne((r) => r.url.includes('/api/posts/post-123/context'));
      expect(req.request.params.get('identity_id')).toBe('42');
      req.flush({});
    });

    it('should get post context without identity_id', () => {
      service.getPostContext('post-123').subscribe();

      const req = httpMock.expectOne((r) => r.url.includes('/api/posts/post-123/context'));
      expect(req.request.params.get('identity_id')).toBeNull();
      req.flush({});
    });
  });

  describe('Sync Account', () => {
    it('should sync account and call correct endpoint', () => {
      service.syncAccount('user@domain', 42).subscribe();

      const req = httpMock.expectOne((r) => r.url.includes('/api/accounts/user@domain/sync'));
      expect(req.request.params.get('identity_id')).toBe('42');
      req.flush({});
    });

    it('should emit refreshNeeded$ after sync', async () => {
      const refreshPromise = firstValueFrom(service.refreshNeeded$);

      service.syncAccount('user@domain', 42).subscribe();
      const req = httpMock.expectOne((r) => r.url.includes('/api/accounts/user@domain/sync'));
      req.flush({});

      await refreshPromise;
    });
  });

  describe('syncAccountDedup', () => {
    it('should deduplicate concurrent sync requests for same account', () => {
      const req1$ = service.syncAccountDedup('user@domain', 42);
      const req2$ = service.syncAccountDedup('user@domain', 42);

      req1$.subscribe();
      req2$.subscribe();

      const requests = httpMock.match((r) => r.url.includes('/api/accounts/user@domain/sync'));
      expect(requests.length).toBe(1);
      requests[0].flush({});
    });

    it('should allow different accounts to sync concurrently', () => {
      service.syncAccountDedup('user1@domain', 42).subscribe();
      service.syncAccountDedup('user2@domain', 42).subscribe();

      const requests = httpMock.match((r) => r.url.includes('/sync'));
      expect(requests.length).toBe(2);
      requests.forEach((r) => r.flush({}));
    });
  });

  describe('Admin / Write Methods', () => {
    it('should trigger sync with force param', () => {
      service.triggerSync(true).subscribe();

      const req = httpMock.expectOne((r) => r.url.includes('/api/admin/sync'));
      expect(req.request.url).toContain('force=true');
      req.flush({});
    });

    it('should create post with status and visibility', () => {
      service.createPost('Hello World').subscribe();

      const req = httpMock.expectOne((r) => r.url.includes('/api/posts') && r.method === 'POST');
      expect(req.request.body).toEqual({ status: 'Hello World', visibility: 'public' });
      req.flush({});
    });

    it('should edit post with status', () => {
      service.editPost('post-123', 'Updated content').subscribe();

      const req = httpMock.expectOne((r) => r.url.includes('/api/posts/post-123/edit'));
      expect(req.request.body).toEqual({ status: 'Updated content' });
      req.flush({});
    });
  });

  describe('Seen Posts', () => {
    it('should mark post as seen', () => {
      service.markPostSeen('post-123').subscribe();

      const req = httpMock.expectOne((r) => r.url.includes('/api/posts/post-123/read'));
      expect(req.request.method).toBe('POST');
      req.flush({});
    });

    it('should mark multiple posts as seen', () => {
      service.markPostsSeen(['post-1', 'post-2', 'post-3']).subscribe();

      const req = httpMock.expectOne((r) => r.url.includes('/api/posts/read'));
      expect(req.request.body).toEqual(['post-1', 'post-2', 'post-3']);
      req.flush({});
    });

    it('should get seen posts', () => {
      service.getSeenPosts(['post-1', 'post-2']).subscribe();

      const req = httpMock.expectOne((r) => r.url.includes('/api/posts/seen'));
      expect(req.request.params.get('ids')).toBe('post-1,post-2');
      req.flush({ seen: ['post-1'] });
    });

    it('should get unread count', () => {
      service.getUnreadCount(42).subscribe();

      const req = httpMock.expectOne((r) => r.url.includes('/api/posts/unread-count'));
      expect(req.request.params.get('identity_id')).toBe('42');
      req.flush({ unread_count: 5 });
    });
  });

  describe('Error Handling', () => {
    it('should propagate HTTP errors', async () => {
      const promise = firstValueFrom(service.getPublicPosts(1));

      const req = httpMock.expectOne((r) => r.url.includes('/api/posts'));
      req.flush('Not found', { status: 404, statusText: 'Not Found' });

      try {
        await promise;
        expect.fail('Should have thrown');
      } catch (err: any) {
        expect(err.status).toBe(404);
      }
    });
  });

  describe('Health Check', () => {
    it('should verify health check observable exists', () => {
      expect(service.serverDown$).toBeDefined();
    });
  });

  describe('Login URL', () => {
    it('should return login URL', () => {
      expect(service.loginUrl()).toBe('http://localhost:8000/auth/login');
    });
  });

  describe('Other Methods', () => {
    it('should get identities', () => {
      service.getIdentities().subscribe();

      const req = httpMock.expectOne((r) => r.url.includes('/api/admin/identities'));
      req.flush([]);
    });

    it('should get admin status', () => {
      service.getAdminStatus().subscribe();

      const req = httpMock.expectOne((r) => r.url.includes('/api/admin/status'));
      req.flush({ connected: true, last_sync: '', current_user: null });
    });

    it('should call me endpoint', () => {
      service.me().subscribe();

      const req = httpMock.expectOne((r) => r.url.includes('/api/me'));
      req.flush({});
    });

    it('should get public post by id', () => {
      service.getPublicPost('post-123').subscribe();

      const req = httpMock.expectOne((r) => r.url.includes('/api/posts/post-123'));
      req.flush({});
    });

    it('should get post by id', () => {
      service.getPost('post-123').subscribe();

      const req = httpMock.expectOne((r) => r.url.includes('/api/posts/post-123'));
      req.flush({});
    });

    it('should get analytics', () => {
      service.getAnalytics().subscribe();

      const req = httpMock.expectOne((r) => r.url.includes('/api/posts/analytics'));
      req.flush({});
    });
  });
});
