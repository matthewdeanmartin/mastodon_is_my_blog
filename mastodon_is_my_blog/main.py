import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import dotenv
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import and_, desc, func, or_, select

from mastodon_is_my_blog.masto_client import client
from mastodon_is_my_blog.store import (
    CachedAccount,
    CachedPost,
    async_session,
    get_last_sync,
    get_token,
    init_db,
    set_token,
    update_last_sync,
)

dotenv.load_dotenv()

# --- Configuration: Domain Filters ---
# Reasonably configurable lists of domains for filters
DOMAIN_CONFIG = {
    "video": {
        "youtube.com", "youtu.be", "vimeo.com", "twitch.tv", "dailymotion.com", "tiktok.com"
    },
    "picture": {
        "flickr.com", "imgur.com", "instagram.com", "500px.com", "deviantart.com"
    },
    "tech": {
        "github.com", "gitlab.com", "pypi.org", "npmjs.com", "stackoverflow.com", "huggingface.co"
    },
    "news": {
        "nytimes.com", "theguardian.com", "bbc.com", "bbc.co.uk", "cnn.com",
        "washingtonpost.com", "reuters.com", "aljazeera.com", "npr.org", "arstechnica.com"
    }
}


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


def to_naive_utc(dt: datetime | None) -> datetime | None:
    """
    Safely converts any datetime (Aware or Naive) to Naive UTC.
    This ensures we can always compare dates with SQLite data without crashing.
    """
    if dt is None:
        return None
    # If it has timezone info, convert to UTC and strip it
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    # If it's already naive, assume it's what we want
    return dt


# --- Helper: Content Analysis ---
def analyze_content_domains(html: str, media_attachments: list) -> dict:
    """
    Analyzes HTML content and attachments to determine content flags.
    Returns dict of boolean flags.
    """
    soup = BeautifulSoup(html, "html.parser")

    flags = {
        "has_media": len(media_attachments) > 0,
        "has_video": False,
        "has_news": False,
        "has_tech": False
    }

    # 1. Check Attachments
    for m in media_attachments:
        if m["type"] in ["video", "gifv", "audio"]:
            flags["has_video"] = True
        if m["type"] == "image":
            flags["has_media"] = True

    # 2. Check Links (<a> tags and <iframe>)
    if soup.find("iframe"):
        flags["has_video"] = True

    for link in soup.find_all("a", href=True):
        try:
            domain = urlparse(link["href"]).netloc.lower()
            # Remove 'www.' prefix if present for matching
            clean_domain = domain.replace("www.", "")

            # Check Video
            if any(d in clean_domain for d in DOMAIN_CONFIG["video"]):
                flags["has_video"] = True

            # Check Pictures (External)
            if any(d in clean_domain for d in DOMAIN_CONFIG["picture"]):
                flags["has_media"] = True  # Treat external image links as "has_media"

            # Check Tech
            if any(d in clean_domain for d in DOMAIN_CONFIG["tech"]):
                flags["has_tech"] = True

            # Check News
            if any(d in clean_domain for d in DOMAIN_CONFIG["news"]):
                flags["has_news"] = True

        except Exception:
            continue

    return flags


# --- Sync Engines ---

