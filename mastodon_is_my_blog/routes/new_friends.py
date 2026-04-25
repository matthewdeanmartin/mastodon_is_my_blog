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
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from mastodon_is_my_blog.mastodon_apis.masto_client import client_from_identity
from mastodon_is_my_blog.queries import get_current_meta_account
from mastodon_is_my_blog.store import (
    CachedAccount,
    FriendsOfFriendsCache,
    MastodonIdentity,
    MetaAccount,
    async_session,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/new-friends", tags=["new-friends"])

CACHE_TTL_HOURS = 6
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
    if not fetched_at:
        return False
    age = datetime.utcnow() - fetched_at.replace(tzinfo=None) if fetched_at.tzinfo else datetime.utcnow() - fetched_at
    return age < timedelta(hours=CACHE_TTL_HOURS)


async def _fetch_and_cache(
    meta_id: int,
    identity: MastodonIdentity,
    max_friends: int,
    blog_roll_filter: str | None,
) -> list[dict]:
    """
    Core fetch: get the accounts our friends follow, de-duplicate, and persist to cache.
    """
    client = client_from_identity(identity)

    async with async_session() as session:
        # Get accounts we currently follow — these are our "friends" to expand from
        if blog_roll_filter:
            # Only expand from the subset matching the blogroll filter (active, mutuals, etc)
            # We reuse the same filter logic as the blogroll: fetch all followed accounts
            # and then let the blogroll filter restrict. For now we fetch all followed and
            # the max_friends limit controls volume.
            stmt = select(CachedAccount).where(
                CachedAccount.meta_account_id == meta_id,
                CachedAccount.mastodon_identity_id == identity.id,
                CachedAccount.is_following.is_(True),
            )
        else:
            stmt = select(CachedAccount).where(
                CachedAccount.meta_account_id == meta_id,
                CachedAccount.mastodon_identity_id == identity.id,
                CachedAccount.is_following.is_(True),
            )
        friends = list((await session.execute(stmt)).scalars())

    if not friends:
        return []

    # Build a set of account IDs we already follow — used to filter candidates
    already_following_ids: set[str] = {f.id for f in friends}
    # Also exclude ourselves
    already_following_ids.add(identity.account_id)

    # Limit how many friends we expand from (controls API call volume)
    friends_to_expand = friends[:max_friends]

    logger.info(
        "new_friends: expanding %d friends (of %d total follows) for identity %d",
        len(friends_to_expand),
        len(friends),
        identity.id,
    )

    # For each friend, fetch who they follow — one API call per friend
    # We run these sequentially (not concurrent) to be polite to the instance.
    # Each call fetches up to 80 accounts (one page); deep pagination not needed here.
    candidate_map: dict[str, dict] = {}  # mastodon_id -> account dict
    followed_by: dict[str, set[str]] = {}  # mastodon_id -> set of our friends' ids

    for friend in friends_to_expand:
        try:
            results = await asyncio.to_thread(client.account_following, friend.id, limit=80)
            if not results:
                continue
            for acc in results:
                acc_id = str(acc.get("id", ""))
                if not acc_id or acc_id in already_following_ids:
                    continue
                if acc_id not in candidate_map:
                    candidate_map[acc_id] = acc
                if acc_id not in followed_by:
                    followed_by[acc_id] = set()
                followed_by[acc_id].add(friend.id)
        except Exception as exc:
            logger.warning("Failed to get following for %s: %s", friend.acct, exc)

    # Build serialisable candidate list
    candidates: list[dict] = []
    for acc_id, acc in candidate_map.items():
        created_raw = acc.get("created_at")
        last_status_raw = acc.get("last_status_at")
        candidates.append(
            {
                "id": acc_id,
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
                "created_at": created_raw.isoformat() if hasattr(created_raw, "isoformat") else str(created_raw) if created_raw else None,
                "last_status_at": last_status_raw.isoformat() if hasattr(last_status_raw, "isoformat") else str(last_status_raw) if last_status_raw else None,
                "followed_by_count": len(followed_by.get(acc_id, set())),
            }
        )

    # Persist to cache
    data_json = json.dumps(candidates)
    async with async_session() as session:
        existing = (await session.execute(select(FriendsOfFriendsCache).where(FriendsOfFriendsCache.identity_id == identity.id))).scalar_one_or_none()

        if existing:
            existing.fetched_at = datetime.utcnow()
            existing.data_json = data_json
        else:
            session.add(
                FriendsOfFriendsCache(
                    identity_id=identity.id,
                    fetched_at=datetime.utcnow(),
                    data_json=data_json,
                )
            )
        await session.commit()

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
    cutoff = datetime.utcnow() - timedelta(days=active_since_days)
    bio_lower = bio_contains.lower().strip()

    result = []
    for c in candidates:
        if c["id"] in already_following_ids:
            continue
        if c["statuses_count"] < min_posts:
            continue
        if c.get("last_status_at"):
            try:
                last = datetime.fromisoformat(c["last_status_at"].replace("Z", "+00:00"))
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
    max_friends: int = Query(50, ge=1, le=500, description="Max number of your friends to expand from. Each costs 1 API call."),
    blog_roll_filter: str | None = Query(None, description="Restrict source friends to this blogroll filter (e.g. top_friends, mutuals)"),
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
        cached = (await session.execute(select(FriendsOfFriendsCache).where(FriendsOfFriendsCache.identity_id == identity_id))).scalar_one_or_none()

    if cached and _is_cache_fresh(cached.fetched_at):
        try:
            candidates = json.loads(cached.data_json)
        except Exception:
            candidates = []
        cache_hit = True
        fetched_at = cached.fetched_at.isoformat() if cached.fetched_at else None
    else:
        candidates = await _fetch_and_cache(meta.id, identity, max_friends, blog_roll_filter)
        cache_hit = False
        fetched_at = datetime.utcnow().isoformat()

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
    filtered = _apply_filters(candidates, already_following_ids, min_posts, active_since_days, bio_contains)

    total = len(filtered)
    page = filtered[offset : offset + limit]

    return {
        "candidates": page,
        "total": total,
        "total_downloaded": total_downloaded,
        "offset": offset,
        "limit": limit,
        "cache_hit": cache_hit,
        "fetched_at": fetched_at,
    }


@router.post("/refresh")
async def refresh_candidates(
    identity_id: int = Query(...),
    max_friends: int = Query(50, ge=1, le=500),
    blog_roll_filter: str | None = Query(None),
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    """
    Force a cache refresh (runs synchronously; use for on-demand refresh).
    """
    identity = await resolve_identity(meta.id, identity_id)
    candidates = await _fetch_and_cache(meta.id, identity, max_friends, blog_roll_filter)
    return {"status": "ok", "candidates_fetched": len(candidates)}
