# mastodon_is_my_blog/main.py
import logging
import os
from contextlib import asynccontextmanager

import dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from mastodon_is_my_blog import duck
from mastodon_is_my_blog.db_log_handler import DbLogHandler
from mastodon_is_my_blog.identity_verifier import verify_all_identities
from mastodon_is_my_blog.link_previews import close_http_client, init_http_client
from mastodon_is_my_blog.mastodon_apis.masto_client import client, get_default_client
from mastodon_is_my_blog.queries import (
    get_current_meta_account,
    sync_accounts_friends_followers,
    sync_user_timeline,
)
from mastodon_is_my_blog.routes import (
    accounts,
    admin,
    analytics,
    content_hub,
    forum,
    new_friends,
    observability,
    peeps,
    posts,
    publish,
    writing,
)
from mastodon_is_my_blog.routes.admin import persist_identity
from mastodon_is_my_blog.static_files import get_static_dir
from mastodon_is_my_blog import tenancy
from mastodon_is_my_blog.store import (
    consume_oauth_pending_connection,
    get_meta_account_by_id,
    get_or_create_default_meta_account,
    get_token,
    init_db,
    sync_configured_identities,
)
from mastodon_is_my_blog.utils.perf import performance_middleware

logger = logging.getLogger(__name__)
logging.basicConfig()
_root = logging.getLogger("mastodon_is_my_blog")
_root.setLevel(logging.INFO)
_db_handler = DbLogHandler(level=logging.WARNING)
_root.addHandler(_db_handler)

dotenv.load_dotenv()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Startup: Initialize database
    await init_db()

    # Stamp a freshly-created DB at the Alembic head so future `alembic upgrade`
    # runs behave (create_all builds the full schema; see db_init). No-op if the
    # DB is already stamped. (Phase 2)
    from mastodon_is_my_blog.db_init import ensure_schema_stamped

    await ensure_schema_stamped()

    # Log the backend / location / schema-version banner (Phase 2).
    from mastodon_is_my_blog.schema_version import log_startup_banner

    await log_startup_banner()

    if tenancy.is_server_mode():
        # Hosted mode: fail fast on missing config. Tenants (MetaAccounts)
        # are created per authenticated session, not at startup, and the
        # keyring/accounts.json config paths are single-machine constructs
        # that must not be consulted here.
        tenancy.check_server_mode_env()
    else:
        # Single-user mode: ensure the default user exists and mirror
        # identities from persistent config and env
        await get_or_create_default_meta_account()
        await sync_configured_identities()

    # Verify all identities (updates acct/account_id from API)
    await verify_all_identities()

    # Initialize shared httpx client for link previews
    init_http_client()

    # Drain buffered error/API-call telemetry to the DB (any backend).
    from mastodon_is_my_blog import telemetry

    telemetry.start_flusher()

    # Open DuckDB analytics connection, attached read-only to the SQLite file
    duck.startup()

    # Load spaCy model off the event loop — it's a slow blocking import
    try:
        import asyncio

        from mastodon_is_my_blog.text_topics import load_spacy_model

        loop = asyncio.get_event_loop()
        app.state.nlp = await loop.run_in_executor(None, load_spacy_model)
        logger.info("spaCy en_core_web_sm loaded")
    except Exception:
        app.state.nlp = None
        logger.warning("spaCy model not available — forum topic facets disabled")

    yield

    # Shutdown: final telemetry flush, then close shared clients
    await telemetry.stop_flusher()
    await telemetry.flush()
    await close_http_client()
    duck.shutdown()


app = FastAPI(lifespan=lifespan)

app.middleware("http")(performance_middleware)


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


app.include_router(accounts.router)
app.include_router(admin.router)
app.include_router(analytics.router)
app.include_router(observability.router)
app.include_router(content_hub.router)
app.include_router(forum.router)
app.include_router(new_friends.router)
app.include_router(peeps.router)
app.include_router(posts.router)
app.include_router(publish.router)
app.include_router(publish.preview_router)
app.include_router(writing.posts_router)
app.include_router(writing.drafts_router)

if tenancy.is_server_mode():
    # Control-plane hand-off API (spec/paid_hosting/control_plane_handoff.md).
    # Never mounted in local mode, so self-hosted installs 404 on /internal/*.
    from mastodon_is_my_blog.routes import internal

    app.include_router(internal.router)

    # Published static blogs (blog_build.py): /blogs/tenant_{id}/. The blogs
    # themselves are public by design — that's the product. Per-tenant
    # subdomains/custom domains are a later phase in front of this same tree.
    from mastodon_is_my_blog.blog_build import blog_output_root

    blogs_root = blog_output_root()
    blogs_root.mkdir(parents=True, exist_ok=True)
    app.mount("/blogs", StaticFiles(directory=blogs_root, html=True), name="blogs")


# Add CORS middleware
def allowed_origins() -> list[str]:
    """Single-user mode allows local dev servers; server mode is locked to
    ALLOWED_ORIGINS (comma-separated), defaulting to APP_BASE_URL."""
    if tenancy.is_server_mode():
        configured = os.environ.get("ALLOWED_ORIGINS", "")
        origins = [origin.strip() for origin in configured.split(",") if origin.strip()]
        if not origins and os.environ.get("APP_BASE_URL"):
            origins = [os.environ["APP_BASE_URL"].rstrip("/")]
        return origins
    return [
        "http://localhost:4200",
        "http://localhost:8080",
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:4200",
        "http://127.0.0.1:8080",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",
    ]