async def sync_accounts_friends_followers() -> None:
    """Syncs lists of following and followers."""
    token = await get_token()
    if not token: return
    m = client(token)
    me = m.account_verify_credentials()

    # Fetch lists (pagination logic simplified for brevity, assumes < 80 for demo)
    # BUG: will need to revisit this hard coded value
    following = m.account_following(me["id"], limit=80)
    followers = m.account_followers(me["id"], limit=80)

    async with async_session() as session:
        # Process Following
        for acc in following:
            stmt = select(CachedAccount).where(CachedAccount.id == str(acc["id"]))
            existing = (await session.execute(stmt)).scalar_one_or_none()

            if not existing:
                new_acc = CachedAccount(
                    id=str(acc["id"]), acct=acc["acct"], display_name=acc["display_name"],
                    avatar=acc["avatar"], url=acc["url"], is_following=True,
                    note=acc.get("note", "")
                )
                session.add(new_acc)
            else:
                existing.is_following = True
                existing.note = acc.get("note", "")

        # Process Followers
        for acc in followers:
            stmt = select(CachedAccount).where(CachedAccount.id == str(acc["id"]))
            existing = (await session.execute(stmt)).scalar_one_or_none()

            if not existing:
                new_acc = CachedAccount(
                    id=str(acc["id"]), acct=acc["acct"], display_name=acc["display_name"],
                    avatar=acc["avatar"], url=acc["url"], is_followed_by=True,
                    note=acc.get("note", "")
                )
                session.add(new_acc)
            else:
                existing.is_followed_by = True
                existing.note = acc.get("note", "")

        await session.commit()
    await update_last_sync("accounts")


async def sync_blog_roll_activity() -> None:
    """
    Fetches the Home Timeline to find who is active.
    Updates CachedAccount.last_status_at for the Blog Roll.
    """
    token = await get_token()
    if not token: return
    m = client(token)

    # Fetch Home Timeline (Active people I follow)
    home_statuses = m.timeline_home(limit=200)

    async with async_session() as session:
        for s in home_statuses:
            account_data = s["account"]
            # Find account in DB (should be there if we ran sync_accounts, but create if new)
            stmt = select(CachedAccount).where(CachedAccount.id == str(account_data["id"]))
            existing = (await session.execute(stmt)).scalar_one_or_none()

            # --- Convert to Naive UTC before comparing ---
            last_status_time = to_naive_utc(s["created_at"])

            if existing:
                # Update last active time if this post is newer
                # existing.last_status_at is Naive (from SQLite), last_status_time is now Naive.
                if not existing.last_status_at or last_status_time > existing.last_status_at:
                    existing.last_status_at = last_status_time
            else:
                # Discovered a new active person (maybe from a boost)
                new_acc = CachedAccount(
                    id=str(account_data["id"]),
                    acct=account_data["acct"],
                    display_name=account_data["display_name"],
                    avatar=account_data["avatar"],
                    url=account_data["url"],
                    last_status_at=last_status_time,
                    note=account_data.get("note", "")
                )
                session.add(new_acc)

        await session.commit()


