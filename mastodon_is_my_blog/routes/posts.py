# mastodon_is_my_blog/routes/posts.py
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, desc, func, select

from mastodon_is_my_blog.link_previews import CardResponse, fetch_card
from mastodon_is_my_blog.mastodon_apis.masto_client import (
    client_from_identity_id,
)
from mastodon_is_my_blog.queries import (
    get_counts_optimized,
    get_current_meta_account,
)
from mastodon_is_my_blog.store import (
    CachedPost,
    MetaAccount,
    async_session,
)
from mastodon_is_my_blog.utils.perf import time_async_function

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/posts", tags=["posts"])


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
    meta: MetaAccount = Depends(get_current_meta_account),
) -> list[dict]:
    """
    Get posts with filters. Scoped to a specific identity.
    """
    async with async_session() as session:
        # Base Scoping: Meta Account AND Identity
        query = select(CachedPost).where(
            and_(
                CachedPost.meta_account_id == meta.id,
                CachedPost.fetched_by_identity_id == identity_id,
            )
        )
        query = query.order_by(desc(CachedPost.created_at))

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
                and_(CachedPost.is_reblog == False, CachedPost.is_reply == False)
            )
        elif filter_type == "storms":
            # not implemented yet!
            # should match get_storms method
            pass
        elif filter_type == "shorts":
            # NEW: Short text posts, no media, no links, not a reply
            query = query.where(
                and_(
                    CachedPost.is_reply == False,
                    CachedPost.is_reblog == False,
                    CachedPost.has_media == False,
                    CachedPost.has_video == False,
                    CachedPost.has_link == False,
                    func.length(CachedPost.content) < 500,
                )
            )
        elif filter_type == "discussions":
            # Only replies to others
            query = query.where(CachedPost.is_reply == True)
        elif filter_type == "pictures":
            query = query.where(CachedPost.has_media == True)
        elif filter_type == "videos":
            query = query.where(CachedPost.has_video == True)
        elif filter_type == "news":
            query = query.where(CachedPost.has_news == True)
        elif filter_type == "software":
            query = query.where(CachedPost.has_tech == True)
        elif filter_type == "links":
            # New Filter: Posts with links
            query = query.where(CachedPost.has_link == True)
        elif filter_type == "questions":
            # Filter for posts with questions
            query = query.where(CachedPost.has_question == True)
        elif filter_type == "everyone":
            # No additional filters, show all posts
            pass

        result = await session.execute(query)
        posts = result.scalars().all()

        return [
            {
                "id": p.id,
                "content": p.content,
                "author_acct": p.author_acct,
                "created_at": p.created_at.isoformat(),
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
            for p in posts
        ]


@router.get("/shorts")
async def get_shorts(
    identity_id: int = Query(...),
    user: str | None = None,
    meta: MetaAccount = Depends(get_current_meta_account),
):
    return await get_public_posts(
        identity_id=identity_id, user=user, filter_type="shorts", meta=meta
    )


@router.get("/storms")
@time_async_function
async def get_storms(
    identity_id: int = Query(...),
    user: str | None = None,
    meta: MetaAccount = Depends(get_current_meta_account),
):
    """
    Returns 'Tweet Storms' visible to the specific identity.
    """
    async with async_session() as session:
        # Base Scoping
        query = select(CachedPost).where(
            and_(
                CachedPost.meta_account_id == meta.id,
                CachedPost.fetched_by_identity_id == identity_id,
            )
        )
        query = query.order_by(desc(CachedPost.created_at))

        # Filter by user if provided
        if user and user != "everyone":
            query = query.where(CachedPost.author_acct == user)

        query = query.where(CachedPost.is_reblog == False)

        result = await session.execute(query)
        all_posts = result.scalars().all()

    # In-Memory Grouping Algorithm (Same as before, just cleaner query)
    post_map = {p.id: p for p in all_posts}
    children_map = {}
    for p in all_posts:
        if p.in_reply_to_id:
            children_map.setdefault(p.in_reply_to_id, []).append(p)

    # 3. Identify Roots
    storms = []
    processed_ids = set()

    # We iterate chronologically DESC (newest first) to show latest storms at top
    sorted_posts = sorted(all_posts, key=lambda x: x.created_at, reverse=True)

    for p in sorted_posts:
        if p.id in processed_ids:
            continue

        # Root Definition:
        # - No parent (in_reply_to_id is None)
        # - Not a link post (optional preference)
        # - If it HAS a parent, but that parent isn't in our DB (broken chain), treat as root?
        #    For now, strict roots only.
        is_root = False
        # ROOT DEFINITION UPDATE:
        # - Must not be a reply
        # - Must NOT have a link (per user request)
        if not p.in_reply_to_id and not p.has_link:
            is_root = True

        if is_root:
            processed_ids.add(p.id)

            # Recursive collector that strictly follows SELF-REPLIES
            def collect_children(parent_id: str, root_author_id: str):
                results = []
                direct_kids = children_map.get(parent_id, [])
                # Sort kids by time ASC (chronological reading)
                direct_kids.sort(key=lambda x: x.created_at)

                for kid in direct_kids:
                    # STRICT RULE: Must be same author as Root to be part of the storm
                    if kid.author_id == root_author_id:
                        processed_ids.add(kid.id)
                        kid_data = {
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
                            "children": collect_children(kid.id, root_author_id),
                        }
                        results.append(kid_data)
                return results

            # Build the storm object
            storm = {
                "root": {
                    "id": p.id,
                    "content": p.content,
                    "created_at": p.created_at.isoformat(),
                    "media": (
                        json.loads(p.media_attachments) if p.media_attachments else []
                    ),
                    "counts": {"replies": p.replies_count, "likes": p.favourites_count},
                    "author_acct": p.author_acct,
                },
                "branches": collect_children(p.id, p.author_id),
            }
            storms.append(storm)

    return storms


# --- Hashtag Aggregation ---
@router.get("/hashtags")
async def get_hashtags(
    identity_id: int = Query(...),
    user: str | None = None,
    meta: MetaAccount = Depends(get_current_meta_account),
):
    """Aggregates all hashtags used by the user."""
    async with async_session() as session:
        query = select(CachedPost.tags).where(
            and_(
                CachedPost.meta_account_id == meta.id,
                CachedPost.fetched_by_identity_id == identity_id,
            )
        )

        if user and user != "everyone":
            query = query.where(CachedPost.author_acct == user)

        result = await session.execute(query)
        # Result is a list of JSON strings (["['tag1', 'tag2']", "['tag3']"])
        all_tags_raw = result.scalars().all()

    tag_counts = {}
    for raw in all_tags_raw:
        if not raw:
            continue
        try:
            tags = json.loads(raw)
            for t in tags:
                lower_t = t.lower()
                tag_counts[lower_t] = tag_counts.get(lower_t, 0) + 1
        except:
            continue

    # Return sorted by count
    return sorted(
        [{"name": k, "count": v} for k, v in tag_counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )


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
@router.get("/{id}/context")
@time_async_function
async def get_post_context(id: str, identity_id: int = Query(...)):
    """
    Crawls the conversation graph for a specific post.
    """
    # Use identity-aware client logic
    try:
        # We await this because client_from_identity_id is async
        m = await client_from_identity_id(identity_id)
    except ValueError:
        raise HTTPException(404, "Identity not found")

    try:
        # Mastodon API 'status_context' does the crawling for us
        # It returns 'ancestors' and 'descendants' list
        context = m.status_context(id)

        # We also need the target post itself
        target = m.status(id)

        return {
            "ancestors": context["ancestors"],
            "target": target,
            "descendants": context["descendants"],
        }
    except Exception as e:
        logger.error(e)
        raise HTTPException(404, f"Could not fetch context: {str(e)}")


@router.get("/{id}")
async def get_single_post(
    id: str, meta: MetaAccount = Depends(get_current_meta_account)
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
                CachedPost.id == id,
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
