# mastodon_is_my_blog/routest/accounts.py
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

router = APIRouter(prefix="/api/accounts", tags=["admin"])


@router.get("/blogroll")
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


@router.get("/{acct}")
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


@router.post("/{acct}/sync")
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