async def sync_user_timeline(acct: str | None = None, acct_id: str | None = None, force: bool = False,
    cooldown_minutes: int = 15
    ) -> dict:
    """Syncs posts for a specific user. Defaults to Me."""
    sync_key = f"user_timeline_{acct or acct_id or 'me'}"
    last_run = await get_last_sync(sync_key)

    # Check custom cooldown
    if not force and last_run and (datetime.utcnow() - last_run) < timedelta(minutes=cooldown_minutes):
        return {"status": "skipped", "reason": "synced_recently"}

    token = await get_token()
    if not token: raise HTTPException(401, "Not connected")
    m = client(token)

    # Resolve the target account
    if acct:
        # Look up account by acct string (username@instance)
        try:
            search_result = m.account_search(acct, limit=1)
            if not search_result:
                raise HTTPException(404, f"Account {acct} not found")
            target_account = search_result[0]
            target_id = target_account["id"]
        except Exception as e:
            raise HTTPException(404, f"Could not find account {acct}: {str(e)}")
    elif acct_id:
        target_id = acct_id
        target_account = m.account(target_id)
    else:
        # Default to authenticated user
        target_account = m.account_verify_credentials()
        target_id = target_account["id"]

    # Cache the account info
    async with async_session() as session:
        stmt = select(CachedAccount).where(CachedAccount.id == str(target_id))
        existing_acc = (await session.execute(stmt)).scalar_one_or_none()

        if not existing_acc:
            new_acc = CachedAccount(
                id=str(target_id),
                acct=target_account["acct"],
                display_name=target_account["display_name"],
                avatar=target_account["avatar"],
                url=target_account["url"],
                note=target_account.get("note", "")
            )
            session.add(new_acc)
        else:
            existing_acc.display_name = target_account["display_name"]
            existing_acc.avatar = target_account["avatar"]
            existing_acc.note = target_account.get("note", "")

        await session.commit()

    # Fetch statuses
    statuses = m.account_statuses(target_id, limit=200)

    async with async_session() as session:
        for s in statuses:
            # Determine flags
            is_reblog = s["reblog"] is not None
            actual_status = s["reblog"] if is_reblog else s

            # Analyze flags
            flags = analyze_content_domains(
                actual_status["content"], actual_status["media_attachments"]
            )

            # Determine Reply Status
            # A post is a reply if it has in_reply_to_id AND it's not a self-thread (initially)
            # We store the raw IDs to reconstruct storms later
            in_reply_to_id = actual_status.get("in_reply_to_id")
            in_reply_to_account = actual_status.get("in_reply_to_account_id")

            is_reply_to_other = (
                    in_reply_to_id is not None and
                    str(in_reply_to_account) != str(actual_status["account"]["id"])
            )

            media_json = json.dumps(actual_status["media_attachments"]) if actual_status["media_attachments"] else None

            # FIX: Ensure creation date is naive UTC
            created_at_naive = to_naive_utc(s["created_at"])

            stmt = select(CachedPost).where(CachedPost.id == str(s["id"]))
            existing = (await session.execute(stmt)).scalar_one_or_none()

            post_data = {
                "content": actual_status["content"],
                "created_at": created_at_naive,
                "visibility": s["visibility"],
                "author_acct": actual_status["account"]["acct"],
                "author_id": str(actual_status["account"]["id"]),
                "is_reblog": is_reblog,
                "is_reply": is_reply_to_other,
                "in_reply_to_id": str(in_reply_to_id) if in_reply_to_id else None,
                "in_reply_to_account_id": str(in_reply_to_account) if in_reply_to_account else None,
                "has_media": flags["has_media"],
                "has_video": flags["has_video"],
                "has_news": flags["has_news"],
                "has_tech": flags["has_tech"],
                "replies_count": s["replies_count"],
                "reblogs_count": s["reblogs_count"],
                "favourites_count": s["favourites_count"],
                "media_attachments": media_json
            }

            if not existing:
                new_post = CachedPost(id=str(s["id"]), **post_data)
                session.add(new_post)
            else:
                for k, v in post_data.items():
                    setattr(existing, k, v)

        await session.commit()

    await update_last_sync(sync_key)
    return {"status": "success", "count": len(statuses)}


# --- Public Endpoints ---

@app.get("/api/public/accounts/blogroll")
async def get_blog_roll():
    """Returns active accounts discovered from the timeline."""
    async with async_session() as session:
        # Get accounts that have posted recently OR are friends
        query = (
            select(CachedAccount)
            .where(or_(CachedAccount.last_status_at != None, CachedAccount.is_following == True))
            .order_by(desc(CachedAccount.last_status_at))
            .limit(40)
        )
        res = await session.execute(query)
        accounts = res.scalars().all()

        return [
            {
                "id": a.id,
                "acct": a.acct,
                "display_name": a.display_name,
                "avatar": a.avatar,
                "url": a.url,
                "note": getattr(a, 'note', ''),
                "last_status_at": a.last_status_at.isoformat() if a.last_status_at else None
            }
            for a in accounts
        ]


@app.get("/api/public/accounts/{acct}")
async def get_account_info(acct: str):
    """Get cached account information by acct string."""
    async with async_session() as session:
        stmt = select(CachedAccount).where(CachedAccount.acct == acct)
        account = (await session.execute(stmt)).scalar_one_or_none()

        if not account:
            raise HTTPException(404, "Account not found in cache")

        return {
            "id": account.id,
            "acct": account.acct,
            "display_name": account.display_name,
            "avatar": account.avatar,
            "url": account.url,
            "note": account.note,
            "is_following": account.is_following,
            "is_followed_by": account.is_followed_by
        }


