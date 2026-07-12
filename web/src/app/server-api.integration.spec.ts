// Integration tests: exercise the REAL FastAPI backend over HTTP — no mocks.
// These verify the API contract the Angular app depends on (shapes and params
// that unit tests can only assume). They require a running dev server:
//
//   make dev-backend        (or: uv run python -m mastodon_is_my_blog)
//
// Run with:  npm run test:integration   (or: make test-frontend-integration)
// If the server is not reachable, every test here is skipped, not failed.
//
// Only read-only endpoints are used, so running against your live app.db is safe.

const env = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env;
const API_BASE = env?.['MIMB_API_BASE'] ?? 'http://localhost:8100';

let serverUp = false;
let identityId: number | null = null;

// GET only — these tests run against a live app.db and must never mutate it.
async function getJson(
  path: string,
  timeoutMs = 10_000,
): Promise<{ status: number; body: unknown }> {
  const res = await fetch(`${API_BASE}${path}`, { signal: AbortSignal.timeout(timeoutMs) });
  return { status: res.status, body: await res.json() };
}

beforeAll(async () => {
  try {
    const res = await fetch(`${API_BASE}/api/status`, { signal: AbortSignal.timeout(2_000) });
    serverUp = res.ok;
  } catch {
    serverUp = false;
  }
  if (!serverUp) {
    console.warn(
      `[integration] backend not reachable at ${API_BASE} — skipping live API tests. ` +
        'Start it with `make dev-backend`.',
    );
    return;
  }
  const { body } = await getJson('/api/admin/identities');
  if (Array.isArray(body) && body.length > 0) {
    identityId = (body[0] as { id: number }).id;
  }
});

describe('live backend API contract', () => {
  it('reports server status', async (ctx) => {
    if (!serverUp) return ctx.skip();

    const { status } = await getJson('/api/status');
    expect(status).toBe(200);
  });

  it('lists identities as an array', async (ctx) => {
    if (!serverUp) return ctx.skip();

    const { status, body } = await getJson('/api/admin/identities');
    expect(status).toBe(200);
    expect(Array.isArray(body)).toBe(true);
  });

  it('serves the posts feed in FeedPage shape', async (ctx) => {
    if (!serverUp || identityId === null) return ctx.skip();

    const { status, body } = await getJson(
      `/api/posts?identity_id=${identityId}&filter_type=all&limit=5`,
    );
    expect(status).toBe(200);
    const page = body as { items: unknown[]; next_cursor: string | null };
    expect(Array.isArray(page.items)).toBe(true);
    expect('next_cursor' in page).toBe(true);
  });

  it('serves storms in root/branches shape', async (ctx) => {
    if (!serverUp || identityId === null) return ctx.skip();

    const { status, body } = await getJson(`/api/posts/storms?identity_id=${identityId}&limit=3`);
    expect(status).toBe(200);
    const page = body as { items: { root?: unknown; branches?: unknown[] }[] };
    expect(Array.isArray(page.items)).toBe(true);
    for (const storm of page.items) {
      expect(storm.root).toBeDefined();
      expect(Array.isArray(storm.branches)).toBe(true);
    }
  });

  it('lists content hub groups', async (ctx) => {
    if (!serverUp || identityId === null) return ctx.skip();

    const { status, body } = await getJson(`/api/content-hub/groups?identity_id=${identityId}`);
    expect(status).toBe(200);
    expect(Array.isArray(body)).toBe(true);
  });

  it('serves group posts with the fields the hub tabs render', async (ctx) => {
    if (!serverUp || identityId === null) return ctx.skip();
    const { body: groups } = await getJson(`/api/content-hub/groups?identity_id=${identityId}`);
    const group = (groups as { id: number }[])[0];
    if (!group) return ctx.skip();

    const { status, body } = await getJson(
      `/api/content-hub/groups/${group.id}/posts?identity_id=${identityId}&tab=text&limit=5`,
    );
    expect(status).toBe(200);
    const resp = body as {
      items: { id: string; created_at: string; author_acct: string; counts: unknown }[];
      next_cursor: string | null;
      stale: boolean;
      group: { id: number; name: string };
    };
    expect(Array.isArray(resp.items)).toBe(true);
    expect(resp.group.id).toBe(group.id);
    for (const post of resp.items) {
      expect(typeof post.id).toBe('string');
      expect(typeof post.created_at).toBe('string');
      expect(post.counts).toMatchObject({});
    }
  });

  it('never returns a pagination cursor for shuffled group posts', async (ctx) => {
    if (!serverUp || identityId === null) return ctx.skip();
    const { body: groups } = await getJson(`/api/content-hub/groups?identity_id=${identityId}`);
    const group = (groups as { id: number }[])[0];
    if (!group) return ctx.skip();

    const { status, body } = await getJson(
      `/api/content-hub/groups/${group.id}/posts?identity_id=${identityId}&tab=text&limit=5&shuffle=true`,
    );
    expect(status).toBe(200);
    expect((body as { next_cursor: string | null }).next_cursor).toBeNull();
  });

  it('serves forum threads with facets', async (ctx) => {
    if (!serverUp || identityId === null) return ctx.skip();

    // KNOWN PERF BUG: thread aggregation takes ~3 minutes against a real
    // app.db (measured 166s, warm and cold). The Forum page hangs on
    // "Loading discussions…" the whole time. Timeout is set high so this
    // test documents the contract; tighten it once the endpoint is fixed.
    const { status, body } = await getJson(
      `/api/forum/threads?identity_id=${identityId}&top_filter=recent&limit=5`,
      240_000,
    );
    expect(status).toBe(200);
    const resp = body as { items: unknown[]; facets: Record<string, unknown[]> };
    expect(Array.isArray(resp.items)).toBe(true);
    expect(Array.isArray(resp.facets['hashtags'])).toBe(true);
    expect(Array.isArray(resp.facets['uncommon_words'])).toBe(true);
    expect(Array.isArray(resp.facets['root_instances'])).toBe(true);
  }, 250_000);
});
