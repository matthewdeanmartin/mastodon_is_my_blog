import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import Integer, and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from mastodon_is_my_blog.inspect_post import analyze_content_domains
from mastodon_is_my_blog.masto_client import client
from mastodon_is_my_blog.perf import time_async_function
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

logger = logging.getLogger(__name__)
logging.basicConfig()
logging.getLogger("mastodon_is_my_blog").setLevel(logging.INFO)

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


# --- Sync Engines ---


async def sync_accounts_friends_followers() -> None:
    """Syncs lists of following and followers."""
    token = await get_token()
    if not token:
        logger.warning("No token")
        return
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
                    id=str(acc["id"]),
                    acct=acc["acct"],
                    display_name=acc["display_name"],
                    avatar=acc["avatar"],
                    url=acc["url"],
                    is_following=True,
                    note=acc.get("note", ""),
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
                logger.warning(f"New account {acc['acct']}")
                new_acc = CachedAccount(
                    id=str(acc["id"]),
                    acct=acc["acct"],
                    display_name=acc["display_name"],
                    avatar=acc["avatar"],
                    url=acc["url"],
                    is_followed_by=True,
                    note=acc.get("note", ""),
                )
                session.add(new_acc)
            else:
                existing.is_followed_by = True

        await session.commit()
    await update_last_sync("accounts")