@app.post("/api/public/accounts/{acct}/sync")
async def sync_account(acct: str):
    """Sync a specific user's timeline."""
    result = await sync_user_timeline(acct=acct, force=True)
    return result


@app.get("/api/public/posts")
async def get_public_posts(
        user: str | None = None,
        filter_type: str = Query("all", enum=["all", "discussions", "pictures", "videos", "news", "software"])
) -> list[dict]:
    """
    Get posts with filters.
    User arg: filter by username (acct). If None, gets all synced posts (usually owner).
    """
    async with async_session() as session:
        query = select(CachedPost).order_by(desc(CachedPost.created_at))

        # Filter by User
        if user:
            query = query.where(CachedPost.author_acct == user)
        else:
            # Default to owner/verified credentials logic if we had multiple users synced
            # For this app, we return everything in DB if user not specified,
            # or we could default to the owner. Let's return all.
            pass

        # Apply Type Filters
        if filter_type == "all":
            # Show roots only (hide replies to others, keep self-threads)
            query = query.where(and_(CachedPost.is_reblog == False, CachedPost.is_reply == False))
        elif filter_type == "discussions":
            # Only replies to others
            query = query.where(CachedPost.is_reply == True)
        elif filter_type == "pictures":
            query = query.where(CachedPost.has_media == True)
        elif filter_type == "videos":
            query = query.where(CachedPost.has_video == True)
        elif filter_type == "news":
            query = query.where(CachedPost.has_news == True)
        elif filter_type == "software":
            query = query.where(CachedPost.has_tech == True)

        result = await session.execute(query)
        posts = result.scalars().all()

        return [
            {
                "id": p.id,
                "content": p.content,
                "author_acct": p.author_acct,
                "created_at": p.created_at.isoformat(),
                "media_attachments": json.loads(p.media_attachments) if p.media_attachments else [],
                "counts": {
                    "replies": p.replies_count,
                    "reblogs": p.reblogs_count,
                    "likes": p.favourites_count
                },
                "is_reblog": p.is_reblog,
                "is_reply": p.is_reply
            }
            for p in posts
        ]


@app.get("/api/public/storms")
async def get_storms(user: str | None = None):
    """
    Returns 'Tweet Storms'.
    Groups a root post and its subsequent self-replies into a single tree.
    """
    async with async_session() as session:
        # 1. Fetch all posts for the user (or all if user is None)
        query = select(CachedPost).order_by(desc(CachedPost.created_at))
        if user:
            query = query.where(CachedPost.author_acct == user)
        else:
            # By default, storms usually imply the blog owner
            query = query.where(CachedPost.is_reblog == False)

        result = await session.execute(query)
        all_posts = result.scalars().all()

    # 2. In-Memory Grouping Algorithm
    # Map ID -> Post
    post_map = {p.id: p for p in all_posts}

    # Identify Roots: Posts that do NOT have a parent in the fetched set
    # OR their parent is not by the same author (but here we filtered by author roughly)
    storms = []
    processed_ids = set()

    # Sort by date desc to find newest roots first
    sorted_posts = sorted(all_posts, key=lambda x: x.created_at, reverse=True)

    for p in sorted_posts:
        if p.id in processed_ids:
            continue

        # Check if this is a Root of a storm
        # It is a root if:
        # 1. It has no in_reply_to_id

        # These are discussions
        # 2. OR it replies to someone else (new conversation start)
        # 3. OR it replies to a post that we don't have in our DB (broken chain)

        is_root = False
        if not p.in_reply_to_id:
            is_root = True
        # elif p.in_reply_to_account_id != p.author_id:
        #     is_root = True
        # elif p.in_reply_to_id not in post_map:
        #     is_root = True

        if is_root:
            # Start a storm
            storm = {
                "root": {
                    "id": p.id,
                    "content": p.content,
                    "created_at": p.created_at.isoformat(),
                    "media": json.loads(p.media_attachments) if p.media_attachments else [],
                    "counts": {"replies": p.replies_count, "likes": p.favourites_count},
                    "author_acct": p.author_acct
                },
                "branches": []
            }
            processed_ids.add(p.id)

            # Find descendants recursively
            # This is O(N^2) worst case, but N is usually small (20-40 posts page)
            # A more efficient way is to build an adjacency list first.

            # Let's build a simple adjacency list for the dataset
            children_map = {}  # parent_id -> [children]
            for child in all_posts:
                if child.in_reply_to_id:
                    children_map.setdefault(child.in_reply_to_id, []).append(child)

            # Recursive collector
            def collect_children(parent_id):
                results = []
                direct_kids = children_map.get(parent_id, [])
                # Sort kids by time ASC (chronological reading)
                direct_kids.sort(key=lambda x: x.created_at)

                for kid in direct_kids:
                    if kid.author_id == post_map[parent_id].author_id:
                        processed_ids.add(kid.id)
                        kid_data = {
                            "id": kid.id,
                            "content": kid.content,
                            "media": json.loads(kid.media_attachments) if kid.media_attachments else [],
                            "counts": {"replies": kid.replies_count, "likes": kid.favourites_count},
                            "children": collect_children(kid.id)
                        }
                        results.append(kid_data)
                return results

            storm["branches"] = collect_children(p.id)
            storms.append(storm)

    return storms


