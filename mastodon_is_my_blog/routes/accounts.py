# mastodon_is_my_blog/routes/accounts.py
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, desc, func, or_, select

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
    - all: All accounts in the blog roll
    - top_friends: Accounts you follow (sorted by activity)
    - mutuals: Accounts that follow you back (mutual follows)
    - chatty: Accounts with high reply activity
    - broadcasters: Accounts with low reply activity (mostly posts)
    - bots: Accounts identified as bots (placeholder logic)
    """
    async with async_session() as session:
        # Simple, direct query on CachedAccount. No aggregation needed.
        query = select(CachedAccount).where(
            and_(
                CachedAccount.meta_account_id == meta.id,
                CachedAccount.mastodon_identity_id == identity_id,
                or_(
                    CachedAccount.last_status_at != None,
                    CachedAccount.is_following == True,
                ),
            )
        )

        # Apply filter logic
        if filter_type == "top_friends":
            query = query.where(CachedAccount.is_following == True)
            query = query.order_by(desc(CachedAccount.last_status_at))

        elif filter_type == "mutuals":
            query = query.where(
                and_(
                    CachedAccount.is_following == True,
                    CachedAccount.is_followed_by == True,
                )
            )
            query = query.order_by(desc(CachedAccount.last_status_at))

        elif filter_type == "bots":
            query = query.where(
                or_(
                    CachedAccount.bot == True,
                    CachedAccount.display_name.ilike("%bot%"),
                    CachedAccount.acct.ilike("%bot%"),
                )
            )
            query = query.order_by(desc(CachedAccount.last_status_at))

        else:  # "all", "chatty", "broadcasters"
            query = query.order_by(desc(CachedAccount.last_status_at))

        query = query.limit(100)
        res = await session.execute(query)
        accounts = res.scalars().all()

        # For chatty/broadcasters, calculate reply ratios
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
