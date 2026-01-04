import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import dotenv
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import and_, desc, or_, select

from mastodon_is_my_blog.masto_client import client
from mastodon_is_my_blog.store import (
    CachedPost,
    async_session,
    get_last_sync,
    get_token,
    init_db,
    set_token,
    update_last_sync,
)

dotenv.load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize database
    await init_db()
    yield
    # Shutdown: cleanup if needed


app = FastAPI(lifespan=lifespan)

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


# --- Pydantic Models ---
class PostIn(BaseModel):
    status: str
    visibility: str = "public"
    spoiler_text: str | None = None


class EditIn(BaseModel):
    status: str
    spoiler_text: str | None = None


# --- Helper: Sync Engine ---
def analyze_content(html: str, media_attachments: list) -> tuple[bool, bool]:
    soup = BeautifulSoup(html, "html.parser")
    has_video = False
    has_media = len(media_attachments) > 0

    # Check for youtube/vimeo links if no native video
    if not has_media:
        if soup.find("iframe"):
            has_video = True

    # Check media types
    for m in media_attachments:
        if m["type"] in ["video", "gifv"]:
            has_video = True
        if m["type"] == "image":
            has_media = True

    return has_media, has_video


async def sync_timeline(force: bool = False) -> dict:
    """Syncs posts from Mastodon to SQLite if stale or forced"""
    last_run = await get_last_sync()

    # 24 Hour check
    if not force and last_run and (datetime.utcnow() - last_run) < timedelta(hours=24):
        return {"status": "skipped", "reason": "synced_recently"}

    token = await get_token()
    if not token:
        raise HTTPException(401, "Not connected to Mastodon")

    m = client(token)
    me = m.account_verify_credentials()
    my_acct = me["acct"]

    # Fetch posts (limit 100 for sync)
    statuses = m.account_statuses(
        me["id"], limit=40, exclude_reblogs=False, exclude_replies=False
    )

    async with async_session() as session:
        for s in statuses:
            # Determine flags
            is_reblog = s["reblog"] is not None
            actual_status = s["reblog"] if is_reblog else s

            # Check if this is a reply to someone else
            is_reply = (
                s.get("in_reply_to_id") is not None
                and s.get("in_reply_to_account_id") != me["id"]
            )

            has_media, has_video = analyze_content(
                actual_status["content"], actual_status["media_attachments"]
            )

            # Serialize media attachments
            import json

            media_json = (
                json.dumps(actual_status["media_attachments"])
                if actual_status["media_attachments"]
                else None
            )

            # Create or Update
            stmt = select(CachedPost).where(CachedPost.id == str(s["id"]))
            existing = (await session.execute(stmt)).scalar_one_or_none()

            if not existing:
                new_post = CachedPost(
                    id=str(s["id"]),
                    content=actual_status["content"],
                    created_at=s["created_at"],
                    visibility=s["visibility"],
                    author_acct=actual_status["account"]["acct"],
                    is_reblog=is_reblog,
                    is_reply=is_reply,
                    has_media=has_media,
                    has_video=has_video,
                    replies_count=s["replies_count"],
                    media_attachments=media_json,
                )
                session.add(new_post)
            else:
                # Update existing
                existing.content = actual_status["content"]
                existing.replies_count = s["replies_count"]
                existing.is_reply = is_reply
                existing.media_attachments = media_json

        await session.commit()

    await update_last_sync()
    return {"status": "success", "count": len(statuses)}


# --- Public Endpoints (Read Only / Cached) ---


@app.get("/api/public/posts")
async def get_public_posts(
    filter_type: str = Query("all", enum=["all", "discussions", "pictures", "videos"])
) -> list[dict]:
    """Get posts from Cache"""
    async with async_session() as session:
        query = select(CachedPost).order_by(desc(CachedPost.created_at))

        if filter_type == "all":
            # Only root posts (not reblogs, not replies)
            query = query.where(
                and_(CachedPost.is_reblog == False, CachedPost.is_reply == False)
            )
        elif filter_type == "discussions":
            # Only replies to others
            query = query.where(CachedPost.is_reply == True)
        elif filter_type == "pictures":
            query = query.where(CachedPost.has_media == True)
        elif filter_type == "videos":
            query = query.where(CachedPost.has_video == True)

        result = await session.execute(query)
        posts = result.scalars().all()

        # Convert to dicts and parse media_attachments
        import json

        output = []
        for p in posts:
            post_dict = {
                "id": p.id,
                "content": p.content,
                "created_at": p.created_at.isoformat(),
                "visibility": p.visibility,
                "author_acct": p.author_acct,
                "is_reblog": p.is_reblog,
                "is_reply": p.is_reply,
                "has_media": p.has_media,
                "has_video": p.has_video,
                "replies_count": p.replies_count,
                "media_attachments": (
                    json.loads(p.media_attachments) if p.media_attachments else []
                ),
            }
            output.append(post_dict)

        return output


