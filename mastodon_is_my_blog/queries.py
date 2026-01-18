# mastodon_is_my_blog/main.py
import json
import logging
from datetime import datetime, timedelta, timezone

import dotenv
from fastapi import HTTPException, Request
from sqlalchemy import Integer, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mastodon_is_my_blog.inspect_post import analyze_content_domains
from mastodon_is_my_blog.mastodon_apis.masto_client import (
    client,
    client_from_identity,
)
from mastodon_is_my_blog.store import (
    CachedAccount,
    CachedPost,
    MastodonIdentity,
    MetaAccount,
    async_session,
    get_last_sync,
    get_token,
    update_last_sync,
)

logger = logging.getLogger(__name__)
logging.basicConfig()
logging.getLogger("mastodon_is_my_blog").setLevel(logging.INFO)

dotenv.load_dotenv()


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
    session: AsyncSession, meta_id: int,
        identity_id: int,  account_data: dict, **overrides
):
    """
    Helper to create or update a CachedAccount from Mastodon API data.
    """
    acc_id = str(account_data["id"])

    # Check for existing account within THIS meta_account's view
    stmt = select(CachedAccount).where(
        and_(
            CachedAccount.id == acc_id,
            CachedAccount.meta_account_id == meta_id,
            CachedAccount.mastodon_identity_id == identity_id
        )
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
        new_acc = CachedAccount(
            id=acc_id,
            meta_account_id=meta_id,
            mastodon_identity_id=identity_id,
            **data
        )
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
                # Pass identity.id
                await _upsert_account(session, meta_id, identity.id, acc, is_following=True)
            for acc in followers:
                # Pass identity.id
                await _upsert_account(session, meta_id, identity.id, acc, is_followed_by=True)
            await session.commit()
    except Exception as e:
        logger.error(f"Failed to sync friends for {identity.acct}: {e}")

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

                # Pass identity.id
                existing = await _upsert_account(session, meta_id, identity.id, account_data)

                if not existing.last_status_at or last_status_time > existing.last_status_at:
                    existing.last_status_at = last_status_time
            await session.commit()
    except Exception as e:
        logger.error(f"Failed to sync blog roll for {identity.acct}: {e}")


async def sync_user_timeline_for_identity(
        meta_id: int,
        identity: MastodonIdentity,
        acct: str | None = None,
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
            await _upsert_account(session, meta_id,                 identity.id,                                  target_account)

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
                        CachedPost.fetched_by_identity_id == identity.id
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

                post_data["fetched_by_identity_id"] = identity.id  # Ensure this is in data

                if not existing:
                    # Explicitly pass identity ID if not in **post_data unpacking
                    new_post = CachedPost(
                        id=str(s["id"]),
                        meta_account_id=meta_id,
                        **post_data
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
            existing = await _upsert_account(
                session, existing.meta_account_id, account_data
            )

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


async def get_counts_optimized(
    session: AsyncSession, meta_id: int, user: str | None = None
) -> dict[str, int | str]:
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
