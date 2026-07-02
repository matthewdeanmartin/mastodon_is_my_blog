# mastodon_is_my_blog/routes/new_friends.py
"""
New Friends — discover accounts your friends follow that you don't yet.

Endpoints:
  GET  /api/new-friends/candidates?identity_id=...&...
  POST /api/new-friends/refresh?identity_id=...&...
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from mastodon.errors import MastodonError
from sqlalchemy import select

from mastodon_is_my_blog.blogroll import (
    BLOGROLL_CATEGORY_TITLES,
    BLOGROLL_NOTIFICATION_TYPES,
    categorize_blogroll_account,
)
from mastodon_is_my_blog.datetime_helpers import to_naive_utc, utc_now
from mastodon_is_my_blog.mastodon_apis.masto_client import client_from_identity
from mastodon_is_my_blog.queries import get_current_meta_account
from mastodon_is_my_blog.store import (
    CachedAccount,
    CachedNotification,
    FriendsOfFriendsCache,
    MastodonIdentity,
    MetaAccount,
    async_session,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/new-friends", tags=["new-friends"])

CACHE_TTL_HOURS = 6
DEFAULT_SCAN_SECONDS = 30
HTML_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    return HTML_TAG_RE.sub("", text or "").strip()


async def resolve_identity(meta_id: int, identity_id: int) -> MastodonIdentity:
    async with async_session() as session:
        stmt = select(MastodonIdentity).where(
            MastodonIdentity.id == identity_id,
            MastodonIdentity.meta_account_id == meta_id,
        )
        identity = (await session.execute(stmt)).scalar_one_or_none()
        if not identity:
            raise HTTPException(404, "Identity not found")
        return identity


def _is_cache_fresh(fetched_at: datetime | None) -> bool:
    # Coerce to naive UTC before subtracting — see datetime_helpers.py.
    naive = to_naive_utc(fetched_at)
    if naive is None:
        return False
    return (utc_now() - naive) < timedelta(hours=CACHE_TTL_HOURS)


async def save_scan_progress(
    identity_id: int,
    candidates: list[dict],
    source_friend_ids: list[str],
    next_friend_index: int,
    max_friends: int,
    blog_roll_filter: str | None,
    complete: bool,
) -> None:
    """Commit a scan checkpoint so cancellation or restart can resume it."""
    async with async_session() as session:
        existing = (
            await session.execute(
                select(FriendsOfFriendsCache).where(
                    FriendsOfFriendsCache.identity_id == identity_id
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            existing = FriendsOfFriendsCache(identity_id=identity_id)
            session.add(existing)
        existing.fetched_at = utc_now()
        existing.data_json = json.dumps(candidates)
        existing.source_friend_ids_json = json.dumps(source_friend_ids)
        existing.next_friend_index = next_friend_index
        existing.scan_max_friends = max_friends
        existing.scan_blog_roll_filter = blog_roll_filter
        existing.scan_complete = complete
        await session.commit()


def candidate_from_account(acc: dict, followed_by_ids: set[str]) -> dict:
    created_raw = acc.get("created_at")
    last_status_raw = acc.get("last_status_at")
    return {
        "id": str(acc.get("id", "")),
        "acct": acc.get("acct", ""),
        "display_name": acc.get("display_name", ""),
        "avatar": acc.get("avatar", ""),
        "url": acc.get("url", ""),
        "note": strip_html(acc.get("note", "")),
        "bot": bool(acc.get("bot", False)),
        "locked": bool(acc.get("locked", False)),
        "followers_count": acc.get("followers_count", 0),
        "following_count": acc.get("following_count", 0),
        "statuses_count": acc.get("statuses_count", 0),
        "created_at": (
            created_raw.isoformat()
            if isinstance(created_raw, datetime)
            else str(created_raw) if created_raw else None
        ),
        "last_status_at": (
            last_status_raw.isoformat()
            if isinstance(last_status_raw, datetime)
            else str(last_status_raw) if last_status_raw else None
        ),
        "followed_by_ids": sorted(followed_by_ids),
        "followed_by_count": len(followed_by_ids),
    }


async def _fetch_and_cache(
    meta_id: int,
    identity: MastodonIdentity,
    max_friends: int,
    blog_roll_filter: str | None,
    max_duration_seconds: int = DEFAULT_SCAN_SECONDS,
) -> list[dict]:
    """
    Fetch friends-of-friends with durable per-friend checkpoints.

    An incomplete scan with the same inputs resumes at its next friend. A
    completed scan (or changed inputs) starts over. Work stops at the duration
    limit and the partial result remains readable.
    """
    if blog_roll_filter and blog_roll_filter not in BLOGROLL_CATEGORY_TITLES:
        raise HTTPException(
            400,
            f"Unknown blog_roll_filter {blog_roll_filter!r}; expected one of {sorted(BLOGROLL_CATEGORY_TITLES)}",
        )

    client = client_from_identity(identity)

    async with async_session() as session:
        # Get accounts we currently follow — these are our "friends" to expand
        # from. Most recently active first so the max_friends slice below
        # spends its API budget on live accounts, not dormant ones.
        stmt = (
            select(CachedAccount)
            .where(
                CachedAccount.meta_account_id == meta_id,
                CachedAccount.mastodon_identity_id == identity.id,
                CachedAccount.is_following.is_(True),
            )
            .order_by(CachedAccount.last_status_at.desc().nulls_last())
        )
        friends = list((await session.execute(stmt)).scalars())

        if friends and blog_roll_filter:
            # Only expand from friends in the requested blogroll category,
            # using the same categorization as the blogroll itself.
            notif_stmt = select(CachedNotification.account_id).where(
                CachedNotification.meta_account_id == meta_id,
                CachedNotification.identity_id == identity.id,
                CachedNotification.type.in_(BLOGROLL_NOTIFICATION_TYPES),
            )
            interacted_accounts = {
                (identity.id, row[0])
                for row in (await session.execute(notif_stmt)).all()
            }
            expandable = [
                f
                for f in friends
                if categorize_blogroll_account(
                    f, interacted_accounts=interacted_accounts
                )
                == blog_roll_filter
            ]
        else:
            expandable = friends

    if not friends:
        await save_scan_progress(
            identity.id, [], [], 0, max_friends, blog_roll_filter, True
        )
        return []

    # Build a set of account IDs we already follow — used to filter candidates.
    # This must cover ALL follows, not just the expandable subset.
    already_following_ids: set[str] = {f.id for f in friends}
    # Also exclude ourselves
    already_following_ids.add(identity.account_id)

    # Limit how many friends we expand from (controls API call volume).
    friends_to_expand = expandable[:max_friends]
    source_friend_ids = [friend.id for friend in friends_to_expand]

    async with async_session() as session:
        cached = (
            await session.execute(
                select(FriendsOfFriendsCache).where(
                    FriendsOfFriendsCache.identity_id == identity.id
                )
            )
        ).scalar_one_or_none()

    can_resume = bool(
        cached
        and not cached.scan_complete
        and cached.scan_max_friends == max_friends
        and cached.scan_blog_roll_filter == blog_roll_filter
        and json.loads(cached.source_friend_ids_json or "[]") == source_friend_ids
    )
    candidate_map: dict[str, dict]
    if can_resume and cached is not None:
        candidates = json.loads(cached.data_json or "[]")
        candidate_map = {candidate["id"]: candidate for candidate in candidates}
        next_friend_index = cached.next_friend_index
    else:
        candidate_map = {}
        next_friend_index = 0
        await save_scan_progress(
            identity.id,
            [],
            source_friend_ids,
            next_friend_index,
            max_friends,
            blog_roll_filter,
            not source_friend_ids,
        )

    logger.info(
        "new_friends: expanding %d friends (of %d total follows) for identity %d",
        len(friends_to_expand),
        len(friends),
        identity.id,
    )

    # Sequential calls respect the instance and give us a natural checkpoint.
    deadline = time.monotonic() + max_duration_seconds
    for index in range(next_friend_index, len(friends_to_expand)):
        friend = friends_to_expand[index]
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            results = await asyncio.wait_for(
                asyncio.to_thread(client.account_following, friend.id, limit=80),
                timeout=remaining,
            )
            for acc in results:
                acc_id = str(acc.get("id", ""))
                if not acc_id or acc_id in already_following_ids:
                    continue
                existing_candidate = candidate_map.get(acc_id)
                followed_by_ids = set(
                    existing_candidate.get("followed_by_ids", [])
                    if existing_candidate
                    else []
                )
                followed_by_ids.add(friend.id)
                candidate_map[acc_id] = candidate_from_account(acc, followed_by_ids)
        except TimeoutError:
            break
        except MastodonError as exc:
            logger.warning("Failed to get following for %s: %s", friend.acct, exc)
        next_friend_index = index + 1
        candidates = list(candidate_map.values())
        await save_scan_progress(
            identity.id,
            candidates,
            source_friend_ids,
            next_friend_index,
            max_friends,
            blog_roll_filter,
            next_friend_index >= len(friends_to_expand),
        )

    candidates = list(candidate_map.values())
    # Save the timeout checkpoint even when no request completed in this run.
    await save_scan_progress(
        identity.id,
        candidates,
        source_friend_ids,
        next_friend_index,
        max_friends,
        blog_roll_filter,
        next_friend_index >= len(friends_to_expand),
    )

    logger.info(
        "new_friends: cached %d candidates for identity %d",
        len(candidates),
        identity.id,
    )
    return candidates


def _apply_filters(
    candidates: list[dict],
    already_following_ids: set[str],
    min_posts: int,
    active_since_days: int,
    bio_contains: str,
) -> list[dict]:
    cutoff = utc_now() - timedelta(days=active_since_days)
    bio_lower = bio_contains.lower().strip()

    result = []
    for c in candidates:
        if c["id"] in already_following_ids:
            continue
        if (c.get("statuses_count") or 0) < min_posts:
            continue
        if c.get("last_status_at"):
            try:
                last = datetime.fromisoformat(
                    c["last_status_at"].replace("Z", "+00:00")
                )
                last_naive = last.replace(tzinfo=None)
                if last_naive < cutoff:
                    continue
            except Exception:
                pass
        if bio_lower and bio_lower not in c.get("note", "").lower():
            continue
        result.append(c)
    return result


@router.get("/candidates")
async def get_candidates(
    identity_id: int = Query(...),
    min_posts: int = Query(1, ge=0),
    active_since_days: int = Query(365, ge=1, le=3650),
    bio_contains: str = Query(""),
    max_friends: int = Query(
        50,
        ge=1,
        le=500,
        description="Max number of your friends to expand from. Each costs 1 API call.",
    ),
    blog_roll_filter: str | None = Query(
        None,
        description="Restrict source friends to this blogroll filter (e.g. top_friends, mutuals)",
    ),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    """
    Return friends-of-friends candidates not yet followed.
    Uses a 6-hour server-side cache per identity to avoid hammering the API.
    """
    identity = await resolve_identity(meta.id, identity_id)

    async with async_session() as session:
        cached = (
            await session.execute(
                select(FriendsOfFriendsCache).where(
                    FriendsOfFriendsCache.identity_id == identity_id
                )
            )
        ).scalar_one_or_none()

    if cached:
        candidates = json.loads(cached.data_json or "[]")
        cache_hit = True
        fetched_at = cached.fetched_at.isoformat() if cached.fetched_at else None
        cache_fresh = _is_cache_fresh(cached.fetched_at)
        scan_complete = cached.scan_complete
        scanned_friends = cached.next_friend_index
        total_friends = len(json.loads(cached.source_friend_ids_json or "[]"))
    else:
        # Reads are deliberately cheap. Scanning is an explicit POST operation,
        # never a surprise side effect of opening the page or applying filters.
        candidates = []
        cache_hit = False
        fetched_at = None
        cache_fresh = False
        scan_complete = True
        scanned_friends = 0
        total_friends = 0

    # Get current following set to exclude (cache may be slightly stale)
    async with async_session() as session:
        stmt = select(CachedAccount.id).where(
            CachedAccount.meta_account_id == meta.id,
            CachedAccount.mastodon_identity_id == identity_id,
            CachedAccount.is_following.is_(True),
        )
        already_following_ids = {row[0] for row in (await session.execute(stmt)).all()}
    already_following_ids.add(identity.account_id)

    total_downloaded = len(candidates)
    filtered = _apply_filters(
        candidates, already_following_ids, min_posts, active_since_days, bio_contains
    )

    total = len(filtered)
    page = [
        {key: value for key, value in candidate.items() if key != "followed_by_ids"}
        for candidate in filtered[offset : offset + limit]
    ]

    return {
        "candidates": page,
        "total": total,
        "total_downloaded": total_downloaded,
        "offset": offset,
        "limit": limit,
        "cache_hit": cache_hit,
        "cache_fresh": cache_fresh,
        "fetched_at": fetched_at,
        "scan_complete": scan_complete,
        "scanned_friends": scanned_friends,
        "total_friends": total_friends,
    }


@router.post("/refresh")
async def refresh_candidates(
    identity_id: int = Query(...),
    max_friends: int = Query(50, ge=1, le=500),
    blog_roll_filter: str | None = Query(None),
    max_duration_seconds: int = Query(
        DEFAULT_SCAN_SECONDS,
        ge=1,
        le=300,
        description="Stop and checkpoint after this many seconds; call again to resume.",
    ),
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    """
    Force a cache refresh (runs synchronously; use for on-demand refresh).
    """
    identity = await resolve_identity(meta.id, identity_id)
    candidates = await _fetch_and_cache(
        meta.id,
        identity,
        max_friends,
        blog_roll_filter,
        max_duration_seconds=max_duration_seconds,
    )
    async with async_session() as session:
        cached = (
            await session.execute(
                select(FriendsOfFriendsCache).where(
                    FriendsOfFriendsCache.identity_id == identity_id
                )
            )
        ).scalar_one()
    return {
        "status": "complete" if cached.scan_complete else "partial",
        "candidates_fetched": len(candidates),
        "scan_complete": cached.scan_complete,
        "scanned_friends": cached.next_friend_index,
        "total_friends": len(json.loads(cached.source_friend_ids_json or "[]")),
    }
