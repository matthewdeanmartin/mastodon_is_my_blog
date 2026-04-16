# mastodon_is_my_blog/content_hub_service.py
"""
Orchestration layer for Content Hub.

Responsibilities:
- sync server-follow groups from Mastodon followed-hashtag API
- refresh a group's posts from Mastodon (hashtag timeline or status search)
- write fetched posts to cached_posts as content_hub_only
- write match rows to content_hub_post_matches
- retro-match new bundle terms against existing cached posts
"""
from __future__ import annotations

import logging
import re
from datetime import timedelta

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from mastodon_is_my_blog.content_hub_matching import (
    normalize_term,
    record_search_matches,
    retro_match_group_hashtag_terms,
)
from mastodon_is_my_blog.datetime_helpers import utc_now
from mastodon_is_my_blog.mastodon_apis.masto_client import client_from_identity
from mastodon_is_my_blog.queries import bulk_upsert_posts
from mastodon_is_my_blog.store import (
    ContentHubGroup,
    ContentHubGroupTerm,
    ContentHubPostMatch,
    MastodonIdentity,
    async_session,
)

logger = logging.getLogger(__name__)

STALE_AFTER_HOURS = 1


def make_slug(name: str) -> str:
    """URL-safe slug from a group name."""
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug)
    return slug.strip("-")


# ---------------------------------------------------------------------------
# Server-follow sync
# ---------------------------------------------------------------------------


