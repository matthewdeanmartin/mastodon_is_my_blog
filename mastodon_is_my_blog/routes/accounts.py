# mastodon_is_my_blog/routes/accounts.py
import json
import logging
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, desc, exists, func, select

from mastodon_is_my_blog.account_catchup_runner import (
    cancel_job as cancel_account_catchup_job,
)
from mastodon_is_my_blog.account_catchup_runner import (
    get_job as get_account_catchup_job,
)
from mastodon_is_my_blog.account_catchup_runner import (
    job_status as account_catchup_job_status,
)
from mastodon_is_my_blog.account_catchup_runner import (
    start_job as start_account_catchup_job,
)
from mastodon_is_my_blog.queries import (
    get_current_meta_account,
    sync_user_timeline_for_identity,
)
from mastodon_is_my_blog.store import (
    CachedAccount,
    CachedNotification,
    CachedPost,
    MastodonIdentity,
    MetaAccount,
    async_session,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


async def _get_identity(meta: MetaAccount, identity_id: int) -> MastodonIdentity:
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
        return identity


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
    - readers: Anyone who has reposted me (follow or not)
    - mutuals: I follow them, they follow me
    - chatty: High reply ratio (> 50%) among people I follow
    - broadcasters: Low reply ratio (< 20%) among people I follow
    - idols: I follow them, they don't follow me, but I've replied to them
    - bots: Strictly identified as bots
    - lively: People I follow with a cached post in the last 30 days
    - graveyard: People I follow with no cached posts, or last cached post older than 90 days
    - parasocials: I follow them, >10k followers, they don't follow me
    - other: People I follow who don't fit any other named category
    """
    async with async_session() as session:
        # Get the current identity to know "My Account ID" for the "Replied to Me" check
        stmt = select(MastodonIdentity).where(MastodonIdentity.id == identity_id)
        identity = (await session.execute(stmt)).scalar_one_or_none()
        if not identity:
            raise HTTPException(404, "Identity not found")

        _ = identity.account_id

        # Base Query: STRICTLY people I follow
        # This removes the "weirdos" (boost-only strangers) from all views.
        # NOTE: the 'readers' branch overrides this below to include non-followed reposters.
        query = select(CachedAccount).where(
            and_(
                CachedAccount.meta_account_id == meta.id,
                CachedAccount.mastodon_identity_id == identity_id,
                CachedAccount.is_following.is_(True),
            )
        )

        # Apply specific filters
        if filter_type == "readers":
            # Anyone who has ever reposted me — follow or not.
            # This drops the is_following gate so we surface fans we don't follow back.
            has_reblog = exists(
                select(1).where(
                    and_(
                        CachedNotification.account_id == CachedAccount.id,
                        CachedNotification.meta_account_id == meta.id,
                        CachedNotification.identity_id == identity_id,
                        CachedNotification.type == "reblog",
                    )
                )
            )
            query = (
                select(CachedAccount)
                .where(
                    and_(
                        CachedAccount.meta_account_id == meta.id,
                        CachedAccount.mastodon_identity_id == identity_id,
                        has_reblog,
                    )
                )
                .order_by(desc(CachedAccount.last_status_at))
            )

        elif filter_type == "top_friends":
            if filter_type == "top_friends":
                # Mutuals who have interacted via notifications
                # This includes: mentions, replies, favorites, reblogs
                query = query.where(CachedAccount.is_followed_by.is_(True))

                # Subquery: Check if there's ANY notification from this account
                has_interaction = exists(
                    select(1).where(
                        and_(
                            CachedNotification.account_id == CachedAccount.id,
                            CachedNotification.meta_account_id == meta.id,
                            CachedNotification.identity_id == identity_id,
                            CachedNotification.type.in_(
                                ["mention", "favourite", "reblog", "status"]
                            ),
                        )
                    )
                )
                query = query.where(has_interaction)

                # Sort by most recent interaction
                # We can add a subquery to get the latest notification time
                query = query.order_by(desc(CachedAccount.last_status_at))

        elif filter_type == "mutuals":
            query = query.where(CachedAccount.is_followed_by.is_(True))
            query = query.order_by(desc(CachedAccount.last_status_at))

        elif filter_type == "bots":
            # Strict flag check only
            query = query.where(CachedAccount.bot.is_(True))
            query = query.order_by(desc(CachedAccount.last_status_at))

        elif filter_type == "idols":
            # People I follow, that I reply to, but who don't follow me AND haven't
            # sent me any notifications. Once they reply/mention/favourite me they
            # graduate out of Idols into Top Friends / Fans.
            query = query.where(CachedAccount.is_followed_by.is_(False))
            has_outbound = exists(
                select(1).where(
                    and_(
                        CachedPost.meta_account_id == meta.id,
                        CachedPost.fetched_by_identity_id == identity_id,
                        CachedPost.author_acct == identity.acct,
                        CachedPost.in_reply_to_account_id == CachedAccount.id,
                    )
                )
            )
            has_inbound_notif = exists(
                select(1).where(
                    and_(
                        CachedNotification.meta_account_id == meta.id,
                        CachedNotification.identity_id == identity_id,
                        CachedNotification.account_id == CachedAccount.id,
                    )
                )
            )
            query = query.where(has_outbound, ~has_inbound_notif)
            query = query.order_by(desc(CachedAccount.last_status_at))

        elif filter_type == "lively":
            # People I follow who have posted recently — at least one cached post in the last 30 days.
            cutoff = datetime.utcnow() - timedelta(days=30)
            query = query.where(CachedAccount.last_status_at >= cutoff)
            query = query.order_by(desc(CachedAccount.last_status_at))

        elif filter_type == "graveyard":
            # People I follow whose account has gone quiet — no cached posts, or last post older than 90 days.
            cutoff = datetime.utcnow() - timedelta(days=90)
            query = query.where(
                (CachedAccount.last_status_at.is_(None))
                | (CachedAccount.last_status_at < cutoff)
            )
            query = query.order_by(CachedAccount.last_status_at.asc().nullsfirst())

        elif filter_type == "parasocials":
            # I follow them, they have >10k followers, they don't follow me back.
            # These are the celebrities I consume but who don't know I exist.
            query = query.where(
                CachedAccount.is_followed_by.is_(False),
                CachedAccount.followers_count > 10000,
            )
            query = query.order_by(desc(CachedAccount.followers_count))

        elif filter_type == "other":
            # People I follow who don't fall into any named category.
            # Excludes: mutuals, bots, idols (replied to non-follower), readers (reposted me)
            thirty_days_ago = datetime.utcnow() - timedelta(days=30)
            is_mutual = CachedAccount.is_followed_by.is_(True)
            is_bot = CachedAccount.bot.is_(True)
            is_lively = CachedAccount.last_status_at >= thirty_days_ago
            has_notification = exists(
                select(1).where(
                    and_(
                        CachedNotification.account_id == CachedAccount.id,
                        CachedNotification.meta_account_id == meta.id,
                        CachedNotification.identity_id == identity_id,
                    )
                )
            )
            has_outbound = exists(
                select(1).where(
                    and_(
                        CachedPost.meta_account_id == meta.id,
                        CachedPost.fetched_by_identity_id == identity_id,
                        CachedPost.author_acct == identity.acct,
                        CachedPost.in_reply_to_account_id == CachedAccount.id,
                    )
                )
            )
            query = query.where(
                ~is_mutual,
                ~is_bot,
                ~is_lively,
                ~has_notification,
                ~has_outbound,
            )
            query = query.order_by(desc(CachedAccount.last_status_at))

        else:  # "all", "chatty", "broadcasters"
            query = query.order_by(desc(CachedAccount.last_status_at))

        # Execute Query
        query = query.limit(100)
        res = await session.execute(query)
        accounts = res.scalars().all()

        # Post-processing for Chatty / Broadcasters using materialized stats
        if filter_type in ("chatty", "broadcasters"):
            accounts_with_ratio = []
            for acc in accounts:
                total = acc.cached_post_count
                if total < 5:
                    continue
                ratio = acc.cached_reply_count / total
                if filter_type == "chatty" and ratio > 0.5:
                    accounts_with_ratio.append((acc, ratio))
                elif filter_type == "broadcasters" and ratio < 0.2:
                    accounts_with_ratio.append((acc, ratio))

            reverse = filter_type == "chatty"
            accounts_with_ratio.sort(key=lambda x: x[1], reverse=reverse)
            accounts = [acc for acc, _ in accounts_with_ratio[:40]]

        account_ids = [a.id for a in accounts]

        # Count unseen posts per account in one query
        unseen_counts: dict[str, int] = {}
        if account_ids:
            from mastodon_is_my_blog.store import SeenPost
            unseen_stmt = (
                select(
                    CachedPost.author_id,
                    func.count(CachedPost.id).label("unseen"),
                )
                .outerjoin(
                    SeenPost,
                    and_(
                        CachedPost.id == SeenPost.post_id,
                        SeenPost.meta_account_id == meta.id,
                    ),
                )
                .where(
                    and_(
                        CachedPost.meta_account_id == meta.id,
                        CachedPost.fetched_by_identity_id == identity_id,
                        CachedPost.author_id.in_(account_ids),
                        CachedPost.content_hub_only.is_(False),
                        SeenPost.post_id.is_(None),
                    )
                )
                .group_by(CachedPost.author_id)
            )
            for row in (await session.execute(unseen_stmt)).all():
                unseen_counts[row.author_id] = row.unseen

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
                "cached_post_count": a.cached_post_count or 0,
                "followers_count": a.followers_count or 0,
                "unseen_post_count": unseen_counts.get(a.id, 0),
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
            "cache_state": {
                "cached_posts": 0,
                "latest_cached_post_at": None,
                "is_stale": False,
                "stale_reason": "virtual_account",
            },
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
            except Exception:
                fields_data = []

        post_cache_stmt = select(
            func.count(CachedPost.id),
            func.max(CachedPost.created_at),
        ).where(
            and_(
                CachedPost.meta_account_id == meta.id,
                CachedPost.fetched_by_identity_id == identity_id,
                CachedPost.author_acct == acct,
            )
        )
        cached_posts, latest_cached_post_at = (
            await session.execute(post_cache_stmt)
        ).one()

        now = datetime.utcnow()
        latest_cached_post_at_naive = None
        if latest_cached_post_at is not None:
            latest_cached_post_at_naive = (
                latest_cached_post_at.replace(tzinfo=None)
                if latest_cached_post_at.tzinfo
                else latest_cached_post_at
            )
        is_stale = latest_cached_post_at_naive is None or (
            now - latest_cached_post_at_naive
        ) > timedelta(days=7)
        stale_reason = (
            "no_cached_posts"
            if latest_cached_post_at_naive is None
            else ("last_cached_post_older_than_7d" if is_stale else "fresh")
        )

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
            "last_status_at": (
                account.last_status_at.isoformat() if account.last_status_at else None
            ),
            "is_following": account.is_following,
            "is_followed_by": account.is_followed_by,
            "cache_state": {
                "cached_posts": int(cached_posts or 0),
                "latest_cached_post_at": (
                    latest_cached_post_at.isoformat() if latest_cached_post_at else None
                ),
                "is_stale": is_stale,
                "stale_reason": stale_reason,
            },
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

    identity = await _get_identity(meta, identity_id)

    # Call the identity-aware sync function
    result = await sync_user_timeline_for_identity(
        meta_id=meta.id, identity=identity, acct=acct, force=True
    )
    return result


@router.post("/{acct}/catchup")
async def start_account_catchup(
    acct: str,
    mode: Literal["recent", "deep"] = Query("recent", pattern="^(recent|deep)$"),
    identity_id: int = Query(..., description="The context Identity ID"),
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    if acct == "everyone":
        raise HTTPException(400, "Cannot catch up virtual user")

    identity = await _get_identity(meta, identity_id)
    try:
        job = await start_account_catchup_job(meta, identity, acct, mode=mode)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return account_catchup_job_status(job)


@router.get("/{acct}/catchup/status")
async def account_catchup_status(
    acct: str,
    identity_id: int = Query(..., description="The context Identity ID"),
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    if acct == "everyone":
        raise HTTPException(400, "Virtual user has no catch-up job")

    identity = await _get_identity(meta, identity_id)
    job = get_account_catchup_job(meta.id, identity.id, acct)
    if job is None:
        raise HTTPException(404, "No catch-up job found for this account")
    return account_catchup_job_status(job)


@router.delete("/{acct}/catchup")
async def cancel_account_catchup(
    acct: str,
    identity_id: int = Query(..., description="The context Identity ID"),
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    if acct == "everyone":
        raise HTTPException(400, "Virtual user has no catch-up job")

    identity = await _get_identity(meta, identity_id)
    cancelled = cancel_account_catchup_job(meta.id, identity.id, acct)
    if not cancelled:
        raise HTTPException(404, "No running catch-up job for this account")
    return {"cancelled": True}
