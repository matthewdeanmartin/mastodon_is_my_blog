# mastodon_is_my_blog/routes/content_hub.py
"""
Public read API for Content Hub.

Endpoints:
  GET  /api/content-hub/groups                       list groups for identity
  GET  /api/content-hub/groups/{group_id}/posts      paged posts for a group tab
  POST /api/content-hub/groups/{group_id}/refresh    force a group refresh
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, desc, func, label, or_, select
from sqlalchemy.orm import selectinload

from mastodon_is_my_blog.content_hub_classifier import is_videos_post
from mastodon_is_my_blog.content_hub_service import (
    is_group_stale,
    refresh_group,
    sync_server_follow_groups,
)
from mastodon_is_my_blog.queries import get_current_meta_account
from mastodon_is_my_blog.store import (
    CachedAccount,
    CachedPost,
    ContentHubGroup,
    ContentHubPostMatch,
    MastodonIdentity,
    MetaAccount,
    async_session,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/content-hub", tags=["content-hub"])

DEFAULT_LIMIT = 30
MAX_LIMIT = 100


def encode_cursor(created_at: datetime, post_id: str) -> str:
    raw = f"{created_at.isoformat()}|{post_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode("ascii")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode()
        iso, post_id = raw.split("|", 1)
        return datetime.fromisoformat(iso), post_id
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(400, "Invalid cursor") from exc


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


def group_to_dict(group: ContentHubGroup) -> dict:
    return {
        "id": group.id,
        "name": group.name,
        "slug": group.slug,
        "source_type": group.source_type,
        "is_read_only": group.is_read_only,
        "last_fetched_at": (group.last_fetched_at.isoformat() if group.last_fetched_at else None),
        "terms": [{"id": t.id, "term": t.term, "term_type": t.term_type} for t in group.terms],
    }


@router.get("/groups")
async def list_groups(
    identity_id: int = Query(...),
    meta: MetaAccount = Depends(get_current_meta_account),
) -> list[dict]:
    """
    List all Content Hub groups visible to the given identity.
    client_bundle groups come first, then server_follow groups, both alphabetical.
    """
    async with async_session() as session:
        stmt = (
            select(ContentHubGroup)
            .options(selectinload(ContentHubGroup.terms))
            .where(
                ContentHubGroup.meta_account_id == meta.id,
                ContentHubGroup.identity_id == identity_id,
            )
            .order_by(ContentHubGroup.source_type, ContentHubGroup.name)
        )
        groups = (await session.execute(stmt)).scalars().all()

    return [group_to_dict(g) for g in groups]


@router.get("/groups/{group_id}/posts")
async def get_group_posts(
    group_id: int,
    identity_id: int = Query(...),
    tab: str = Query("text", enum=["text", "videos", "jobs", "software", "news", "links"]),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    before: str | None = Query(None),
    shuffle: bool = Query(False),
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    """
    Return cached matched posts for a Content Hub group tab.
    Triggers a background-style stale check (non-blocking refresh info in response).
    """
    async with async_session() as session:
        group = await session.get(ContentHubGroup, group_id)
        if group is None or group.meta_account_id != meta.id or group.identity_id != identity_id:
            raise HTTPException(404, "Group not found")

        stale = await is_group_stale(group)

        # Join content_hub_post_matches → cached_posts
        query = (
            select(CachedPost)
            .join(
                ContentHubPostMatch,
                and_(
                    ContentHubPostMatch.post_id == CachedPost.id,
                    ContentHubPostMatch.meta_account_id == CachedPost.meta_account_id,
                    ContentHubPostMatch.fetched_by_identity_id == CachedPost.fetched_by_identity_id,
                    ContentHubPostMatch.group_id == group_id,
                ),
            )
            .where(
                CachedPost.meta_account_id == meta.id,
                CachedPost.fetched_by_identity_id == identity_id,
            )
            .distinct()
            .order_by(desc(CachedPost.created_at), desc(CachedPost.id))
        )

        if before:
            cursor_created_at, cursor_id = decode_cursor(before)
            query = query.where(
                or_(
                    CachedPost.created_at < cursor_created_at,
                    and_(
                        CachedPost.created_at == cursor_created_at,
                        CachedPost.id < cursor_id,
                    ),
                )
            )

        # Fetch more than needed so we can apply tab filtering in Python
        # (tab filters are cheap in-memory operations)
        raw_limit = limit * 4  # overfetch for filtering
        query = query.limit(raw_limit)
        posts = (await session.execute(query)).scalars().all()

    # Apply tab filter
    if tab == "videos":
        posts = [p for p in posts if is_videos_post(p)]
    elif tab == "jobs":
        posts = [p for p in posts if p.has_job]
    elif tab == "software":
        posts = [p for p in posts if p.has_tech]
    elif tab == "news":
        posts = [p for p in posts if p.has_news]
    elif tab == "links":
        posts = [p for p in posts if p.has_link]
    # "text" includes all posts

    posts = list(posts)
    if shuffle:
        import random

        random.shuffle(posts)

    has_more = len(posts) > limit
    posts = posts[:limit]

    # Fetch account avatars
    author_accts = {p.author_acct for p in posts}
    account_info: dict[str, dict] = {}
    if author_accts:
        async with async_session() as session:
            stmt = select(CachedAccount.acct, CachedAccount.avatar, CachedAccount.display_name).where(
                CachedAccount.meta_account_id == meta.id,
                CachedAccount.mastodon_identity_id == identity_id,
                CachedAccount.acct.in_(author_accts),
            )
            for row in (await session.execute(stmt)).all():
                account_info[row.acct] = {
                    "avatar": row.avatar,
                    "display_name": row.display_name,
                }

    items = [
        {
            "id": p.id,
            "content": p.content,
            "author_acct": p.author_acct,
            "author_avatar": account_info.get(p.author_acct, {}).get("avatar", ""),
            "author_display_name": account_info.get(p.author_acct, {}).get("display_name", ""),
            "created_at": p.created_at.isoformat(),
            "media_attachments": (json.loads(p.media_attachments) if p.media_attachments else []),
            "tags": json.loads(p.tags) if p.tags else [],
            "counts": {
                "replies": p.replies_count,
                "reblogs": p.reblogs_count,
                "likes": p.favourites_count,
            },
            "has_video": p.has_video,
            "has_link": p.has_link,
            "is_reblog": p.is_reblog,
            "is_reply": p.is_reply,
        }
        for p in posts
    ]

    next_cursor = None
    if has_more and posts and not shuffle:
        next_cursor = encode_cursor(posts[-1].created_at, posts[-1].id)

    return {
        "items": items,
        "next_cursor": next_cursor,
        "stale": stale,
        "group": {
            "id": group.id,
            "name": group.name,
            "last_fetched_at": (group.last_fetched_at.isoformat() if group.last_fetched_at else None),
        },
    }


@router.post("/groups/{group_id}/refresh")
async def force_refresh_group(
    group_id: int,
    identity_id: int = Query(...),
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    """Force a refresh of a Content Hub group from Mastodon."""
    async with async_session() as session:
        group = await session.get(ContentHubGroup, group_id)
        if group is None or group.meta_account_id != meta.id or group.identity_id != identity_id:
            raise HTTPException(404, "Group not found")

    identity = await resolve_identity(meta.id, identity_id)

    result = await refresh_group(meta.id, identity, group_id, force=True)
    return {"refreshed": True, **result}


@router.get("/groups/{group_id}/people")
async def get_group_people(
    group_id: int,
    identity_id: int = Query(...),
    limit: int = Query(50, ge=1, le=200),
    sort: str = Query("posts", enum=["posts", "recent", "engagement"]),
    exclude_followed: bool = Query(False),
    meta: MetaAccount = Depends(get_current_meta_account),
) -> list[dict]:
    """Ranked list of distinct authors posting in a Content Hub group."""
    async with async_session() as session:
        group = await session.get(ContentHubGroup, group_id)
        if group is None or group.meta_account_id != meta.id or group.identity_id != identity_id:
            raise HTTPException(404, "Group not found")

        aggregated = (
            select(
                CachedPost.author_acct,
                CachedPost.author_id,
                label("post_count_in_group", func.count(CachedPost.id)),  # pylint: disable=not-callable
                label("last_in_group", func.max(CachedPost.created_at)),
                label(
                    "total_engagement_in_group",
                    func.sum(CachedPost.favourites_count + CachedPost.reblogs_count + CachedPost.replies_count),
                ),
            )
            .join(
                ContentHubPostMatch,
                and_(
                    ContentHubPostMatch.post_id == CachedPost.id,
                    ContentHubPostMatch.meta_account_id == CachedPost.meta_account_id,
                    ContentHubPostMatch.fetched_by_identity_id == CachedPost.fetched_by_identity_id,
                    ContentHubPostMatch.group_id == group_id,
                ),
            )
            .where(
                CachedPost.meta_account_id == meta.id,
                CachedPost.fetched_by_identity_id == identity_id,
            )
            .group_by(CachedPost.author_acct, CachedPost.author_id)
        )

        if sort == "recent":
            aggregated = aggregated.order_by(desc("last_in_group"))
        elif sort == "engagement":
            aggregated = aggregated.order_by(desc("total_engagement_in_group"))
        else:
            aggregated = aggregated.order_by(desc("post_count_in_group"), desc("last_in_group"))

        aggregated = aggregated.limit(limit * 2)
        agg_rows = (await session.execute(aggregated)).all()

        author_accts = {row.author_acct for row in agg_rows}
        accounts_map: dict[str, CachedAccount] = {}
        if author_accts:
            acct_stmt = select(CachedAccount).where(
                CachedAccount.meta_account_id == meta.id,
                CachedAccount.mastodon_identity_id == identity_id,
                CachedAccount.acct.in_(author_accts),
            )
            for account in (await session.execute(acct_stmt)).scalars():
                accounts_map[account.acct] = account

    items = []
    for row in agg_rows:
        ca = accounts_map.get(row.author_acct)
        is_following = ca.is_following if ca else False
        if exclude_followed and is_following:
            continue
        items.append(
            {
                "acct": row.author_acct,
                "display_name": ca.display_name if ca else row.author_acct,
                "avatar": ca.avatar if ca else "",
                "note": ca.note if ca else "",
                "is_following": is_following,
                "is_followed_by": ca.is_followed_by if ca else False,
                "post_count_in_group": row.post_count_in_group,
                "last_in_group": (row.last_in_group.isoformat() if row.last_in_group else None),
                "total_engagement_in_group": row.total_engagement_in_group or 0,
            }
        )
        if len(items) >= limit:
            break

    return items


@router.post("/sync-follows")
async def sync_follows(
    identity_id: int = Query(...),
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    """Sync server-side followed hashtags into read-only Content Hub groups."""
    identity = await resolve_identity(meta.id, identity_id)
    result = await sync_server_follow_groups(meta.id, identity)
    return result
