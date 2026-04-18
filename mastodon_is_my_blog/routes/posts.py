# mastodon_is_my_blog/routes/posts.py
import base64
import json
import logging
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, desc, func, or_, select

from mastodon_is_my_blog.link_previews import CardResponse, fetch_card
from mastodon_is_my_blog.mastodon_apis.masto_client import (
    client_from_identity_id,
)
from mastodon_is_my_blog.queries import (
    get_counts_optimized,
    get_current_meta_account,
)
from mastodon_is_my_blog.store import (
    CachedAccount,
    CachedPost,
    MetaAccount,
    SeenPost,
    async_session,
    get_seen_posts,
    get_unread_count,
    mark_post_seen,
    mark_posts_seen,
)
from mastodon_is_my_blog.utils.perf import time_async_function

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/posts", tags=["posts"])


async def fetch_account_info(
    session, meta_id: int, identity_id: int, accts: set[str]
) -> dict[str, dict]:
    """Return {acct: {avatar, display_name}} for the given set of accts."""
    if not accts:
        return {}
    result = await session.execute(
        select(CachedAccount.acct, CachedAccount.avatar, CachedAccount.display_name).where(
            and_(
                CachedAccount.meta_account_id == meta_id,
                CachedAccount.mastodon_identity_id == identity_id,
                CachedAccount.acct.in_(accts),
            )
        )
    )
    return {row.acct: {"avatar": row.avatar, "display_name": row.display_name} for row in result.all()}

STORM_MIN_TEXT_LEN = 500
DEFAULT_PAGE_LIMIT = 30
MAX_PAGE_LIMIT = 100


def encode_cursor(created_at: datetime, post_id: str) -> str:
    """Encode (created_at, id) as a stable base64 cursor."""
    raw = f"{created_at.isoformat()}|{post_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    """Decode a base64 cursor into (created_at, id)."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        iso, post_id = raw.split("|", 1)
        return datetime.fromisoformat(iso), post_id
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(400, "Invalid cursor") from exc


