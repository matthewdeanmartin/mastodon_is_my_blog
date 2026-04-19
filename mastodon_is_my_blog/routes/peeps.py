# mastodon_is_my_blog/routes/peeps.py
"""
Peeps Finder — engagement intelligence layer.

Endpoints:
  GET  /api/peeps/matrix?identity_id=...&window_days=180
  GET  /api/peeps/dossier/{acct}?identity_id=...
  POST /api/peeps/dossier/{acct}/deep-fetch?identity_id=...
  POST /api/peeps/dossier/{acct}/follow?identity_id=...
  POST /api/peeps/dossier/{acct}/unfollow?identity_id=...
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select

from mastodon_is_my_blog.account_catchup_runner import (
    job_status as account_catchup_job_status,
)
from mastodon_is_my_blog.account_catchup_runner import (
    start_job as start_account_catchup_job,
)
from mastodon_is_my_blog.engagement_scoring import score_interactions
from mastodon_is_my_blog.mastodon_apis.follow_actions import (
    follow_account,
    unfollow_account,
)
from mastodon_is_my_blog.queries import (
    get_current_meta_account,
)
from mastodon_is_my_blog.store import (
    CachedAccount,
    CachedMyFavourite,
    CachedNotification,
    CachedPost,
    MastodonIdentity,
    MetaAccount,
    async_session,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/peeps", tags=["peeps"])


async def _resolve_identity(meta_id: int, identity_id: int) -> MastodonIdentity:
    async with async_session() as session:
        stmt = select(MastodonIdentity).where(
            MastodonIdentity.id == identity_id,
            MastodonIdentity.meta_account_id == meta_id,
        )
        identity = (await session.execute(stmt)).scalar_one_or_none()
        if not identity:
            raise HTTPException(404, "Identity not found")
        return identity


def _age_days(dt: datetime | None, now: datetime) -> float:
    if dt is None:
        return 0.0
    naive_dt = dt.replace(tzinfo=None) if dt.tzinfo else dt
    delta = now - naive_dt
    return max(0.0, delta.total_seconds() / 86400)


@router.get("/matrix")
async def get_engagement_matrix(
    identity_id: int = Query(...),
    window_days: int = Query(180, ge=1, le=3650),
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    """Return the four-quadrant engagement matrix for an identity."""
    identity = await _resolve_identity(meta.id, identity_id)
    cutoff = datetime.utcnow() - timedelta(days=window_days)
    now = datetime.utcnow()

    async with async_session() as session:
        # --- Inbound: them→me (notifications) ---
        notif_stmt = select(
            CachedNotification.account_id,
            CachedNotification.account_acct,
            CachedNotification.type,
            CachedNotification.created_at,
        ).where(
            CachedNotification.meta_account_id == meta.id,
            CachedNotification.identity_id == identity_id,
            CachedNotification.created_at >= cutoff,
        )
        notif_rows = (await session.execute(notif_stmt)).all()

        # Group inbound by account_id
        inbound: dict[str, list[dict]] = {}
        inbound_acct: dict[str, str] = {}
        for n_row in notif_rows:
            if n_row.account_id not in inbound:
                inbound[n_row.account_id] = []
            inbound[n_row.account_id].append(
                {
                    "type": n_row.type,
                    "age_days": _age_days(n_row.created_at, now),
                }
            )
            inbound_acct[n_row.account_id] = n_row.account_acct

        # --- Outbound: me→them via cached_posts (replies/reblogs I authored) ---
        my_acct = identity.acct
        # Replies by me to others
        reply_stmt = select(
            CachedPost.in_reply_to_account_id,
            CachedPost.created_at,
        ).where(
            CachedPost.meta_account_id == meta.id,
            CachedPost.fetched_by_identity_id == identity_id,
            CachedPost.author_acct == my_acct,
            CachedPost.is_reply.is_(True),
            CachedPost.created_at >= cutoff,
            CachedPost.in_reply_to_account_id.is_not(None),
        )
        reply_rows = (await session.execute(reply_stmt)).all()

        # Reblogs by me
        reblog_stmt = select(
            CachedPost.in_reply_to_account_id,
            CachedPost.author_id,
            CachedPost.created_at,
            CachedPost.is_reblog,
        ).where(
            CachedPost.meta_account_id == meta.id,
            CachedPost.fetched_by_identity_id == identity_id,
            CachedPost.is_reblog.is_(True),
            CachedPost.created_at >= cutoff,
        )
        reblog_rows = (await session.execute(reblog_stmt)).all()

        # Outbound favourites
        fav_stmt = select(
            CachedMyFavourite.target_account_id,
            CachedMyFavourite.target_acct,
            CachedMyFavourite.favourited_at,
        ).where(
            CachedMyFavourite.meta_account_id == meta.id,
            CachedMyFavourite.identity_id == identity_id,
            CachedMyFavourite.favourited_at >= cutoff,
        )
        fav_rows = (await session.execute(fav_stmt)).all()

        # Group outbound by account_id
        outbound: dict[str, list[dict]] = {}
        for r_row in reply_rows:
            account_id = str(r_row.in_reply_to_account_id)
            if account_id not in outbound:
                outbound[account_id] = []
            outbound[account_id].append(
                {"type": "mention", "age_days": _age_days(r_row.created_at, now)}
            )

        for f_row in fav_rows:
            account_id = str(f_row.target_account_id)
            if account_id not in outbound:
                outbound[account_id] = []
            outbound[account_id].append(
                {"type": "favourite", "age_days": _age_days(f_row.favourited_at, now)}
            )

        # Gather all account_ids we need
        all_account_ids = set(inbound.keys()) | set(outbound.keys())

        # Fetch CachedAccount records for these accounts
        accounts_map: dict[str, CachedAccount] = {}
        if all_account_ids:
            acct_stmt = select(CachedAccount).where(
                CachedAccount.meta_account_id == meta.id,
                CachedAccount.mastodon_identity_id == identity_id,
                CachedAccount.id.in_(all_account_ids),
            )
            for ca_obj in (await session.execute(acct_stmt)).scalars():
                accounts_map[ca_obj.id] = ca_obj

    # Score each account
    scored: dict[str, dict] = {}
    for account_id in all_account_ids:
        in_score = score_interactions(inbound.get(account_id, []))
        out_score = score_interactions(outbound.get(account_id, []))
        ca = accounts_map.get(account_id)
        scored[account_id] = {
            "account_id": account_id,
            "acct": ca.acct if ca else inbound_acct.get(account_id, ""),
            "display_name": ca.display_name if ca else "",
            "avatar": ca.avatar if ca else "",
            "is_following": ca.is_following if ca else False,
            "is_followed_by": ca.is_followed_by if ca else False,
            "statuses_count": ca.statuses_count if ca else 0,
            "cached_post_count": ca.cached_post_count if ca else 0,
            "cached_reply_count": ca.cached_reply_count if ca else 0,
            "in_score": in_score,
            "out_score": out_score,
            "combined_score": in_score + out_score,
        }

    # Quadrant thresholds
    scores_in: list[float] = [v["in_score"] for v in scored.values()]
    scores_out: list[float] = [v["out_score"] for v in scored.values()]
    in_median = sorted(scores_in)[len(scores_in) // 2] if scores_in else 0.0
    out_median = sorted(scores_out)[len(scores_out) // 2] if scores_out else 0.0

    inner_circle = []
    fans = []
    idols = []
    broadcasters = []

    for entry in scored.values():
        in_s = entry["in_score"]
        out_s = entry["out_score"]
        is_following = entry["is_following"]
        post_count = entry["cached_post_count"]
        reply_count = entry["cached_reply_count"]

        high_in = in_s > in_median
        high_out = out_s > out_median

        if high_in and high_out:
            inner_circle.append(entry)
        elif high_in and not high_out and not is_following:
            fans.append(entry)
        elif high_out and not high_in:
            idols.append(entry)
        elif (
            is_following
            and entry["statuses_count"] > 100
            and in_s < 1.0
            and post_count > 0
            and (reply_count / post_count < 0.2 if post_count else True)
        ):
            broadcasters.append(entry)

    def sort_key(e: dict) -> float:
        return -e["combined_score"]

    inner_circle.sort(key=sort_key)
    fans.sort(key=lambda e: -e["in_score"])
    idols.sort(key=lambda e: -e["out_score"])
    broadcasters.sort(key=lambda e: -e["statuses_count"])

    return {
        "inner_circle": inner_circle[:20],
        "fans": fans[:20],
        "idols": idols[:20],
        "broadcasters": broadcasters[:20],
    }


@router.get("/dossier/{acct}")
async def get_dossier(
    acct: str,
    identity_id: int = Query(...),
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    """Return full dossier payload for a single account."""
    async with async_session() as session:
        ca_stmt = select(CachedAccount).where(
            CachedAccount.meta_account_id == meta.id,
            CachedAccount.mastodon_identity_id == identity_id,
            CachedAccount.acct == acct,
        )
        ca = (await session.execute(ca_stmt)).scalar_one_or_none()
        if not ca:
            raise HTTPException(404, f"Account {acct!r} not found in cache")

        # Interaction history windows
        now = datetime.utcnow()
        windows = {"30d": 30, "90d": 90, "180d": 180}
        interaction_history: dict[str, dict] = {}
        for label, days in windows.items():
            cutoff = now - timedelta(days=days)
            in_stmt = select(func.count(CachedNotification.id)).where(
                CachedNotification.meta_account_id == meta.id,
                CachedNotification.identity_id == identity_id,
                CachedNotification.account_id == ca.id,
                CachedNotification.created_at >= cutoff,
            )
            in_count = (await session.execute(in_stmt)).scalar_one()

            out_stmt = select(func.count(CachedMyFavourite.status_id)).where(
                CachedMyFavourite.meta_account_id == meta.id,
                CachedMyFavourite.identity_id == identity_id,
                CachedMyFavourite.target_account_id == ca.id,
                CachedMyFavourite.favourited_at >= cutoff,
            )
            out_count = (await session.execute(out_stmt)).scalar_one()

            interaction_history[label] = {
                "them_to_me": in_count,
                "me_to_them": out_count,
            }

        # Top hashtags from cached posts
        tag_stmt = (
            select(CachedPost.tags)
            .where(
                CachedPost.meta_account_id == meta.id,
                CachedPost.fetched_by_identity_id == identity_id,
                CachedPost.author_acct == acct,
                CachedPost.tags.is_not(None),
            )
            .limit(200)
        )
        tag_counter: dict[str, int] = {}
        for (tags_json,) in (await session.execute(tag_stmt)).all():
            try:
                tags = json.loads(tags_json) if tags_json else []
            except Exception:
                tags = []
            for tag in tags:
                tag_lower = tag.lower()
                tag_counter[tag_lower] = tag_counter.get(tag_lower, 0) + 1
        top_hashtags = sorted(tag_counter.items(), key=lambda x: -x[1])[:5]

        # Media profile
        media_stmt = select(
            func.count(CachedPost.id).label("total"),
            func.sum(
                CachedPost.has_media.cast(type_=__import__("sqlalchemy").Integer)
            ).label("has_media"),
            func.sum(
                CachedPost.has_video.cast(type_=__import__("sqlalchemy").Integer)
            ).label("has_video"),
            func.sum(
                CachedPost.has_link.cast(type_=__import__("sqlalchemy").Integer)
            ).label("has_link"),
        ).where(
            CachedPost.meta_account_id == meta.id,
            CachedPost.fetched_by_identity_id == identity_id,
            CachedPost.author_acct == acct,
        )
        media_row = (await session.execute(media_stmt)).one()
        total_posts = media_row.total or 0
        media_profile = {
            "total": total_posts,
            "has_media": media_row.has_media or 0,
            "has_video": media_row.has_video or 0,
            "has_link": media_row.has_link or 0,
        }

        # Staleness check
        latest_stmt = select(func.max(CachedPost.created_at)).where(
            CachedPost.meta_account_id == meta.id,
            CachedPost.fetched_by_identity_id == identity_id,
            CachedPost.author_acct == acct,
        )
        latest_post_at = (await session.execute(latest_stmt)).scalar_one_or_none()
        is_stale = (
            latest_post_at is None
            or (
                now
                - (
                    latest_post_at.replace(tzinfo=None)
                    if latest_post_at.tzinfo
                    else latest_post_at
                )
            ).days
            > 7
        )

        # Parse fields
        fields_data = []
        if ca.fields:
            try:
                fields_data = json.loads(ca.fields)
            except Exception:
                fields_data = []

    return {
        "id": ca.id,
        "acct": ca.acct,
        "display_name": ca.display_name,
        "avatar": ca.avatar,
        "header": ca.header,
        "url": ca.url,
        "note": ca.note,
        "fields": fields_data,
        "bot": ca.bot,
        "followers_count": ca.followers_count,
        "following_count": ca.following_count,
        "statuses_count": ca.statuses_count,
        "is_following": ca.is_following,
        "is_followed_by": ca.is_followed_by,
        "post_reply_ratio": (
            ca.cached_post_count / max(ca.cached_reply_count, 1)
            if ca.cached_post_count
            else None
        ),
        "top_hashtags": [{"tag": t, "count": c} for t, c in top_hashtags],
        "interaction_history": interaction_history,
        "media_profile": media_profile,
        "is_stale": is_stale,
    }


@router.post("/dossier/{acct}/deep-fetch")
async def deep_fetch_dossier(
    acct: str,
    identity_id: int = Query(...),
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    """Trigger a background deep catch-up of an account's posts."""
    identity = await _resolve_identity(meta.id, identity_id)
    try:
        job = await start_account_catchup_job(meta, identity, acct, mode="deep")
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return account_catchup_job_status(job)


@router.post("/dossier/{acct}/follow")
async def follow_acct(
    acct: str,
    identity_id: int = Query(...),
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    """Follow an account via the Mastodon API and update the local cache."""
    identity = await _resolve_identity(meta.id, identity_id)
    result = await follow_account(meta.id, identity, acct)
    return result


@router.post("/dossier/{acct}/unfollow")
async def unfollow_acct(
    acct: str,
    identity_id: int = Query(...),
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    """Unfollow an account via the Mastodon API and update the local cache."""
    identity = await _resolve_identity(meta.id, identity_id)
    result = await unfollow_account(meta.id, identity, acct)
    return result
