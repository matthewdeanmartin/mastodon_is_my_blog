# mastodon_is_my_blog/main.py
import logging
import os
from contextlib import asynccontextmanager

import dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from mastodon_is_my_blog.identity_verifier import verify_all_identities
from mastodon_is_my_blog.mastodon_apis.masto_client import (
    client,
    get_default_client,
)
from mastodon_is_my_blog.queries import (
    sync_accounts_friends_followers,
    sync_user_timeline,
)
from mastodon_is_my_blog.routes import accounts, admin, posts, writing
from mastodon_is_my_blog.store import (
    bootstrap_identities_from_env,
    get_or_create_default_meta_account,
    get_token,
    init_db,
    set_token,
)

logger = logging.getLogger(__name__)
logging.basicConfig()
logging.getLogger("mastodon_is_my_blog").setLevel(logging.INFO)

dotenv.load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize database
    await init_db()
    # Ensure default user exists for local dev
    await get_or_create_default_meta_account()
    # Bootstrap identities from .env
    await bootstrap_identities_from_env()

    # Verify all identities (updates acct/account_id from API)
    await verify_all_identities()
    yield
    # Shutdown: cleanup if needed


app = FastAPI(lifespan=lifespan)

app.include_router(accounts.router)
app.include_router(admin.router)
app.include_router(posts.router)
app.include_router(writing.router)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",
        "http://localhost:8080",
        "http://localhost:3000",
        "http://127.0.0.1:4200",
        "http://127.0.0.1:8080",
        "http://127.0.0.1:3000",
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
    m = client()
    redirect_uri = f"{os.environ['APP_BASE_URL']}/auth/callback"

    # Generate authorization URL
    auth_url = m.auth_request_url(redirect_uris=redirect_uri, scopes=["read", "write"])

    return RedirectResponse(url=auth_url)


@app.get("/auth/callback")
async def callback(code: str):
    m = client()
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
