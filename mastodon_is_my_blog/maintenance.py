"""Cache-maintenance jobs shared by the admin API routes and the CLI
(`mimb admin …`). Extracted from routes/admin.py so headless users don't need
a running server to run them. No Mastodon API calls in this module — these
re-analyse already-cached posts.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import select, text as sa_text, update

from mastodon_is_my_blog.store import CachedPost, async_session

logger = logging.getLogger(__name__)


async def backfill_content_flags_for_identity(meta_id: int, identity_id: int) -> dict[str, Any]:
    """Re-analyse cached posts to populate has_question / has_book flags that
    were added after initial ingestion."""
    from mastodon_is_my_blog.inspect_post import analyze_content_domains

    async with async_session() as session:
        stmt = select(
            CachedPost.id,
            CachedPost.content,
            CachedPost.media_attachments,
            CachedPost.tags,
            CachedPost.is_reply,
        ).where(
            CachedPost.meta_account_id == meta_id,
            CachedPost.fetched_by_identity_id == identity_id,
        )
        rows = (await session.execute(stmt)).all()

    async def flush(batch: list[dict]) -> None:
        async with async_session() as session:
            for item in batch:
                await session.execute(update(CachedPost).where(CachedPost.id == item["id"]).values(has_question=item["has_question"], has_book=item["has_book"]))
            await session.commit()

    updated = 0
    batch: list[dict] = []
    for row in rows:
        media = json.loads(row.media_attachments) if row.media_attachments else []
        tags = json.loads(row.tags) if row.tags else []
        try:
            flags = analyze_content_domains(row.content or "", media, row.is_reply, tags)
        except Exception:
            continue
        batch.append({"id": row.id, "has_question": flags["has_question"], "has_book": flags["has_book"]})

        if len(batch) >= 500:
            await flush(batch)
            updated += len(batch)
            batch = []

    if batch:
        await flush(batch)
        updated += len(batch)

    return {"ok": True, "updated": updated}


async def run_nlp_backfill(
    meta_id: int,
    nlp: Any,
    on_progress: Callable[[int, int | None, str], None],
    cancelled: Callable[[], bool],
) -> dict[str, Any]:
    """Precompute uncommon topic words per forum thread (thread_uncommon_words
    on root posts) using a loaded spaCy pipeline."""
    from mastodon_is_my_blog.text_topics import uncommon_lemmas

    async with async_session() as session:
        root_rows = (
            await session.execute(
                sa_text("SELECT id, meta_account_id FROM cached_posts WHERE meta_account_id = :mid AND root_id = id"),
                {"mid": meta_id},
            )
        ).all()

    total = len(root_rows)
    logger.info("NLP backfill: %d threads to process", total)
    on_progress(0, total, "loading")

    done = 0
    batch_size = 50
    updates: list[dict] = []

    update_sql = sa_text("UPDATE cached_posts SET thread_uncommon_words = :words WHERE id = :root_id AND meta_account_id = :meta_id AND root_id = id")

    for root_row in root_rows:
        if cancelled():
            logger.info("NLP backfill cancelled at %d/%d", done, total)
            break

        root_id = root_row.id
        row_meta_id = root_row.meta_account_id

        async with async_session() as session:
            thread_rows = (
                await session.execute(
                    sa_text("SELECT content FROM cached_posts WHERE meta_account_id = :mid AND root_id = :rid"),
                    {"mid": row_meta_id, "rid": root_id},
                )
            ).all()

        combined = " ".join(r.content for r in thread_rows)
        words = uncommon_lemmas(combined, nlp)
        updates.append({"root_id": root_id, "meta_id": row_meta_id, "words": json.dumps(words)})
        done += 1

        if len(updates) >= batch_size:
            async with async_session() as session:
                await session.execute(update_sql, updates)
                await session.commit()
            logger.info("NLP backfill: %d/%d committed", done, total)
            updates = []
            on_progress(done, total, "processing")

    if updates:
        async with async_session() as session:
            await session.execute(update_sql, updates)
            await session.commit()
        logger.info("NLP backfill: %d/%d final batch committed", done, total)

    on_progress(done, total, "done")
    return {"processed": done, "total": total}
