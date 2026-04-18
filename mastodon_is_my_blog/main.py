# mastodon_is_my_blog/main.py
import logging
import os
from contextlib import asynccontextmanager

import dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from mastodon_is_my_blog.identity_verifier import verify_all_identities
from mastodon_is_my_blog.link_previews import close_http_client, init_http_client
from mastodon_is_my_blog.mastodon_apis.masto_client import get_default_client
from mastodon_is_my_blog.queries import (
    sync_accounts_friends_followers,
    sync_user_timeline,
)
from mastodon_is_my_blog import duck
from mastodon_is_my_blog.routes import (
    accounts,
    admin,
    analytics,
    content_hub,
    peeps,
    posts,
    writing,
)
from mastodon_is_my_blog.static_files import get_static_dir
from mastodon_is_my_blog.utils.perf import performance_middleware
from mastodon_is_my_blog.store import (
    get_or_create_default_meta_account,
    get_token,
    init_db,
    set_token,
    sync_configured_identities,
)

logger = logging.getLogger(__name__)
logging.basicConfig()
logging.getLogger("mastodon_is_my_blog").setLevel(logging.INFO)

dotenv.load_dotenv()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Startup: Initialize database
    await init_db()
    # Ensure default user exists for local dev
    await get_or_create_default_meta_account()
    # Sync configured identities from persistent config and env
    await sync_configured_identities()

    # Verify all identities (updates acct/account_id from API)
    await verify_all_identities()

    # Initialize shared httpx client for link previews
    init_http_client()

    # Open DuckDB analytics connection, attached read-only to the SQLite file
    duck.startup()

    yield

    # Shutdown: close shared httpx client
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
app.include_router(content_hub.router)
app.include_router(peeps.router)
app.include_router(posts.router)
app.include_router(writing.router)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",
        "http://localhost:8080",
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:4200",
        "http://127.0.0.1:8080",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/status")
async def status() -> dict:
    return {"status": "up"}


@app.get("/auth/login")
async def login():
    """Initiate OAuth login flow"""
    m = await get_default_client()
    redirect_uri = f"{os.environ['APP_BASE_URL']}/auth/callback"

    # Generate authorization URL
    auth_url = m.auth_request_url(redirect_uris=redirect_uri, scopes=["read", "write"])

    return RedirectResponse(url=auth_url)


@app.get("/auth/callback")
async def callback(code: str):
    m = await get_default_client()
    redirect_uri = f"{os.environ['APP_BASE_URL']}/auth/callback"
    access_token = m.log_in(
        code=code, redirect_uri=redirect_uri, scopes=["read", "write"]
    )
    await set_token(access_token)
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:4200")
    await sync_accounts_friends_followers()
    await sync_user_timeline(force=True)
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
