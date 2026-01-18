# mastodon_is_my_blog/main.py
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import Integer, and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from mastodon_is_my_blog.identity_verifier import verify_all_identities
from mastodon_is_my_blog.inspect_post import analyze_content_domains
from mastodon_is_my_blog.link_previews import CardResponse, fetch_card
from mastodon_is_my_blog.masto_client import (
    client,
    client_from_identity,
    get_default_client,
)
from mastodon_is_my_blog.perf import time_async_function
from mastodon_is_my_blog.store import (
    CachedAccount,
    CachedPost,
    MastodonIdentity,
    MetaAccount,
    async_session,
    bootstrap_identities_from_env,
    get_last_sync,
    get_or_create_default_meta_account,
    get_token,
    init_db,
    update_last_sync,
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


async def get_current_meta_account(request: Request) -> MetaAccount:
    """
    Identifies the Meta Account.
    In a real app, this would verify a JWT or Session Cookie.
    Here, we default to the 'default' user or read a header X-Meta-Account-ID.
    """
    async with async_session() as session:
        # Simple header check for multi-user test capability
        header_id = request.headers.get("X-Meta-Account-ID")
        if header_id:
            stmt = select(MetaAccount).where(MetaAccount.id == int(header_id))
            meta = (await session.execute(stmt)).scalar_one_or_none()
            if meta:
                return meta

        # Fallback to default
        stmt = select(MetaAccount).where(MetaAccount.username == "default")
        return (await session.execute(stmt)).scalar_one()


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


async def _upsert_account(
    session: AsyncSession, meta_id: int, account_data: dict, **overrides
):
    """
    Helper to create or update a CachedAccount from Mastodon API data.
    """
    acc_id = str(account_data["id"])

    # Check for existing account within THIS meta_account's view
    stmt = select(CachedAccount).where(
        and_(CachedAccount.id == acc_id, CachedAccount.meta_account_id == meta_id)
    )
    existing = (await session.execute(stmt)).scalar_one_or_none()

    # Prepare common fields
    fields_json = json.dumps(account_data.get("fields", []))
    created_at = to_naive_utc(account_data.get("created_at"))

    data = {
        "acct": account_data["acct"],
        "display_name": account_data["display_name"],
        "avatar": account_data["avatar"],
        "url": account_data["url"],
        "note": account_data.get("note", ""),
        "bot": account_data.get("bot", False),
        "locked": account_data.get("locked", False),
        "header": account_data.get("header", ""),
        "created_at": created_at,
        "fields": fields_json,
        "followers_count": account_data.get("followers_count", 0),
        "following_count": account_data.get("following_count", 0),
        "statuses_count": account_data.get("statuses_count", 0),
    }

    # Apply overrides (e.g. is_following=True)
    data.update(overrides)

    if not existing:
        new_acc = CachedAccount(id=acc_id, meta_account_id=meta_id, **data)
        session.add(new_acc)
        return new_acc
    else:
        for k, v in data.items():
            setattr(existing, k, v)
        return existing


async def sync_all_identities(meta: MetaAccount, force: bool = False):
    """Iterates through all identities for the meta account and syncs them."""
    async with async_session() as session:
        # Re-fetch identities to be safe
        result = await session.execute(
            select(MastodonIdentity).where(MastodonIdentity.meta_account_id == meta.id)
        )
        identities = result.scalars().all()

    results = []
    for identity in identities:
        # Sync Friends
        await sync_friends_for_identity(meta.id, identity)
        # Sync Blog Roll (Activity)
        await sync_blog_roll_for_identity(meta.id, identity)
        # Sync Timeline
        res = await sync_user_timeline_for_identity(meta.id, identity, force=force)
        results.append({identity.acct: res})
    return results


async def sync_friends_for_identity(meta_id: int, identity: MastodonIdentity):
    m = client_from_identity(identity)

    try:
        me = m.account_verify_credentials()
        following = m.account_following(me["id"], limit=80)
        followers = m.account_followers(me["id"], limit=80)

        async with async_session() as session:
            for acc in following:
                await _upsert_account(session, meta_id, acc, is_following=True)
            for acc in followers:
                await _upsert_account(session, meta_id, acc, is_followed_by=True)
            await session.commit()
    except Exception as e:
        logger.error(f"Failed to sync friends for {identity.acct}: {e}")


async def sync_blog_roll_for_identity(meta_id: int, identity: MastodonIdentity):
    m = client_from_identity(identity)

    try:
        home_statuses = m.timeline_home(limit=100)
        async with async_session() as session:
            for s in home_statuses:
                account_data = s["account"]
                last_status_time = to_naive_utc(s["created_at"])

                # Use helper to ensure correct meta_scope
                existing = await _upsert_account(session, meta_id, account_data)

                if (
                    not existing.last_status_at
                    or last_status_time > existing.last_status_at
                ):
                    existing.last_status_at = last_status_time
            await session.commit()
    except Exception as e:
        logger.error(f"Failed to sync blog roll for {identity.acct}: {e}")


async def sync_user_timeline_for_identity(
    meta_id: int,
    identity: MastodonIdentity,
    acct: str | None = None,  # If None, syncs the identity itself
    force: bool = False,
):
    target_acct_desc = acct if acct else "self"
    sync_key = f"timeline:{meta_id}:{identity.id}:{target_acct_desc}"

    last_run = await get_last_sync(sync_key)
    if (
        not force
        and last_run
        and (datetime.utcnow() - last_run) < timedelta(minutes=15)
    ):
        return {"status": "skipped"}

    m = client_from_identity(identity)

    try:
        if acct:
            s_res = m.account_search(acct, limit=1)
            if not s_res:
                return {"status": "not_found"}
            target_account = s_res[0]
            target_id = target_account["id"]
        else:
            target_account = m.account_verify_credentials()
            target_id = target_account["id"]

        statuses = m.account_statuses(target_id, limit=200)

        async with async_session() as session:
            # Upsert Author
            await _upsert_account(session, meta_id, target_account)

            for s in statuses:
                is_reblog = s["reblog"] is not None
                actual = s["reblog"] if is_reblog else s

                # Check Reply Status
                in_reply_to_id = actual.get("in_reply_to_id")
                in_reply_to_account = actual.get("in_reply_to_account_id")
                is_reply_to_other = in_reply_to_id is not None and str(
                    in_reply_to_account
                ) != str(actual["account"]["id"])

                flags = analyze_content_domains(
                    actual["content"], actual["media_attachments"], is_reply_to_other
                )
                media_json = (
                    json.dumps(actual["media_attachments"])
                    if actual["media_attachments"]
                    else None
                )
                created_at = to_naive_utc(s["created_at"])
                tags_json = json.dumps([t["name"] for t in s.get("tags", [])])

                # Check if post exists FOR THIS META ACCOUNT
                stmt = select(CachedPost).where(
                    and_(
                        CachedPost.id == str(s["id"]),
                        CachedPost.meta_account_id == meta_id,
                    )
                )
                existing = (await session.execute(stmt)).scalar_one_or_none()

                post_data = {
                    "content": actual["content"],
                    "created_at": created_at,
                    "visibility": s["visibility"],
                    "author_acct": actual["account"]["acct"],
                    "author_id": str(actual["account"]["id"]),
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
                    "fetched_by_identity_id": identity.id,
                }

                if not existing:
                    new_post = CachedPost(
                        id=str(s["id"]), meta_account_id=meta_id, **post_data
                    )
                    session.add(new_post)
                else:
                    for k, v in post_data.items():
                        setattr(existing, k, v)

            await session.commit()
            await update_last_sync(sync_key)
            return {"status": "success", "count": len(statuses)}

    except Exception as e:
        logger.error(f"Sync error {sync_key}: {e}")
        return {"status": "error", "msg": str(e)}


async def sync_accounts_friends_followers() -> None:
    """Syncs lists of following and followers. Legacy wrapper."""
    # NOTE: This uses the old token mechanism. Ideally should be deprecated
    # but kept for backward compatibility with simple setups.
    token = await get_token()
    if not token:
        logger.warning("No token")
        return
    m = client(token)
    me = m.account_verify_credentials()

    # We assume 'default' meta account for legacy calls
    async with async_session() as session:
        stmt = select(MetaAccount).where(MetaAccount.username == "default")
        meta = (await session.execute(stmt)).scalar_one_or_none()
        if not meta:
            return

        following = m.account_following(me["id"], limit=80)
        followers = m.account_followers(me["id"], limit=80)

        for acc in following:
            await _upsert_account(session, meta.id, acc, is_following=True)
        for acc in followers:
            await _upsert_account(session, meta.id, acc, is_followed_by=True)
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

            # Use upsert to ensure account exists and details are fresh
            existing = await _upsert_account(session, account_data)

            # Logic specifically for blogroll timing
            if (
                not existing.last_status_at
                or last_status_time > existing.last_status_at
            ):
                existing.last_status_at = last_status_time

        await session.commit()


async def sync_user_timeline(
    acct: str | None = None,
    acct_id: str | None = None,
    force: bool = False,
    cooldown_minutes: int = 15,
) -> dict:
    """Legacy wrapper: Syncs posts for a specific user to Default Meta Account."""
    if acct == "everyone":
        return {"status": "skipped", "reason": "virtual_user"}

    async with async_session() as session:
        # Get default meta
        stmt = select(MetaAccount).where(MetaAccount.username == "default")
        meta = (await session.execute(stmt)).scalar_one_or_none()
        if not meta:
            raise HTTPException(500, "Default meta account missing")

        # Get first identity
        stmt = (
            select(MastodonIdentity)
            .where(MastodonIdentity.meta_account_id == meta.id)
            .limit(1)
        )
        identity = (await session.execute(stmt)).scalar_one_or_none()
        if not identity:
            raise HTTPException(500, "No identity found")

    return await sync_user_timeline_for_identity(
        meta_id=meta.id, identity=identity, acct=acct, force=force
    )


@app.get("/api/status")
async def status() -> dict:
    return {"status": "up"}


@app.get("/api/public/accounts/blogroll")
async def get_blog_roll(
    filter_type: str = Query("all"),
    meta: MetaAccount = Depends(get_current_meta_account),
) -> list[dict]:
    """
    Returns active accounts discovered from the timeline.
    Scoped to the current Meta Account.

    Filters:
    - all: All accounts in the blog roll
    - top_friends: Accounts you follow (sorted by activity)
    - mutuals: Accounts that follow you back (mutual follows)
    - chatty: Accounts with high reply activity
    - broadcasters: Accounts with low reply activity (mostly posts)
    - bots: Accounts identified as bots (placeholder logic)
    """
    async with async_session() as session:
        # Base query: Get accounts that have posted recently OR are friends
        # SCALAR: Scoped to meta_account_id
        query = select(CachedAccount).where(
            and_(
                CachedAccount.meta_account_id == meta.id,
                or_(
                    CachedAccount.last_status_at != None,
                    CachedAccount.is_following == True,
                ),
            )
        )

        # Apply filter logic
        if filter_type == "top_friends":
            # Accounts you follow, sorted by most recent activity
            query = query.where(CachedAccount.is_following == True)
            query = query.order_by(desc(CachedAccount.last_status_at))

        elif filter_type == "mutuals":
            # Accounts where both is_following and is_followed_by are True
            query = query.where(
                and_(
                    CachedAccount.is_following == True,
                    CachedAccount.is_followed_by == True,
                )
            )
            query = query.order_by(desc(CachedAccount.last_status_at))

        elif filter_type == "chatty":
            # Accounts with high reply activity
            # We'll need to count their replies in CachedPost
            # For now, return accounts and calculate in Python
            query = query.order_by(desc(CachedAccount.last_status_at))

        elif filter_type == "broadcasters":
            # Accounts with low reply activity
            # Similar to chatty, we'll calculate this
            query = query.order_by(desc(CachedAccount.last_status_at))

        elif filter_type == "bots":
            # Bot detection heuristics:
            # - "bot" in display_name or acct (case insensitive)
            # - Specific patterns in note/bio
            query = query.where(
                or_(
                    CachedAccount.bot == True,
                    CachedAccount.display_name.ilike("%bot%"),
                    CachedAccount.acct.ilike("%bot%"),
                )
            )
            query = query.order_by(desc(CachedAccount.last_status_at))

        else:  # "all" or default
            query = query.order_by(desc(CachedAccount.last_status_at))

        query = query.limit(40)
        res = await session.execute(query)
        accounts = res.scalars().all()

        # For chatty/broadcasters, we need to calculate reply ratios
        if filter_type in ("chatty", "broadcasters"):
            accounts_with_stats = []

            for acc in accounts:
                # Count total posts and replies for this account
                # SCOPED: meta_account_id
                total_stmt = select(func.count(CachedPost.id)).where(
                    and_(
                        CachedPost.author_id == acc.id,
                        CachedPost.meta_account_id == meta.id,
                    )
                )
                reply_stmt = select(func.count(CachedPost.id)).where(
                    and_(
                        CachedPost.author_id == acc.id,
                        CachedPost.is_reply == True,
                        CachedPost.meta_account_id == meta.id,
                    )
                )

                total_result = await session.execute(total_stmt)
                reply_result = await session.execute(reply_stmt)

                total_posts = total_result.scalar() or 0
                reply_posts = reply_result.scalar() or 0

                reply_ratio = reply_posts / total_posts if total_posts > 0 else 0

                accounts_with_stats.append(
                    {
                        "account": acc,
                        "reply_ratio": reply_ratio,
                        "total_posts": total_posts,
                    }
                )

            # Sort by reply ratio
            if filter_type == "chatty":
                # High reply ratio = chatty (> 50% replies)
                accounts_with_stats = [
                    a
                    for a in accounts_with_stats
                    if a["reply_ratio"] > 0.5 and a["total_posts"] >= 5
                ]
                accounts_with_stats.sort(key=lambda x: x["reply_ratio"], reverse=True)
            else:  # broadcasters
                # Low reply ratio = broadcaster (< 20% replies)
                accounts_with_stats = [
                    a
                    for a in accounts_with_stats
                    if a["reply_ratio"] < 0.2 and a["total_posts"] >= 5
                ]
                accounts_with_stats.sort(key=lambda x: x["reply_ratio"])

            # Extract accounts from the stats
            accounts = [a["account"] for a in accounts_with_stats[:40]]

        return [
            {
                "id": a.id,
                "acct": a.acct,
                "display_name": a.display_name,
                "avatar": a.avatar,
                "url": a.url,
                "note": getattr(a, "note", ""),
                "bot": getattr(a, "bot", False),
                "last_status_at": (
                    a.last_status_at.isoformat() if a.last_status_at else None
                ),
            }
            for a in accounts
        ]


@app.get("/api/public/accounts/{acct}")
async def get_account_info(
    acct: str, meta: MetaAccount = Depends(get_current_meta_account)
):
    """Get cached account information by acct string."""

    # FIX: Handle 'everyone' virtual user to prevent 404s
    if acct == "everyone":
        return {
            "id": "everyone",
            "acct": "everyone",
            "display_name": "Everyone",
            # Simple placeholder avatar
            "avatar": "https://ui-avatars.com/api/?name=Everyone&background=f59e0b&color=fff&size=128",
            "header": "",
            "url": "",
            "note": "Aggregated feed from all active blog roll accounts.",
            "fields": [],
            "bot": False,
            "locked": False,
            "created_at": None,
            "counts": {"followers": 0, "following": 0, "statuses": 0},
            "is_following": False,
            "is_followed_by": False,
        }

    async with async_session() as session:
        # SCOPED: meta_account_id
        stmt = select(CachedAccount).where(
            and_(
                CachedAccount.acct == acct,
                CachedAccount.meta_account_id == meta.id,
            )
        )
        account = (await session.execute(stmt)).scalar_one_or_none()

        if not account:
            raise HTTPException(404, "Account not found in cache")

        # Parse fields from JSON
        fields_data = []
        if account.fields:
            try:
                fields_data = json.loads(account.fields)
            except:
                fields_data = []

        return {
            "id": account.id,
            "acct": account.acct,
            "display_name": account.display_name,
            "avatar": account.avatar,
            "header": account.header,
            "url": account.url,
            "note": account.note,
            "fields": fields_data,
            "bot": account.bot,
            "locked": account.locked,
            "created_at": (
                account.created_at.isoformat() if account.created_at else None
            ),
            "counts": {
                "followers": account.followers_count,
                "following": account.following_count,
                "statuses": account.statuses_count,
            },
            "is_following": account.is_following,
            "is_followed_by": account.is_followed_by,
        }


@app.post("/api/public/accounts/{acct}/sync")
async def sync_account(
    acct: str, meta: MetaAccount = Depends(get_current_meta_account)
):
    """Sync a specific user's timeline."""
    # FIX: Don't attempt to sync the virtual 'everyone' user
    if acct == "everyone":
        return {"status": "skipped", "message": "Cannot sync virtual user"}

    async with async_session() as session:
        # Get first identity for THIS meta account
        stmt = (
            select(MastodonIdentity)
            .where(MastodonIdentity.meta_account_id == meta.id)
            .limit(1)
        )
        identity = (await session.execute(stmt)).scalar_one_or_none()

        if not identity:
            raise HTTPException(
                500, "No identity found. Please configure MASTODON_ID_* in .env"
            )

    # Call the identity-aware sync function
    result = await sync_user_timeline_for_identity(
        meta_id=meta.id, identity=identity, acct=acct, force=True
    )
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
    meta: MetaAccount = Depends(get_current_meta_account),
) -> list[dict]:
    """
    Get posts with filters.
    User arg: filter by username (acct). If None and not 'everyone' filter, gets main user's posts.
    """
    async with async_session() as session:
        # SCOPED: meta_account_id
        query = select(CachedPost).where(CachedPost.meta_account_id == meta.id)
        query = query.order_by(desc(CachedPost.created_at))

        # FIX: Handle user="everyone" explicitly to bypass filtering
        if user == "everyone":
            # Show all posts from all users (still scoped to meta)
            pass
        elif filter_type == "everyone":
            # Legacy handle: Show all posts from all users
            pass
        elif user:
            # Filter by specific user
            query = query.where(CachedPost.author_acct == user)
        else:
            # No user specified and not "everyone" filter - default to main user
            # Find the primary identity's acct for this meta account
            stmt = (
                select(MastodonIdentity)
                .where(MastodonIdentity.meta_account_id == meta.id)
                .limit(1)
            )
            identity = (await session.execute(stmt)).scalar_one_or_none()
            if identity:
                query = query.where(CachedPost.author_acct == identity.acct)
            else:
                # Fallback if no identity found
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
async def get_all_posts_unfiltered(
    user: str | None = None, meta: MetaAccount = Depends(get_current_meta_account)
):
    """Returns ALL posts, including replies, reblogs, links, etc."""
    async with async_session() as session:
        # SCOPED: meta_account_id
        query = select(CachedPost).where(CachedPost.meta_account_id == meta.id)
        query = query.order_by(desc(CachedPost.created_at))

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
async def get_shorts(
    user: str | None = None, meta: MetaAccount = Depends(get_current_meta_account)
):
    """
    Convenience endpoint for Shorts (short text posts).
    Delegates to get_public_posts, passing the meta account.
    """
    return await get_public_posts(user=user, filter_type="shorts", meta=meta)