@app.get("/api/public/analytics")
async def get_analytics(user: str | None = None):
    """Aggregate performance metrics."""
    async with async_session() as session:
        # Query sums
        stmt = select(
            func.count(CachedPost.id),
            func.sum(CachedPost.replies_count),
            func.sum(CachedPost.reblogs_count),
            func.sum(CachedPost.favourites_count)
        )
        if user:
            stmt = stmt.where(CachedPost.author_acct == user)

        row = (await session.execute(stmt)).first()

    return {
        "user": user or "all",
        "total_posts": row[0] or 0,
        "total_replies_received": row[1] or 0,
        "total_boosts": row[2] or 0,
        "total_favorites": row[3] or 0
    }


@app.get("/api/public/posts/{id}")
async def get_single_post(id: str):
    """Get a single cached post by ID."""
    async with async_session() as session:
        stmt = select(CachedPost).where(CachedPost.id == id)
        post = (await session.execute(stmt)).scalar_one_or_none()

        if not post:
            raise HTTPException(404, "Post not found")

        return {
            "id": post.id,
            "content": post.content,
            "author_acct": post.author_acct,
            "created_at": post.created_at.isoformat(),
            "media_attachments": json.loads(post.media_attachments) if post.media_attachments else [],
            "counts": {
                "replies": post.replies_count,
                "reblogs": post.reblogs_count,
                "likes": post.favourites_count
            },
            "is_reblog": post.is_reblog,
            "is_reply": post.is_reply
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
    """Master sync trigger"""
    await sync_accounts_friends_followers()  # Sync friends
    await sync_blog_roll_activity()  # Sync 'who is active'
    res = await sync_user_timeline(force=force)  # Sync my posts
    return {
        "timeline": res,
        "message": "Sync complete"
    }


@app.get("/api/admin/status")
async def admin_status() -> dict:
    token = await get_token()
    last_sync = await get_last_sync()

    # Get current user info
    current_user = None
    if token:
        try:
            m = client(token)
            me = m.account_verify_credentials()
            current_user = {
                "acct": me["acct"],
                "display_name": me["display_name"],
                "avatar": me["avatar"],
                "note": me.get("note", "")
            }
        except:
            pass

    return {
        "connected": token is not None,
        "last_sync": last_sync.isoformat() if last_sync else None,
        "current_user": current_user
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
    await sync_user_timeline(force=True)
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
    await sync_accounts_friends_followers()
    await sync_user_timeline(force=True)
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
    # This is a direct proxy for edit/view in admin, not public feed
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