@app.get("/api/public/posts/{id}")
async def get_public_post_detail(id: str) -> dict:
    # Try cache first
    async with async_session() as session:
        res = await session.execute(select(CachedPost).where(CachedPost.id == id))
        post = res.scalar_one_or_none()

    # If not in cache or we want live comments, we might fetch live
    # But for speed, return cached post, let frontend fetch comments live
    if not post:
        raise HTTPException(404, "Post not found in cache")

    import json

    return {
        "id": post.id,
        "content": post.content,
        "created_at": post.created_at.isoformat(),
        "visibility": post.visibility,
        "author_acct": post.author_acct,
        "is_reblog": post.is_reblog,
        "is_reply": post.is_reply,
        "has_media": post.has_media,
        "has_video": post.has_video,
        "replies_count": post.replies_count,
        "media_attachments": (
            json.loads(post.media_attachments) if post.media_attachments else []
        ),
    }


@app.get("/api/public/posts/{id}/comments")
async def get_live_comments(id: str) -> dict:
    """Comments are fetched live to ensure freshness"""
    token = await get_token()  # Uses env token if DB token missing
    if not token:
        return {"descendants": []}

    try:
        m = client(token)
        context = m.status_context(id)
        return context
    except:
        return {"descendants": []}


# --- Admin/Auth Endpoints ---


@app.post("/api/admin/sync")
async def trigger_sync(force: bool = True) -> dict:
    return await sync_timeline(force=force)


@app.get("/api/admin/status")
async def admin_status() -> dict:
    token = await get_token()
    last_sync = await get_last_sync()
    return {
        "connected": token is not None,
        "last_sync": last_sync.isoformat() if last_sync else None,
    }


@app.post("/api/posts")
async def create_post(payload: PostIn):
    token = await get_token()
    if not token:
        raise HTTPException(401, "Not connected")
    m = client(token)
    if not payload.status.strip():
        raise HTTPException(400, "Empty post")
    resp = m.status_post(
        status=payload.status,
        visibility=payload.visibility,
        spoiler_text=payload.spoiler_text,
    )
    # Trigger immediate sync
    await sync_timeline(force=True)
    return resp


# (Keep /auth/login, /auth/callback, /api/me from previous code)
# ... Insert previous auth code here ...
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
    # Trigger initial sync on login
    await sync_timeline(force=True)
    return RedirectResponse(url=f"{frontend_url}/#/admin")


@app.get("/api/me")
async def me():
    token = await get_token()
    if not token:
        raise HTTPException(401, "Not connected")
    m = client(token)
    return m.account_verify_credentials()


@app.get("/api/posts")
async def posts(limit: int = 20):
    token = await get_token()
    if not token:
        raise HTTPException(401, "Not connected")
    m = client(token)
    me = m.account_verify_credentials()
    return m.account_statuses(me["id"], limit=limit, exclude_reblogs=True)


@app.get("/api/posts/{status_id}")
async def get_post(status_id: str):
    token = await get_token()
    if not token:
        raise HTTPException(401, "Not connected")
    return client(token).status(status_id)


@app.get("/api/posts/{status_id}/comments")
async def comments(status_id: str):
    token = await get_token()
    if not token:
        raise HTTPException(401, "Not connected")
    return client(token).status_context(status_id)


@app.get("/api/posts/{status_id}/source")
async def source(status_id: str):
    token = await get_token()
    if not token:
        raise HTTPException(401, "Not connected")
    return client(token).status_source(status_id)


@app.post("/api/posts/{status_id}/edit")
async def edit(status_id: str, payload: EditIn):
    token = await get_token()
    if not token:
        raise HTTPException(401, "Not connected")
    m = client(token)
    if not payload.status.strip():
        raise HTTPException(400, "Empty post")

    return m.status_update(
        status_id,
        status=payload.status,
        spoiler_text=payload.spoiler_text,
    )