def html_text_len(html: str) -> int:
    """Strip HTML tags and URLs, return character count of remaining text."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"https?://\S+", " ", text)
    return len(text.strip())


@router.post("/read")
async def mark_posts_as_read(
    post_ids: list[str], meta: MetaAccount = Depends(get_current_meta_account)
):
    """
    Batch mark multiple posts as read.
    """
    await mark_posts_seen(meta.id, post_ids)
    return {"status": "success", "count": len(post_ids)}


@router.get("/seen")
async def get_seen_status(
    ids: str = Query(..., description="Comma-separated post IDs"),
    meta: MetaAccount = Depends(get_current_meta_account),
):
    """
    Get seen status for multiple posts.
    """
    post_ids = [p.strip() for p in ids.split(",") if p.strip()]
    seen_ids = await get_seen_posts(meta.id, post_ids)
    return {"seen": list(seen_ids)}


@router.get("/unread-count")
async def get_unread_post_count(
    identity_id: int = Query(...), meta: MetaAccount = Depends(get_current_meta_account)
):
    """
    Get count of unread posts for badge display.
    """
    async with async_session() as session:
        stmt = select(func.count(CachedPost.id)).where(  # pylint: disable=not-callable
            and_(
                CachedPost.meta_account_id == meta.id,
                CachedPost.fetched_by_identity_id == identity_id,
                CachedPost.is_reblog.is_(False),
                CachedPost.is_reply.is_(False),
                CachedPost.content_hub_only.is_(False),
            )
        )
        total_posts = (await session.execute(stmt)).scalar() or 0

    seen_count = await get_unread_count(meta.id)
    unread_count = max(0, total_posts - seen_count)
    return {"unread_count": unread_count}


@router.get("")
async def get_public_posts(
    identity_id: int = Query(..., description="The context Identity ID"),
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
    limit: int = Query(DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    before: str | None = Query(None, description="Opaque cursor from a previous page"),
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    """
    Get posts with filters. Scoped to a specific identity.
    Returns a cursor-paginated page: {items, next_cursor}.
    """
    async with async_session() as session:
        # Base Scoping: Meta Account AND Identity
        # LEFT JOIN with SeenPost to get read status
        query = (
            select(CachedPost, SeenPost.post_id.label("is_seen"))
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
                    CachedPost.content_hub_only.is_(False),
                )
            )
            .order_by(desc(CachedPost.created_at), desc(CachedPost.id))
        )

        # Apply cursor filter
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

        # Handle user filtering
        if user == "everyone" or filter_type == "everyone":
            # Show all posts fetched by this identity
            pass
        elif user:
            # Filter by specific author
            query = query.where(CachedPost.author_acct == user)
        else:
            # No user specified: Default to posts AUTHORED by the identity itself
            # We need to look up the acct for this identity_id to be safe
            # but usually the client passes the current user in `user` if they want self-posts.
            # If `user` is None here, we assume the client wants the FEED.
            # However, existing logic suggests this endpoint is often used for profiles.
            # Let's assume if user=None, we show the Feed (everyone) or throw?
            # Existing behavior implied "Main User". Let's stick to "everyone" behavior if None to be safe,
            # or filtering by the identity's own acct?
            # SAFE BET: If user is None, return all (Feed behavior).
            pass

        # Apply Type Filters
        if filter_type == "all":
            # Show roots only (hide replies to others, keep self-threads)
            query = query.where(
                and_(CachedPost.is_reblog.is_(False), CachedPost.is_reply.is_(False))
            )
        elif filter_type == "storms":
            # not implemented yet!
            # should match get_storms method
            pass
        elif filter_type == "shorts":
            # Short text posts: no links, not a reply, not a reblog, no video, short text
            # Images are allowed — a short post can have a picture; Pictures filter handles media-heavy posts
            query = query.where(
                and_(
                    CachedPost.is_reply.is_(False),
                    CachedPost.is_reblog.is_(False),
                    CachedPost.has_video.is_(False),
                    CachedPost.has_link.is_(False),
                    func.length(CachedPost.content) < 500,
                )
            )
        elif filter_type == "discussions":
            # Only replies to others
            query = query.where(CachedPost.is_reply.is_(True))
        elif filter_type == "pictures":
            query = query.where(CachedPost.has_media.is_(True))
        elif filter_type == "videos":
            query = query.where(CachedPost.has_video.is_(True))
        elif filter_type == "news":
            query = query.where(CachedPost.has_news.is_(True))
        elif filter_type == "software":
            query = query.where(CachedPost.has_tech.is_(True))
        elif filter_type == "links":
            # New Filter: Posts with links
            query = query.where(CachedPost.has_link.is_(True))
        elif filter_type == "questions":
            # Filter for posts with questions
            query = query.where(CachedPost.has_question.is_(True))
        elif filter_type == "everyone":
            # No additional filters, show all posts
            pass

        # Fetch limit+1 to detect whether a next page exists
        query = query.limit(limit + 1)
        result = await session.execute(query)
        rows = result.all()

        has_more = len(rows) > limit
        rows = rows[:limit]

        author_accts = {p.author_acct for p, _ in rows}
        account_info = await fetch_account_info(session, meta.id, identity_id, author_accts)

        items = [
            {
                "id": p.id,
                "content": p.content,
                "author_acct": p.author_acct,
                "author_avatar": account_info.get(p.author_acct, {}).get("avatar", ""),
                "author_display_name": account_info.get(p.author_acct, {}).get("display_name", ""),
                "created_at": p.created_at.isoformat(),
                "is_read": is_seen is not None,
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
            for p, is_seen in rows
        ]

        next_cursor = None
        if has_more and rows:
            last_post, _ = rows[-1]
            next_cursor = encode_cursor(last_post.created_at, last_post.id)

        return {"items": items, "next_cursor": next_cursor}


@router.get("/shorts")
async def get_shorts(
    identity_id: int = Query(...),
    user: str | None = None,
    limit: int = Query(DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    before: str | None = Query(None),
    meta: MetaAccount = Depends(get_current_meta_account),
):
    return await get_public_posts(
        identity_id=identity_id,
        user=user,
        filter_type="shorts",
        limit=limit,
        before=before,
        meta=meta,
    )


@router.get("/storms")
@time_async_function
async def get_storms(
    identity_id: int = Query(...),
    user: str | None = None,
    limit: int = Query(DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    before: str | None = Query(None, description="Opaque cursor from a previous page"),
    meta: MetaAccount = Depends(get_current_meta_account),
):
    """
    Returns 'Tweet Storms' visible to the specific identity.

    A storm is a root post (no parent, no link) that either:
    - Has at least one self-reply (same author replied to themselves), OR
    - Is long (>= STORM_MIN_TEXT_LEN chars of text)

    Instead of loading the full timeline, we:
    1. Find candidate roots via a subquery (self-replied-to posts) + long-post filter
    2. Load only roots + their reply descendants
    """
    scope = and_(
        CachedPost.meta_account_id == meta.id,
        CachedPost.fetched_by_identity_id == identity_id,
        CachedPost.is_reblog.is_(False),
        CachedPost.content_hub_only.is_(False),
    )
    user_filter = (CachedPost.author_acct == user) if (user and user != "everyone") else True

    async with async_session() as session:
        # Subquery: post IDs that have at least one self-reply.
        # A self-reply is a post where in_reply_to_id points at a post by the same author.
        # We find the *parent* IDs by joining a post to itself on in_reply_to_id.
        parent = CachedPost.__table__.alias("parent")
        child = CachedPost.__table__.alias("child")
        self_replied_ids_sq = (
            select(parent.c.id)
            .join(child, child.c.in_reply_to_id == parent.c.id)
            .where(
                and_(
                    parent.c.meta_account_id == meta.id,
                    parent.c.fetched_by_identity_id == identity_id,
                    child.c.meta_account_id == meta.id,
                    child.c.fetched_by_identity_id == identity_id,
                    child.c.author_id == parent.c.author_id,
                )
            )
            .scalar_subquery()
        )

        # Roots: no parent, no link, and either long or has a self-reply
        roots_query = (
            select(CachedPost)
            .where(
                and_(
                    scope,
                    user_filter,
                    CachedPost.in_reply_to_id.is_(None),
                    CachedPost.has_link.is_(False),
                    (
                        (func.length(CachedPost.content) >= STORM_MIN_TEXT_LEN)
                        | CachedPost.id.in_(self_replied_ids_sq)
                    ),
                )
            )
            .order_by(desc(CachedPost.created_at), desc(CachedPost.id))
        )

        # Cursor filter — paginate on roots only
        if before:
            cursor_created_at, cursor_id = decode_cursor(before)
            roots_query = roots_query.where(
                or_(
                    CachedPost.created_at < cursor_created_at,
                    and_(
                        CachedPost.created_at == cursor_created_at,
                        CachedPost.id < cursor_id,
                    ),
                )
            )

        roots_query = roots_query.limit(limit + 1)
        roots = list((await session.execute(roots_query)).scalars().all())

        has_more = len(roots) > limit
        roots = roots[:limit]

        if not roots:
            return {"items": [], "next_cursor": None}

        root_ids = [r.id for r in roots]

        # Load all reply descendants for these roots in one query.
        # We only need posts whose in_reply_to_id is one of the root IDs or their
        # descendants. Since storm chains are typically short (< 20 posts), two passes
        # (root children + grandchildren) covers nearly all real cases without recursion.
        # We load all non-root posts whose author matches any root author and whose
        # in_reply_to_id is known within our scope, then build the tree in memory.
        # This is bounded to the reply subgraph, not the full timeline.
        root_author_ids = {r.author_id for r in roots}

        replies_query = select(CachedPost).where(
            and_(
                scope,
                CachedPost.in_reply_to_id.is_not(None),
                CachedPost.author_id.in_(root_author_ids),
            )
        )
        if user and user != "everyone":
            replies_query = replies_query.where(CachedPost.author_acct == user)

        replies = (await session.execute(replies_query)).scalars().all()

        root_accts = {p.author_acct for p in roots}
        account_info = await fetch_account_info(session, meta.id, identity_id, root_accts)

    # Build children map from the small reply set only
    children_map: dict[str, list] = {}
    for p in replies:
        if p.in_reply_to_id:
            children_map.setdefault(p.in_reply_to_id, []).append(p)

    all_post_ids = root_ids + [p.id for p in replies]
    seen_ids = await get_seen_posts(meta.id, all_post_ids)

    def collect_children(parent_id: str, root_author_id: str) -> list:
        results = []
        direct_kids = sorted(children_map.get(parent_id, []), key=lambda x: x.created_at)
        for kid in direct_kids:
            if kid.author_id == root_author_id:
                results.append(
                    {
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
                        "is_read": kid.id in seen_ids,
                        "children": collect_children(kid.id, root_author_id),
                    }
                )
        return results

    storm_items = [
        {
            "root": {
                "id": p.id,
                "content": p.content,
                "created_at": p.created_at.isoformat(),
                "media": (
                    json.loads(p.media_attachments) if p.media_attachments else []
                ),
                "counts": {"replies": p.replies_count, "likes": p.favourites_count},
                "author_acct": p.author_acct,
                "author_avatar": account_info.get(p.author_acct, {}).get("avatar", ""),
                "author_display_name": account_info.get(p.author_acct, {}).get("display_name", ""),
                "is_read": p.id in seen_ids,
            },
            "branches": collect_children(p.id, p.author_id),
        }
        for p in roots
    ]

    next_cursor = None
    if has_more and roots:
        last_root = roots[-1]
        next_cursor = encode_cursor(last_root.created_at, last_root.id)

    return {"items": storm_items, "next_cursor": next_cursor}


# --- Hashtag Aggregation ---
@router.get("/hashtags")
async def get_hashtags(
    identity_id: int = Query(...),
    user: str | None = None,
    meta: MetaAccount = Depends(get_current_meta_account),
):
    """Aggregates all hashtags used by the user."""
    from mastodon_is_my_blog import duck
    return await duck.hashtag_counts(meta.id, identity_id, user=user)


# @router.get("/analytics")
# async def get_analytics(
#     user: str | None = None, meta: MetaAccount = Depends(get_current_meta_account)
# ):
#     """Aggregate performance metrics."""
#     async with async_session() as session:
#         # Query sums
#         stmt = select(
#             func.count(CachedPost.id),
#             func.sum(CachedPost.replies_count),
#             func.sum(CachedPost.reblogs_count),
#             func.sum(CachedPost.favourites_count),
#         ).where(
#             CachedPost.meta_account_id == meta.id
#         )  # SCOPED
#
#         if user and user != "everyone":
#             stmt = stmt.where(CachedPost.author_acct == user)
#
#         row = (await session.execute(stmt)).first()
#
#     return {
#         "user": user or "all",
#         "total_posts": row[0] or 0,
#         "total_replies_received": row[1] or 0,
#         "total_boosts": row[2] or 0,
#         "total_favorites": row[3] or 0,
#     }


@router.get("/counts")
@time_async_function
async def get_counts(
    identity_id: int = Query(...),
    user: str | None = None,
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    """
    Returns counts used for sidebar badges.
    Counts are designed to match existing feed endpoint semantics.
    """
    # If user is "everyone", treat it as None (all users within meta scope)
    if user == "everyone":
        user = None

    async with async_session() as session:
        return await get_counts_optimized(session, meta.id, identity_id, user)


@router.get("/card", response_model=CardResponse)
async def fetch_card_endpoint(url: str = Query(..., min_length=8, max_length=2048)):
    return await fetch_card(url)


# --- Context Crawler ---
@router.get("/{post_id}/context")
@time_async_function
async def get_post_context(post_id: str, identity_id: int = Query(...)):
    """
    Crawls the conversation graph for a specific post.
    """
    # Use identity-aware client logic
    try:
        # We await this because client_from_identity_id is async
        m = await client_from_identity_id(identity_id)
    except ValueError as exc:
        raise HTTPException(404, "Identity not found") from exc

    try:
        # Mastodon API 'status_context' does the crawling for us
        # It returns 'ancestors' and 'descendants' list
        context = m.status_context(post_id)

        # We also need the target post itself
        target = m.status(post_id)

        return {
            "ancestors": context["ancestors"],
            "target": target,
            "descendants": context["descendants"],
        }
    except Exception as e:
        logger.error(e)
        raise HTTPException(404, f"Could not fetch context: {str(e)}") from e


@router.get("/{post_id}")
async def get_single_post(
    post_id: str, meta: MetaAccount = Depends(get_current_meta_account)
):
    """
    Get a single cached post.
    Note: We don't strictly enforce identity_id here because a post ID is unique
    and if we have it in cache for this meta account, we can show it.
    """
    async with async_session() as session:
        # SCOPED: meta_account_id
        stmt = select(CachedPost).where(
            and_(
                CachedPost.id == post_id,
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


@router.post("/{post_id}/read")
async def mark_post_as_read(
    post_id: str, meta: MetaAccount = Depends(get_current_meta_account)
):
    """
    Called by UI mouseover. Marks a post as seen.
    """
    await mark_post_seen(meta.id, post_id)
    return {"status": "success"}


#
#
# @router.get("/{id}/comments")
# async def get_live_comments(id: str) -> dict:
#     """Comments are fetched live to ensure freshness"""
#     token = await get_token()
#     if not token:
#         return {"descendants": []}
#
#     try:
#         m = client(token)
#         context = m.status_context(id)
#         return context
#     except:
#         return {"descendants": []}
#
#
# @router.get("")
# async def posts(limit: int = 20):
#     token = await get_token()
#     if not token:
#         raise HTTPException(401, "Not connected")
#     m = client(token)
#     me = m.account_verify_credentials()
#     return m.account_statuses(me["id"], limit=limit, exclude_reblogs=True)
#
#
# @router.get("/{status_id}")
# async def get_post(status_id: str):
#     # This is a direct proxy for edit/view in admin, not public feed
#     token = await get_token()
#     if not token:
#         raise HTTPException(401, "Not connected")
#     return client(token).status(status_id)
#
#
# @router.get("/{status_id}/comments")
# async def comments(status_id: str):
#     token = await get_token()
#     if not token:
#         raise HTTPException(401, "Not connected")
#     return client(token).status_context(status_id)
#
#
# @router.get("/{status_id}/source")
# async def source(status_id: str):
#     token = await get_token()
#     if not token:
#         raise HTTPException(401, "Not connected")
#     return client(token).status_source(status_id)