@app.get("/api/public/storms")
@time_async_function
async def get_storms(
    user: str | None = None, meta: MetaAccount = Depends(get_current_meta_account)
):
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
            # Default to main user of this meta account
            stmt = (
                select(MastodonIdentity)
                .where(MastodonIdentity.meta_account_id == meta.id)
                .limit(1)
            )
            identity = (await session.execute(stmt)).scalar_one_or_none()
            if identity:
                target_user = identity.acct
            else:
                return []

        # 1. Fetch all posts for the user
        # SCOPED: meta_account_id
        query = select(CachedPost).where(CachedPost.meta_account_id == meta.id)
        query = query.order_by(desc(CachedPost.created_at))

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
async def get_hashtags(
    user: str | None = None, meta: MetaAccount = Depends(get_current_meta_account)
):
    """Aggregates all hashtags used by the user."""
    async with async_session() as session:
        # SCOPED: meta_account_id
        query = select(CachedPost.tags).where(CachedPost.meta_account_id == meta.id)

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
async def get_analytics(
    user: str | None = None, meta: MetaAccount = Depends(get_current_meta_account)
):
    """Aggregate performance metrics."""
    async with async_session() as session:
        # Query sums
        stmt = select(
            func.count(CachedPost.id),
            func.sum(CachedPost.replies_count),
            func.sum(CachedPost.reblogs_count),
            func.sum(CachedPost.favourites_count),
        ).where(CachedPost.meta_account_id == meta.id)  # SCOPED

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
    Note: Context crawling is done live via API, so less scoped,
    but we use the token from env or DB which defines the scope.
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
async def get_single_post(id: str, meta: MetaAccount = Depends(get_current_meta_account)):
    """Get a single cached post by ID."""
    async with async_session() as session:
        # SCOPED: meta_account_id
        stmt = select(CachedPost).where(
            and_(
                CachedPost.id == id,
                CachedPost.meta_account_id == meta.id,
            )
        )
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
    token = await get_token()
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
async def trigger_sync(
    force: bool = True, meta: MetaAccount = Depends(get_current_meta_account)
) -> dict:
    res = await sync_all_identities(meta, force=force)
    return {"results": res}


