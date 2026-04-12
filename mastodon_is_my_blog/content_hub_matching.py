# mastodon_is_my_blog/content_hub_matching.py
"""
Matching helpers for Content Hub post discovery.

Responsibilities:
- normalize hashtag terms for consistent comparison
- retro-match existing cached posts against new hashtag bundle terms
- preserve raw-search historical matches (no local re-evaluation)
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from sqlalchemy import and_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mastodon_is_my_blog.store import (
    CachedPost,
    ContentHubGroupTerm,
    ContentHubPostMatch,
)


def normalize_hashtag(term: str) -> str:
    """
    Normalize a hashtag for deduplication and matching.
    Strips leading '#', lowercases, strips whitespace.
    """
    return re.sub(r"^#+", "", term).strip().lower()


def normalize_search_term(term: str) -> str:
    """Normalize a raw search query (just lowercase + strip for now)."""
    return term.strip().lower()


def normalize_term(term: str, term_type: str) -> str:
    if term_type == "hashtag":
        return normalize_hashtag(term)
    return normalize_search_term(term)


async def retro_match_hashtag_term(
    session: AsyncSession,
    meta_id: int,
    identity_id: int,
    group_id: int,
    term: ContentHubGroupTerm,
) -> int:
    """
    Match existing cached posts whose tags contain the given hashtag term.
    Inserts rows into content_hub_post_matches for any new matches.
    Returns the count of newly inserted match rows.
    """
    normalized = term.normalized_term

    # Fetch all cached posts for this identity that have tags
    stmt = select(CachedPost).where(
        and_(
            CachedPost.meta_account_id == meta_id,
            CachedPost.fetched_by_identity_id == identity_id,
            CachedPost.tags.is_not(None),
        )
    )
    posts = (await session.execute(stmt)).scalars().all()

    matching_post_ids: list[str] = []
    for post in posts:
        try:
            tags = [t.lower() for t in json.loads(post.tags or "[]")]
        except (json.JSONDecodeError, TypeError):
            continue
        if normalized in tags:
            matching_post_ids.append(post.id)

    if not matching_post_ids:
        return 0

    # Find which ones already have a match row for this group
    existing_stmt = select(ContentHubPostMatch.post_id).where(
        and_(
            ContentHubPostMatch.group_id == group_id,
            ContentHubPostMatch.meta_account_id == meta_id,
            ContentHubPostMatch.post_id.in_(matching_post_ids),
        )
    )
    already_matched = set(
        (await session.execute(existing_stmt)).scalars().all()
    )

    new_ids = [pid for pid in matching_post_ids if pid not in already_matched]
    if not new_ids:
        return 0

    rows = [
        {
            "group_id": group_id,
            "post_id": pid,
            "meta_account_id": meta_id,
            "fetched_by_identity_id": identity_id,
            "matched_term_id": term.id,
            "matched_via": "hashtag",
            "created_at": datetime.utcnow(),
        }
        for pid in new_ids
    ]
    await session.execute(
        sqlite_insert(ContentHubPostMatch).values(rows).prefix_with("OR IGNORE")
    )
    return len(rows)


async def retro_match_group_hashtag_terms(
    session: AsyncSession,
    meta_id: int,
    identity_id: int,
    group_id: int,
    terms: list[ContentHubGroupTerm],
) -> int:
    """
    Run retro-matching for all hashtag terms in a group.
    Returns total match rows inserted.
    """
    total = 0
    for term in terms:
        if term.term_type == "hashtag":
            total += await retro_match_hashtag_term(
                session, meta_id, identity_id, group_id, term
            )
    return total


async def record_search_matches(
    session: AsyncSession,
    meta_id: int,
    identity_id: int,
    group_id: int,
    term: ContentHubGroupTerm,
    post_ids: list[str],
) -> int:
    """
    Record that a set of post IDs were fetched by a raw search term.
    Used after a live search fetch — we don't re-evaluate search locally.
    Returns the count of inserted rows.
    """
    if not post_ids:
        return 0

    rows = [
        {
            "group_id": group_id,
            "post_id": pid,
            "meta_account_id": meta_id,
            "fetched_by_identity_id": identity_id,
            "matched_term_id": term.id,
            "matched_via": "search",
            "created_at": datetime.utcnow(),
        }
        for pid in post_ids
    ]
    await session.execute(
        sqlite_insert(ContentHubPostMatch).values(rows).prefix_with("OR IGNORE")
    )
    return len(rows)