async def sync_server_follow_groups(
    meta_id: int,
    identity: MastodonIdentity,
) -> dict[str, int]:
    """
    Read followed hashtags from Mastodon and materialize them into
    read-only singleton ContentHubGroup rows.

    Returns {"created": N, "removed": N}.
    """
    m = client_from_identity(identity)
    try:
        followed = m.followed_tags()
    except Exception as exc:
        logger.error("Failed to fetch followed tags for identity %s: %s", identity.id, exc)
        return {"created": 0, "removed": 0}

    # followed is a list of tag dicts: {"name": str, ...}
    live_names: set[str] = {tag["name"].lower() for tag in followed}

    async with async_session() as session:
        # Load existing server_follow groups for this identity
        stmt = select(ContentHubGroup).where(
            and_(
                ContentHubGroup.meta_account_id == meta_id,
                ContentHubGroup.identity_id == identity.id,
                ContentHubGroup.source_type == "server_follow",
            )
        )
        existing = (await session.execute(stmt)).scalars().all()
        existing_by_slug = {g.slug: g for g in existing}
        existing_slugs: set[str] = set(existing_by_slug.keys())

        created = 0
        for tag in followed:
            tag_name = tag["name"].lower()
            slug = make_slug(tag_name)
            if slug not in existing_slugs:
                group = ContentHubGroup(
                    meta_account_id=meta_id,
                    identity_id=identity.id,
                    name=f"#{tag['name']}",
                    slug=slug,
                    source_type="server_follow",
                    is_read_only=True,
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
                session.add(group)
                await session.flush()  # get group.id

                term = ContentHubGroupTerm(
                    group_id=group.id,
                    term=tag["name"],
                    term_type="hashtag",
                    normalized_term=tag_name,
                    created_at=utc_now(),
                )
                session.add(term)
                created += 1

        # Remove server_follow groups no longer followed
        removed = 0
        for slug, group in existing_by_slug.items():
            if slug not in live_names:
                await session.delete(group)
                removed += 1

        await session.commit()

    logger.info(
        "server_follow sync for identity %s: created=%d removed=%d",
        identity.id,
        created,
        removed,
    )
    return {"created": created, "removed": removed}


# ---------------------------------------------------------------------------
# Group refresh
# ---------------------------------------------------------------------------


async def is_group_stale(group: ContentHubGroup) -> bool:
    """Return True if the group needs a refresh."""
    if group.last_fetched_at is None:
        return True
    cutoff = utc_now() - timedelta(hours=STALE_AFTER_HOURS)
    return group.last_fetched_at < cutoff


async def refresh_group(
    meta_id: int,
    identity: MastodonIdentity,
    group_id: int,
    force: bool = False,
) -> dict[str, int]:
    """
    Fetch fresh posts for every term in the group from Mastodon.
    Stores posts as content_hub_only and records match rows.

    Returns {"fetched": N, "matched": N}.
    """
    async with async_session() as session:
        group = await session.get(ContentHubGroup, group_id)
        if group is None:
            raise ValueError(f"ContentHubGroup {group_id} not found")

        if not force and not await is_group_stale(group):
            return {"fetched": 0, "matched": 0}

        stmt = select(ContentHubGroupTerm).where(
            ContentHubGroupTerm.group_id == group_id
        )
        terms = (await session.execute(stmt)).scalars().all()

    m = client_from_identity(identity)
    total_fetched = 0
    total_matched = 0

    for term in terms:
        try:
            if term.term_type == "hashtag":
                statuses = m.timeline_hashtag(term.normalized_term, limit=40)
            else:
                result = m.search(term.term, result_type="statuses", limit=40)
                statuses = result.get("statuses", [])
        except Exception as exc:
            logger.error(
                "Refresh failed for group %s term %s: %s", group_id, term.term, exc
            )
            continue

        if not statuses:
            continue

        async with async_session() as session:
            new_count, _ = await bulk_upsert_posts(
                session, meta_id, identity.id, statuses,
                discovery_source=term.term_type,
                content_hub_only=True,
            )
            await session.commit()
            total_fetched += len(statuses)

            post_ids = [str(s["id"]) for s in statuses]
            if term.term_type == "hashtag":
                from mastodon_is_my_blog.content_hub_matching import retro_match_hashtag_term
                matched = await retro_match_hashtag_term(
                    session, meta_id, identity.id, group_id, term
                )
            else:
                matched = await record_search_matches(
                    session, meta_id, identity.id, group_id, term, post_ids
                )
            await session.commit()
            total_matched += matched

    # Update last_fetched_at
    async with async_session() as session:
        group = await session.get(ContentHubGroup, group_id)
        if group:
            group.last_fetched_at = utc_now()
            group.updated_at = utc_now()
            await session.commit()

    return {"fetched": total_fetched, "matched": total_matched}


# ---------------------------------------------------------------------------
# Bundle creation / update helpers
# ---------------------------------------------------------------------------


async def retro_match_new_bundle(
    session: AsyncSession,
    meta_id: int,
    identity_id: int,
    group: ContentHubGroup,
) -> int:
    """
    After creating or editing a client bundle, retro-match existing cached
    posts against all hashtag terms.  Raw search terms are skipped (we do not
    re-evaluate Mastodon search syntax locally).
    """
    stmt = select(ContentHubGroupTerm).where(
        ContentHubGroupTerm.group_id == group.id
    )
    terms = (await session.execute(stmt)).scalars().all()
    return await retro_match_group_hashtag_terms(
        session, meta_id, identity_id, group.id, terms
    )


async def create_client_bundle(
    meta_id: int,
    identity_id: int,
    name: str,
    terms_input: list[dict],
) -> ContentHubGroup:
    """
    Create a new client_bundle group with the given terms.
    Each element in terms_input must be {"term": str, "term_type": "hashtag"|"search"}.
    Retro-matches hashtag terms immediately.
    """
    slug = make_slug(name)
    now = utc_now()

    async with async_session() as session:
        group = ContentHubGroup(
            meta_account_id=meta_id,
            identity_id=identity_id,
            name=name,
            slug=slug,
            source_type="client_bundle",
            is_read_only=False,
            created_at=now,
            updated_at=now,
        )
        session.add(group)
        await session.flush()

        for t in terms_input:
            term_obj = ContentHubGroupTerm(
                group_id=group.id,
                term=t["term"],
                term_type=t["term_type"],
                normalized_term=normalize_term(t["term"], t["term_type"]),
                created_at=now,
            )
            session.add(term_obj)

        await session.flush()
        await retro_match_new_bundle(session, meta_id, identity_id, group)
        await session.commit()
        await session.refresh(group)

    return group


async def update_client_bundle(
    meta_id: int,
    identity_id: int,
    group_id: int,
    name: str | None,
    terms_input: list[dict] | None,
) -> ContentHubGroup:
    """
    Update name and/or terms of a client_bundle group.
    Replaces all terms if terms_input is provided, then retro-matches.
    """
    async with async_session() as session:
        group = await session.get(ContentHubGroup, group_id)
        if group is None or group.meta_account_id != meta_id or group.identity_id != identity_id:
            raise ValueError("Bundle not found or not owned by this identity")
        if group.is_read_only:
            raise ValueError("Cannot edit a read-only server-follow group")

        if name is not None:
            group.name = name
            group.slug = make_slug(name)
        group.updated_at = utc_now()

        if terms_input is not None:
            # Delete existing terms
            existing_stmt = select(ContentHubGroupTerm).where(
                ContentHubGroupTerm.group_id == group_id
            )
            old_terms = (await session.execute(existing_stmt)).scalars().all()
            for t in old_terms:
                await session.delete(t)
            await session.flush()

            now = utc_now()
            for t in terms_input:
                term_obj = ContentHubGroupTerm(
                    group_id=group.id,
                    term=t["term"],
                    term_type=t["term_type"],
                    normalized_term=normalize_term(t["term"], t["term_type"]),
                    created_at=now,
                )
                session.add(term_obj)
            await session.flush()
            await retro_match_new_bundle(session, meta_id, identity_id, group)

        await session.commit()
        await session.refresh(group)

    return group