app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/status")
async def status() -> dict:
    return {"status": "up"}


@app.get("/api/whoami")
async def whoami(request: Request) -> dict:
    """Who is signed in, and which tenant is this request scoped to?

    Server mode: echoes the mimb_session claims (email + tenant_id) so the UI
    can show "signed in as …" — on localhost/subdomains cookies are shared
    across the control-plane apps and the product server, so without this
    surface two accounts render identical pages and nobody can tell whose
    blog is whose. account_url points back at the mimb_co account page for
    "manage account / sign out".

    Local (self-hosted single-user) mode: there is no sign-in; everything is
    the 'default' account and the UI should not render an identity bar entry.
    """
    if tenancy.is_server_mode():
        cookie = request.cookies.get(tenancy.SESSION_COOKIE_NAME)
        if not cookie:
            raise HTTPException(401, "Not signed in")
        try:
            claims = tenancy.verify_session_token(cookie)
        except tenancy.SessionValidationError as exc:
            raise HTTPException(401, "Invalid or expired session") from exc
        # Same enabled gate as every data route (get_current_meta_account) —
        # otherwise a disabled tenant's UI still says "signed in" while every
        # other call 403s. This also lazily provisions, which is fine: the
        # control plane authenticated them.
        await get_current_meta_account(request)
        return {
            "mode": "server",
            "email": claims.email,
            "tenant_id": claims.tenant_id,
            "account_url": os.environ.get("ACCOUNT_PORTAL_URL", "http://localhost:8051").rstrip("/"),
        }
    return {"mode": "local", "email": None, "tenant_id": None, "account_url": None}


@app.get("/auth/callback")
async def callback(code: str, state: str):
    """
    Completes a dynamically-registered OAuth connection started by
    POST /api/admin/identities/oauth/start. Looks up the pending app
    credentials by `state`, exchanges the code, and persists the identity.
    """
    pending = await consume_oauth_pending_connection(state)
    if pending is None:
        raise HTTPException(400, "Unknown or expired OAuth state")

    redirect_uri = f"{os.environ['APP_BASE_URL']}/auth/callback"
    m = client(
        base_url=pending.base_url,
        client_id=pending.client_id,
        client_secret=pending.client_secret,
    )
    access_token = m.log_in(
        code=code,
        redirect_uri=redirect_uri,
        scopes=["read", "write"],
        # Same escape hatch as oauth/start: Mastodon.py rejects http OAuth
        # endpoints by default; plain http is legit for dev against
        # mastodon_mock (make dev-mock).
        allow_http=pending.base_url.startswith("http://"),
    )
    verified_me = m.account_verify_credentials()

    # Bind the identity to the tenant that STARTED the flow, not the default
    # account — pending.meta_account_id was set from the session at /oauth/start.
    meta = await get_meta_account_by_id(pending.meta_account_id)
    if meta is None:
        raise HTTPException(400, "Tenant for this OAuth flow no longer exists")
    await persist_identity(meta, pending.base_url, pending.client_id, pending.client_secret, access_token, verified_me)

    # In server mode the SPA is served by this very app, so the post-OAuth
    # landing defaults to APP_BASE_URL (required env there) — the :4200
    # default is the local-dev ng-serve split only.
    frontend_url = os.environ.get("FRONTEND_URL") or (os.environ["APP_BASE_URL"].rstrip("/") if tenancy.is_server_mode() else "http://localhost:4200")
    if not tenancy.is_server_mode():
        # Single-user mode: kick an inline first sync for instant gratification.
        await sync_accounts_friends_followers()
        await sync_user_timeline(force=True)
    else:
        # Server mode: same instant gratification, tenant-scoped and in the
        # background (a full first sync can take a minute; the redirect must
        # not wait). Without this every page is an empty state until the
        # control plane's next scheduled sync (sprint-05 testing).
        from mastodon_is_my_blog.queries import sync_all_identities
        from mastodon_is_my_blog.routes.internal import spawn_background

        async def first_sync_and_build() -> None:
            from mastodon_is_my_blog.blog_build import build_tenant_blog

            await sync_all_identities(meta, force=True)
            if meta.username.startswith("tenant_"):
                await build_tenant_blog(int(meta.username.removeprefix("tenant_")), meta.id)

        spawn_background(first_sync_and_build(), label=f"first-sync-{meta.username}")
    return RedirectResponse(url=f"{frontend_url}/#/admin")


@app.get("/api/me")
async def me():
    token = await get_token()
    if not token:
        raise HTTPException(401, "Not connected")
    m = await get_default_client()
    return m.account_verify_credentials()


# Serve compiled Angular SPA — must come after all API/auth routes
static_dir = get_static_dir()
if static_dir.exists():
    app.mount("/assets", StaticFiles(directory=static_dir), name="static-assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str) -> FileResponse:
        requested_path = (static_dir / full_path).resolve()
        try:
            requested_path.relative_to(static_dir.resolve())
        except ValueError:
            return FileResponse(str(static_dir / "index.html"))

        if full_path and requested_path.is_file():
            return FileResponse(str(requested_path))

        return FileResponse(str(static_dir / "index.html"))