@app.get("/api/admin/identities")
async def list_identities(meta: MetaAccount = Depends(get_current_meta_account)):
    async with async_session() as session:
        stmt = select(MastodonIdentity).where(
            MastodonIdentity.meta_account_id == meta.id
        )
        res = (await session.execute(stmt)).scalars().all()
        return [{"id": i.id, "acct": i.acct, "base_url": i.api_base_url} for i in res]


@app.post("/api/admin/identities")
async def add_identity(
    base_url: str,
    code: str,
    client_id: str,
    client_secret: str,
    meta: MetaAccount = Depends(get_current_meta_account),
):
    """
    Exchanges code for token and saves identity.
    (Simplified OAuth flow - normally requires redirect)
    """
    # Create temp client to exchange code
    m = client(base_url, client_id, client_secret)
    access_token = m.log_in(code=code, scopes=["read", "write"])
    me = m.account_verify_credentials()

    async with async_session() as session:
        new_id = MastodonIdentity(
            meta_account_id=meta.id,
            api_base_url=base_url,
            client_id=client_id,
            client_secret=client_secret,
            access_token=access_token,
            acct=me["acct"],
            account_id=str(me["id"]),
        )
        session.add(new_id)
        await session.commit()
    return {"status": "created", "acct": me["acct"]}