async def sync_blog_roll_activity() -> None:
    """
    Fetches the Home Timeline to find who is active.
    Updates CachedAccount.last_status_at for the Blog Roll.
    """
    token = await get_token()
    if not token:
        return
    m = client(token)

    # Fetch Home Timeline (Active people I follow)
    home_statuses = m.timeline_home(limit=200)

    async with async_session() as session:
        for s in home_statuses:
            account_data = s["account"]
            # Find account in DB (should be there if we ran sync_accounts, but create if new)
            stmt = select(CachedAccount).where(
                CachedAccount.id == str(account_data["id"])
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()

            # --- Convert to Naive UTC before comparing ---
            last_status_time = to_naive_utc(s["created_at"])

            if existing:
                logger.warning(f"Cache hit {account_data['acct']}")
                # Update last active time if this post is newer
                # existing.last_status_at is Naive (from SQLite), last_status_time is now Naive.
                if (
                    not existing.last_status_at
                    or last_status_time > existing.last_status_at
                ):
                    existing.last_status_at = last_status_time
            else:
                logger.warning(f"New account {account_data['acct']}")
                # Discovered a new active person (maybe from a boost)
                new_acc = CachedAccount(
                    id=str(account_data["id"]),
                    acct=account_data["acct"],
                    display_name=account_data["display_name"],
                    avatar=account_data["avatar"],
                    url=account_data["url"],
                    last_status_at=last_status_time,
                    note=account_data.get("note", ""),
                )
                session.add(new_acc)

        await session.commit()


async def sync_user_timeline(
    acct: str | None = None,
    acct_id: str | None = None,
    force: bool = False,
    cooldown_minutes: int = 15,
) -> dict:
    """Syncs posts for a specific user. Defaults to Me."""
    if acct == "everyone":
        return {"status": "skipped", "reason": "virtual_user"}

    sync_key = f"user_timeline_{acct or acct_id or 'me'}"
    last_run = await get_last_sync(sync_key)

    # Check custom cooldown
    if (
        not force
        and last_run
        and (datetime.utcnow() - last_run) < timedelta(minutes=cooldown_minutes)
    ):
        return {"status": "skipped", "reason": "synced_recently"}

    token = await get_token()
    if not token:
        raise HTTPException(401, "Not connected")
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
                note=target_account.get("note", ""),
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

            is_reply_to_other = in_reply_to_id is not None and str(
                in_reply_to_account
            ) != str(actual_status["account"]["id"])

            media_json = (
                json.dumps(actual_status["media_attachments"])
                if actual_status["media_attachments"]
                else None
            )

            # FIX: Ensure creation date is naive UTC
            created_at_naive = to_naive_utc(s["created_at"])

            stmt = select(CachedPost).where(CachedPost.id == str(s["id"]))
            existing = (await session.execute(stmt)).scalar_one_or_none()
            # Extract tags
            tags_list = [t["name"] for t in s.get("tags", [])]
            tags_json = json.dumps(tags_list)

            post_data = {
                "content": actual_status["content"],
                "created_at": created_at_naive,
                "visibility": s["visibility"],
                "author_acct": actual_status["account"]["acct"],
                "author_id": str(actual_status["account"]["id"]),
                "is_reblog": is_reblog,
                "is_reply": is_reply_to_other,
                "in_reply_to_id": str(in_reply_to_id) if in_reply_to_id else None,
                "in_reply_to_account_id": (
                    str(in_reply_to_account) if in_reply_to_account else None
                ),
                "has_media": flags["has_media"],
                "has_video": flags["has_video"],
                "has_news": flags["has_news"],
                "has_tech": flags["has_tech"],
                "has_link": flags["has_link"],
                "has_question": flags["has_question"],
                "tags": tags_json,
                "replies_count": s["replies_count"],
                "reblogs_count": s["reblogs_count"],
                "favourites_count": s["favourites_count"],
                "media_attachments": media_json,
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


@app.get("/api/status")
async def status() -> dict:
    return {"status": "up"}


@app.get("/api/public/accounts/blogroll")
async def get_blog_roll():
    """Returns active accounts discovered from the timeline."""
    async with async_session() as session:
        # Get accounts that have posted recently OR are friends
        query = (
            select(CachedAccount)
            .where(
                or_(
                    CachedAccount.last_status_at != None,
                    CachedAccount.is_following == True,
                )
            )
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
                "note": getattr(a, "note", ""),
                "last_status_at": (
                    a.last_status_at.isoformat() if a.last_status_at else None
                ),
            }
            for a in accounts
        ]


@app.get("/api/public/accounts/{acct}")
async def get_account_info(acct: str):
    """Get cached account information by acct string."""

    # FIX: Handle 'everyone' virtual user to prevent 404s
    if acct == "everyone":
        return {
            "id": "everyone",
            "acct": "everyone",
            "display_name": "Everyone",
            # Simple placeholder avatar
            "avatar": "https://ui-avatars.com/api/?name=Everyone&background=f59e0b&color=fff&size=128",
            "url": "",
            "note": "Aggregated feed from all active blog roll accounts.",
            "is_following": False,
            "is_followed_by": False,
        }

    async with async_session() as session:
        stmt = select(CachedAccount).where(CachedAccount.acct == acct)
        account = (await session.execute(stmt)).scalar_one_or_none()

        if not account:
            raise HTTPException(404, "Account not found in cache")

        # TODO: needs user's URLs and stuff.
        return {
            "id": account.id,
            "acct": account.acct,
            "display_name": account.display_name,
            "avatar": account.avatar,
            "url": account.url,
            "note": account.note,
            "is_following": account.is_following,
            "is_followed_by": account.is_followed_by,
        }


@app.post("/api/public/accounts/{acct}/sync")
async def sync_account(acct: str):
    """Sync a specific user's timeline."""
    # FIX: Don't attempt to sync the virtual 'everyone' user
    if acct == "everyone":
        return {"status": "skipped", "message": "Cannot sync virtual user"}

    result = await sync_user_timeline(acct=acct, force=True)
    return result


@app.get("/api/public/posts")
async def get_public_posts(
    user: str | None = None,
    filter_type: str = Query(
        "all",
        enum=[
            "all",
            "storm",
            "shorts",
            "discussions",
            "pictures",
            "videos",
            "news",
            "software",
            "links",
            "questions",
            "everyone",
        ],
    ),
) -> list[dict]:
    """
    Get posts with filters.
    User arg: filter by username (acct). If None and not 'everyone' filter, gets main user's posts.
    """
    async with async_session() as session:
        query = select(CachedPost).order_by(desc(CachedPost.created_at))

        # FIX: Handle user="everyone" explicitly to bypass filtering
        if user == "everyone":
            # Show all posts from all users (no user filtering)
            pass
        elif filter_type == "everyone":
            # Legacy handle: Show all posts from all users
            pass
        elif user:
            # Filter by specific user
            query = query.where(CachedPost.author_acct == user)
        else:
            # No user specified and not "everyone" filter - default to main user
            # Get the main user from token
            token = await get_token()
            if token:
                try:
                    m = client(token)
                    me = m.account_verify_credentials()
                    query = query.where(CachedPost.author_acct == me["acct"])
                except:
                    # If we can't get main user, show nothing rather than everyone
                    query = query.where(CachedPost.id == "impossible_id")

        # Apply Type Filters
        if filter_type == "all":
            # Show roots only (hide replies to others, keep self-threads)
            query = query.where(
                and_(CachedPost.is_reblog == False, CachedPost.is_reply == False)
            )
        elif filter_type == "storms":
            # not implemented yet!
            # should match get_storms method
            pass
        elif filter_type == "shorts":
            # NEW: Short text posts, no media, no links, not a reply
            query = query.where(
                and_(
                    CachedPost.is_reply == False,
                    CachedPost.is_reblog == False,
                    CachedPost.has_media == False,
                    CachedPost.has_video == False,
                    CachedPost.has_link == False,
                    func.length(CachedPost.content) < 500,
                )
            )
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
        elif filter_type == "links":
            # New Filter: Posts with links
            query = query.where(CachedPost.has_link == True)
        elif filter_type == "questions":
            # Filter for posts with questions
            query = query.where(CachedPost.has_question == True)
        elif filter_type == "everyone":
            # No additional filters, show all posts
            pass

        result = await session.execute(query)
        posts = result.scalars().all()

        return [
            {
                "id": p.id,
                "content": p.content,
                "author_acct": p.author_acct,
                "created_at": p.created_at.isoformat(),
                "media_attachments": (
                    json.loads(p.media_attachments) if p.media_attachments else []
                ),
                "counts": {
                    "replies": p.replies_count,
                    "reblogs": p.reblogs_count,
                    "likes": p.favourites_count,
                },
                "is_reblog": p.is_reblog,
                "is_reply": p.is_reply,
                "has_link": p.has_link,
                "tags": json.loads(p.tags) if p.tags else [],
            }
            for p in posts
        ]


# --- Unfiltered Endpoint ---
@app.get("/api/public/posts/all")
async def get_all_posts_unfiltered(user: str | None = None):
    """Returns ALL posts, including replies, reblogs, links, etc."""
    async with async_session() as session:
        query = select(CachedPost).order_by(desc(CachedPost.created_at))

        # FIX: Handle "everyone" here too
        if user and user != "everyone":
            query = query.where(CachedPost.author_acct == user)

        result = await session.execute(query)
        posts = result.scalars().all()

        return [
            {
                "id": p.id,
                "content": p.content,
                "created_at": p.created_at.isoformat(),
                "is_reply": p.is_reply,
                "is_reblog": p.is_reblog,
                "has_link": p.has_link,
            }
            for p in posts
        ]

@app.get("/api/public/shorts")
async def get_shorts(user: str | None = None):
    """
    Convenience endpoint for Shorts (short text posts).
    Delegates to get_public_posts.
    """
    return await get_public_posts(user=user, filter_type="shorts")

@app.get("/api/public/storms")
@time_async_function
async def get_storms(user: str | None = None):
    """
    Returns 'Tweet Storms'.
    Groups a root post and its subsequent self-replies into a single tree.
    Excludes posts with external links from being roots.
    If user is None, defaults to main authenticated user.
    """
    async with async_session() as session:
        # Determine which user to show
        target_user = user

        # FIX: Default to main user ONLY if not requesting everyone
        if target_user != "everyone" and not target_user:
            # Default to main user
            token = await get_token()
            if token:
                try:
                    m = client(token)
                    me = m.account_verify_credentials()
                    target_user = me["acct"]
                except:
                    # Can't determine main user, return empty
                    return []

        # 1. Fetch all posts for the user
        query = select(CachedPost).order_by(desc(CachedPost.created_at))

        # FIX: Apply user filter only if not "everyone"
        if target_user != "everyone":
            query = query.where(CachedPost.author_acct == target_user)

        query = query.where(CachedPost.is_reblog == False)

        result = await session.execute(query)
        all_posts = result.scalars().all()

    # 2. In-Memory Grouping Algorithm
    # Map ID -> Post
    post_map = {p.id: p for p in all_posts}

    # Build Adjacency List (Parent -> Children)
    # This must handle "missing parents" gracefully
    children_map = {}  # parent_id -> [children_posts]
    for p in all_posts:
        if p.in_reply_to_id:
            children_map.setdefault(p.in_reply_to_id, []).append(p)

    # 3. Identify Roots
    storms = []
    processed_ids = set()

    # We iterate chronologically DESC (newest first) to show latest storms at top
    sorted_posts = sorted(all_posts, key=lambda x: x.created_at, reverse=True)

    for p in sorted_posts:
        if p.id in processed_ids:
            continue

        # Root Definition:
        # 1. No parent (in_reply_to_id is None)
        # 2. Not a link post (optional preference)
        # 3. If it HAS a parent, but that parent isn't in our DB (broken chain), treat as root?
        #    For now, strict roots only.
        is_root = False
        # ROOT DEFINITION UPDATE:
        # 1. Must not be a reply
        # 2. Must NOT have a link (per user request)
        if not p.in_reply_to_id and not p.has_link:
            is_root = True

        if is_root:
            processed_ids.add(p.id)

            # Recursive collector that strictly follows SELF-REPLIES
            def collect_children(parent_id: str, root_author_id: str):
                results = []
                direct_kids = children_map.get(parent_id, [])
                # Sort kids by time ASC (chronological reading)
                direct_kids.sort(key=lambda x: x.created_at)

                for kid in direct_kids:
                    # STRICT RULE: Must be same author as Root to be part of the storm
                    if kid.author_id == root_author_id:
                        processed_ids.add(kid.id)
                        kid_data = {
                            "id": kid.id,
                            "content": kid.content,
                            "media": (
                                json.loads(kid.media_attachments)
                                if kid.media_attachments
                                else []
                            ),
                            "counts": {
                                "replies": kid.replies_count,
                                "likes": kid.favourites_count,
                            },
                            "children": collect_children(kid.id, root_author_id),
                        }
                        results.append(kid_data)
                return results

            # Build the storm object
            storm = {
                "root": {
                    "id": p.id,
                    "content": p.content,
                    "created_at": p.created_at.isoformat(),
                    "media": (
                        json.loads(p.media_attachments) if p.media_attachments else []
                    ),
                    "counts": {"replies": p.replies_count, "likes": p.favourites_count},
                    "author_acct": p.author_acct,
                },
                "branches": collect_children(p.id, p.author_id),
            }
            storms.append(storm)

    return storms


# --- Hashtag Aggregation ---
@app.get("/api/public/hashtags")
async def get_hashtags(user: str | None = None):
    """Aggregates all hashtags used by the user."""
    async with async_session() as session:
        query = select(CachedPost.tags)
        if user and user != "everyone":
            query = query.where(CachedPost.author_acct == user)

        result = await session.execute(query)
        # Result is a list of JSON strings (["['tag1', 'tag2']", "['tag3']"])
        all_tags_raw = result.scalars().all()

    tag_counts = {}
    for raw in all_tags_raw:
        if not raw:
            continue
        try:
            tags = json.loads(raw)
            for t in tags:
                lower_t = t.lower()
                tag_counts[lower_t] = tag_counts.get(lower_t, 0) + 1
        except:
            continue

    # Return sorted by count
    return sorted(
        [{"name": k, "count": v} for k, v in tag_counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )


@app.get("/api/public/analytics")
async def get_analytics(user: str | None = None):
    """Aggregate performance metrics."""
    async with async_session() as session:
        # Query sums
        stmt = select(
            func.count(CachedPost.id),
            func.sum(CachedPost.replies_count),
            func.sum(CachedPost.reblogs_count),
            func.sum(CachedPost.favourites_count),
        )
        if user and user != "everyone":
            stmt = stmt.where(CachedPost.author_acct == user)

        row = (await session.execute(stmt)).first()

    return {
        "user": user or "all",
        "total_posts": row[0] or 0,
        "total_replies_received": row[1] or 0,
        "total_boosts": row[2] or 0,
        "total_favorites": row[3] or 0,
    }


# --- Context Crawler ---
@app.get("/api/public/posts/{id}/context")
@time_async_function
async def get_post_context(id: str):
    """
    Crawls the conversation graph for a specific post.
    Returns ancestors (parents) and descendants (children).
    """
    token = await get_token()
    if not token:
        raise HTTPException(401, "Server not connected to Mastodon")

    m = client(token)
    try:
        # Mastodon API 'status_context' does the crawling for us
        # It returns 'ancestors' and 'descendants' list
        context = m.status_context(id)

        # We also need the target post itself
        target = m.status(id)

        return {
            "ancestors": context["ancestors"],
            "target": target,
            "descendants": context["descendants"],
        }
    except Exception as e:
        raise HTTPException(404, f"Could not fetch context: {str(e)}")


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
            "media_attachments": (
                json.loads(post.media_attachments) if post.media_attachments else []
            ),
            "counts": {
                "replies": post.replies_count,
                "reblogs": post.reblogs_count,
                "likes": post.favourites_count,
            },
            "is_reblog": post.is_reblog,
            "is_reply": post.is_reply,
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
@time_async_function
async def trigger_sync(force: bool = True) -> dict:
    """Master sync trigger"""
    await sync_accounts_friends_followers()  # Sync friends
    await sync_blog_roll_activity()  # Sync 'who is active'
    res = await sync_user_timeline(force=force)  # Sync my posts
    return {"timeline": res, "message": "Sync complete"}


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
                "note": me.get("note", ""),
            }
        except:
            pass

    return {
        "connected": token is not None,
        "last_sync": last_sync.isoformat() if last_sync else None,
        "current_user": current_user,
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


@app.get("/api/public/counts")
@time_async_function
async def get_counts(user: str | None = None) -> dict:
    """
    Returns counts used for sidebar badges.
    Counts are designed to match existing feed endpoint semantics.
    """
    # If user is "everyone", treat it as None (all users)
    if user == "everyone":
        user = None

    async with async_session() as session:
        return await get_counts_optimized(session, user)


async def get_counts_optimized(
    session: AsyncSession, user: str | None = None
) -> dict[str, int]:
    """
    Optimized count query using a single query with conditional aggregation.
    This is MUCH faster than 9 separate COUNT queries.
    """

    # Build base conditions
    base_conditions = []
    if user:
        base_conditions.append(CachedPost.author_acct == user)

    # Use CASE expressions for conditional counting (SQLite supports this)
    query = select(
        # Storms: not reblog, not reply, no link
        func.sum(
            func.cast(
                and_(
                    CachedPost.is_reblog == False,
                    CachedPost.in_reply_to_id == None,
                    CachedPost.has_link == False,
                    *base_conditions,
                ),
                Integer,
            )
        ).label("storms"),
        # Shorts (NEW)
        func.sum(
            func.cast(
                and_(
                    CachedPost.is_reply == False,
                    CachedPost.is_reblog == False,
                    CachedPost.has_media == False,
                    CachedPost.has_video == False,
                    CachedPost.has_link == False,
                    func.length(CachedPost.content) < 500,
                    *base_conditions,
                ),
                Integer,
            )
        ).label("shorts"),
        # News
        func.sum(
            func.cast(and_(CachedPost.has_news == True, *base_conditions), Integer)
        ).label("news"),
        # Software
        func.sum(
            func.cast(and_(CachedPost.has_tech == True, *base_conditions), Integer)
        ).label("software"),
        # Pictures
        func.sum(
            func.cast(and_(CachedPost.has_media == True, *base_conditions), Integer)
        ).label("pictures"),
        # Videos
        func.sum(
            func.cast(and_(CachedPost.has_video == True, *base_conditions), Integer)
        ).label("videos"),
        # Discussions
        func.sum(
            func.cast(and_(CachedPost.is_reply == True, *base_conditions), Integer)
        ).label("discussions"),
        # Links
        func.sum(
            func.cast(and_(CachedPost.has_link == True, *base_conditions), Integer)
        ).label("links"),
        # Questions
        func.sum(
            func.cast(and_(CachedPost.has_question == True, *base_conditions), Integer)
        ).label("questions"),
        # Everyone (total count)
        func.count().label("everyone"),
    ).select_from(CachedPost)

    # Add user filter if specified
    if user:
        query = query.where(CachedPost.author_acct == user)

    result = await session.execute(query)
    row = result.first()

    return {
        "user": user or "all",
        "storms": row.storms or 0,
        "shorts": row.shorts or 0,
        "news": row.news or 0,
        "software": row.software or 0,
        "pictures": row.pictures or 0,
        "videos": row.videos or 0,
        "discussions": row.discussions or 0,
        "links": row.links or 0,
        "questions": row.questions or 0,
        "everyone": row.everyone or 0,
    }
