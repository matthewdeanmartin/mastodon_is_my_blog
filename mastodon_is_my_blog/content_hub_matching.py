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

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from mastodon_is_my_blog.datetime_helpers import utc_now
from mastodon_is_my_blog.dialect_upsert import insert_or_ignore
from mastodon_is_my_blog.store import (
    CachedPost,
    ContentHubGroupTerm,
    ContentHubPostMatch,
)

# SQLite limits bound parameters per statement (historically 999, 32766 in
# modern builds). Stay well under for both IN() lookups and multi-row inserts.
# ContentHubPostMatch has 7 columns, so 4000 rows -> 28000 params.
_IN_CHUNK = 5000
_INSERT_CHUNK = 4000


def _chunked(seq: list, size: int):
    """Yield successive size-length chunks of seq."""
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


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

    # Fetch only (id, tags) for this identity's tagged posts. Selecting the two
    # columns the matcher needs avoids hydrating full ORM rows (content blobs
    # etc.), which dominates on a large cache.
    stmt = select(CachedPost.id, CachedPost.tags).where(
        and_(
            CachedPost.meta_account_id == meta_id,
            CachedPost.fetched_by_identity_id == identity_id,
            CachedPost.tags.is_not(None),
        )
    )
    selected_rows = (await session.execute(stmt)).all()

    matching_post_ids: list[str] = []
    for post_id, raw_tags in selected_rows:
        try:
            tags = [t.lower() for t in json.loads(raw_tags or "[]")]
        except (json.JSONDecodeError, TypeError):
            continue
        if normalized in tags:
            matching_post_ids.append(post_id)

    if not matching_post_ids:
        return 0

    # Find which ones already have a match row for this group. Chunk the IN()
    # lookup to stay under SQLite's bound-parameter limit on a large cache.
    already_matched: set[str] = set()
    for batch in _chunked(matching_post_ids, _IN_CHUNK):
        existing_stmt = select(ContentHubPostMatch.post_id).where(
            and_(
                ContentHubPostMatch.group_id == group_id,
                ContentHubPostMatch.meta_account_id == meta_id,
                ContentHubPostMatch.post_id.in_(batch),
            )
        )
        already_matched.update((await session.execute(existing_stmt)).scalars().all())

    new_ids = [pid for pid in matching_post_ids if pid not in already_matched]
    if not new_ids:
        return 0

    insert_rows: list[dict[str, object]] = [
        {
            "group_id": group_id,
            "post_id": pid,
            "meta_account_id": meta_id,
            "fetched_by_identity_id": identity_id,
            "matched_term_id": term.id,
            "matched_via": "hashtag",
            "created_at": utc_now(),
        }
        for pid in new_ids
    ]
    for batch in _chunked(insert_rows, _INSERT_CHUNK):
        await session.execute(
            insert_or_ignore(
                ContentHubPostMatch,
                batch,
                index_elements=["group_id", "post_id", "meta_account_id"],
            )
        )
    return len(insert_rows)


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

    Scans the identity's tagged posts a single time and matches every hashtag
    term against each post in that one pass. This replaces the previous
    one-scan-per-term behaviour, which was O(terms x cache_size).
    """
    # normalized hashtag -> term (last wins on duplicate normalizations within
    # the group, which is fine: the term ids share a group and matched_via).
    hashtag_terms = {term.normalized_term: term for term in terms if term.term_type == "hashtag"}
    if not hashtag_terms:
        return 0

    stmt = select(CachedPost.id, CachedPost.tags).where(
        and_(
            CachedPost.meta_account_id == meta_id,
            CachedPost.fetched_by_identity_id == identity_id,
            CachedPost.tags.is_not(None),
        )
    )
    rows = (await session.execute(stmt)).all()

    # term_id -> list of post ids that contain that term's hashtag
    matches_by_term: dict[int, list[str]] = {}
    for post_id, raw_tags in rows:
        try:
            tags = {t.lower() for t in json.loads(raw_tags or "[]")}
        except (json.JSONDecodeError, TypeError):
            continue
        for normalized, term in hashtag_terms.items():
            if normalized in tags:
                matches_by_term.setdefault(term.id, []).append(post_id)

    if not matches_by_term:
        return 0

    # Skip post ids that already have a match row for this group (per term).
    # Chunk the IN() lookup: SQLite caps bound parameters per statement, and the
    # candidate set can exceed that on a large cache.
    candidate_ids = list({pid for ids in matches_by_term.values() for pid in ids})
    already: set[tuple[int, str]] = set()
    for batch in _chunked(candidate_ids, _IN_CHUNK):
        existing_stmt = select(ContentHubPostMatch.matched_term_id, ContentHubPostMatch.post_id).where(
            and_(
                ContentHubPostMatch.group_id == group_id,
                ContentHubPostMatch.meta_account_id == meta_id,
                ContentHubPostMatch.post_id.in_(batch),
            )
        )
        already.update((term_id, post_id) for term_id, post_id in (await session.execute(existing_stmt)).all())

    now = utc_now()
    new_rows = [
        {
            "group_id": group_id,
            "post_id": pid,
            "meta_account_id": meta_id,
            "fetched_by_identity_id": identity_id,
            "matched_term_id": term_id,
            "matched_via": "hashtag",
            "created_at": now,
        }
        for term_id, post_ids in matches_by_term.items()
        for pid in post_ids
        if (term_id, pid) not in already
    ]
    if not new_rows:
        return 0

    # Chunk the multi-row insert for the same parameter-limit reason
    # (ContentHubPostMatch has 7 bound columns per row).
    for batch in _chunked(new_rows, _INSERT_CHUNK):
        await session.execute(
            insert_or_ignore(
                ContentHubPostMatch,
                batch,
                index_elements=["group_id", "post_id", "meta_account_id"],
            )
        )
    return len(new_rows)


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
            "created_at": utc_now(),
        }
        for pid in post_ids
    ]
    await session.execute(
        insert_or_ignore(
            ContentHubPostMatch,
            rows,
            index_elements=["group_id", "post_id", "meta_account_id"],
        )
    )
    return len(rows)
