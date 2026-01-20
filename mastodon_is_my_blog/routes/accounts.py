# mastodon_is_my_blog/routes/accounts.py
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, desc, exists, func, select

from mastodon_is_my_blog.queries import (
    get_current_meta_account,
    sync_user_timeline_for_identity,
)
from mastodon_is_my_blog.store import (
    CachedAccount,
    CachedPost,
    MastodonIdentity,
    MetaAccount,
    async_session,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


@router.get("/blogroll")
async def get_blog_roll(
    identity_id: int = Query(..., description="The context Identity ID"),
    filter_type: str = Query("all"),
    meta: MetaAccount = Depends(get_current_meta_account),
) -> list[dict]:
    """
    Returns active accounts discovered from the timeline of a SPECIFIC identity.

    Filters:
    - all: Everyone I follow (no strangers)
    - top_friends: Mutuals who have replied to me
    - mutuals: I follow them, they follow me
    - chatty: High reply ratio (> 50%)
    - broadcasters: Low reply ratio (< 20%)
    - bots: Strictly identified as bots
    """
    async with async_session() as session:
        # 1. Get the current identity to know "My Account ID" for the "Replied to Me" check
        stmt = select(MastodonIdentity).where(MastodonIdentity.id == identity_id)
        identity = (await session.execute(stmt)).scalar_one_or_none()
        if not identity:
            raise HTTPException(404, "Identity not found")

        my_account_id = identity.account_id

        # 2. Base Query: STRICTLY people I follow
        # This removes the "weirdos" (boost-only strangers) from all views.
        query = select(CachedAccount).where(
            and_(
                CachedAccount.meta_account_id == meta.id,
                CachedAccount.mastodon_identity_id == identity_id,
                CachedAccount.is_following == True,  # <--- The fix for "unknown people"
            )
        )

        # 3. Apply specific filters
        if filter_type == "top_friends":
            # Mutuals + Have replied to ME
            # We look for posts where author is the friend, and in_reply_to is ME.
            query = query.where(CachedAccount.is_followed_by == True)

            # Subquery to check for interaction
            has_replied_to_me = exists(
                select(1).where(
                    and_(
                        CachedPost.author_id == CachedAccount.id,
                        CachedPost.in_reply_to_account_id == str(my_account_id),
                        CachedPost.meta_account_id == meta.id,
                        CachedPost.fetched_by_identity_id == identity_id,
                    )
                )
            )
            query = query.where(has_replied_to_me)
            query = query.order_by(desc(CachedAccount.last_status_at))

        elif filter_type == "mutuals":
            query = query.where(CachedAccount.is_followed_by == True)
            query = query.order_by(desc(CachedAccount.last_status_at))

        elif filter_type == "bots":
            # Strict flag check only
            query = query.where(CachedAccount.bot == True)
            query = query.order_by(desc(CachedAccount.last_status_at))

        else:  # "all", "chatty", "broadcasters"
            query = query.order_by(desc(CachedAccount.last_status_at))

        # Execute Query
        query = query.limit(100)
        res = await session.execute(query)
        accounts = res.scalars().all()

        # 4. Post-processing for Chatty / Broadcasters (Reply Ratios)
        if filter_type in ("chatty", "broadcasters"):
            accounts_with_stats = []

            for acc in accounts:
                # Count total posts and replies for this account within this identity context
                total_stmt = select(func.count(CachedPost.id)).where(
                    and_(
                        CachedPost.author_id == acc.id,
                        CachedPost.meta_account_id == meta.id,
                        CachedPost.fetched_by_identity_id == identity_id,
                    )
                )
                reply_stmt = select(func.count(CachedPost.id)).where(
                    and_(
                        CachedPost.author_id == acc.id,
                        CachedPost.is_reply == True,
                        CachedPost.meta_account_id == meta.id,
                        CachedPost.fetched_by_identity_id == identity_id,
                    )
                )

                total_posts = (await session.execute(total_stmt)).scalar() or 0
                reply_posts = (await session.execute(reply_stmt)).scalar() or 0

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

        # Convert to dicts
        return [
            {
                "id": a.id,
                "acct": a.acct,
                "display_name": a.display_name,
                "avatar": a.avatar,
                "url": a.url,
                "note": a.note,
                "bot": a.bot,
                "last_status_at": (
                    a.last_status_at.isoformat() if a.last_status_at else None
                ),
            }
            for a in accounts
        ]


@router.get("/{acct}")
async def get_account_info(
    acct: str,
    identity_id: int = Query(..., description="The context Identity ID"),
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    """
    Get cached account information by acct string for a specific identity.
    """
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
        # Strict lookup: meta + identity + acct
        stmt = select(CachedAccount).where(
            and_(
                CachedAccount.acct == acct,
                CachedAccount.meta_account_id == meta.id,
                CachedAccount.mastodon_identity_id == identity_id,
            )
        )

        account = (await session.execute(stmt)).scalar_one_or_none()

        if not account:
            raise HTTPException(
                404, f"Account {acct} not found for identity {identity_id}"
            )

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


@router.post("/{acct}/sync")
async def sync_account(
    acct: str,
    identity_id: int = Query(..., description="The context Identity ID"),
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    """Sync a specific user's timeline using a specific identity."""
    if acct == "everyone":
        return {"status": "skipped", "message": "Cannot sync virtual user"}

    async with async_session() as session:
        stmt = select(MastodonIdentity).where(
            and_(
                MastodonIdentity.id == identity_id,
                MastodonIdentity.meta_account_id == meta.id,
            )
        )
        identity = (await session.execute(stmt)).scalar_one_or_none()

        if not identity:
            raise HTTPException(404, "Identity not found")

    # Call the identity-aware sync function
    result = await sync_user_timeline_for_identity(
        meta_id=meta.id, identity=identity, acct=acct, force=True
    )
    return result