@app.get("/api/admin/status")
async def admin_status() -> dict:
    """Get connection status and current user info"""

    # Try to get default identity
    current_user = None
    connected = False

    async with async_session() as session:
        stmt = select(MetaAccount).where(MetaAccount.username == "default")
        meta = (await session.execute(stmt)).scalar_one_or_none()

        if meta:
            stmt = (
                select(MastodonIdentity)
                .where(MastodonIdentity.meta_account_id == meta.id)
                .limit(1)
            )
            identity = (await session.execute(stmt)).scalar_one_or_none()

            if identity and identity.access_token:
                connected = True
                try:
                    from mastodon_is_my_blog.masto_client import client_from_identity

                    m = client_from_identity(identity)
                    me = m.account_verify_credentials()
                    current_user = {
                        "acct": me["acct"],
                        "display_name": me["display_name"],
                        "avatar": me["avatar"],
                        "note": me.get("note", ""),
                    }
                except Exception as e:
                    logger.error(f"Failed to verify credentials: {e}")
                    connected = False

    last_sync = await get_last_sync()

    return {
        "connected": connected,
        "last_sync": last_sync.isoformat() if last_sync else None,
        "current_user": current_user,
    }


@app.post("/api/posts")
async def create_post(payload: PostIn):
    token = await get_token()
    if not token:
        raise HTTPException(401, "Not connected")
    m = await get_default_client()

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
    m = await get_default_client()
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
async def get_counts(
    user: str | None = None, meta: MetaAccount = Depends(get_current_meta_account)
) -> dict:
    """
    Returns counts used for sidebar badges.
    Counts are designed to match existing feed endpoint semantics.
    """
    # If user is "everyone", treat it as None (all users within meta scope)
    if user == "everyone":
        user = None

    async with async_session() as session:
        return await get_counts_optimized(session, meta.id, user)


async def get_counts_optimized(
    session: AsyncSession, meta_id: int, user: str | None = None
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
                    CachedPost.in_reply_to_id is None,
                    CachedPost.has_link == False,
                    *base_conditions,
                ),
                Integer,
            )
        ).label("storms"),
        # Shorts
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

    # SCOPED: Global filter for this meta account on the table before aggregation
    query = query.where(CachedPost.meta_account_id == meta_id)

    # Add user filter if specified (also in WHERE to optimize scan)
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


@app.get("/card", response_model=CardResponse)
async def fetch_card_endpoint(url: str = Query(..., min_length=8, max_length=2048)):
    return await fetch_card(url)
