"""
Backfill root_id and root_is_partial on CachedPost rows.

For each post:
- If not a reply: root_id = id, root_is_partial = False
- If a reply: walk in_reply_to_id chain within cached posts until we reach a
  root (in_reply_to_id IS NULL) or a gap (parent not cached).
  root_is_partial = True when the chain terminates at a gap.

Safe to re-run — only updates rows where root_id IS NULL.
"""

import asyncio
import logging

from sqlalchemy import text

from mastodon_is_my_blog.store import async_session

logger = logging.getLogger(__name__)


async def backfill(batch_size: int = 2000) -> None:
    async with async_session() as session:
        # Count work to do
        needs_fill = (await session.execute(text("SELECT COUNT(*) FROM cached_posts WHERE root_id IS NULL"))).scalar() or 0
        logger.info("Posts needing backfill: %d", needs_fill)
        if needs_fill == 0:
            logger.info("Nothing to do.")
            return

        # Load only the columns needed for chain-walking
        rows = (await session.execute(text("SELECT id, meta_account_id, in_reply_to_id FROM cached_posts WHERE root_id IS NULL"))).all()

        # Also load the in_reply_to_id for already-filled posts so we can walk through them
        all_rows = (await session.execute(text("SELECT id, meta_account_id, in_reply_to_id FROM cached_posts"))).all()

    # Build lookup: (meta_account_id, id) -> in_reply_to_id
    post_map: dict[tuple[int, str], str | None] = {}
    for row in all_rows:
        post_map[(row.meta_account_id, row.id)] = row.in_reply_to_id

    # Compute root_id for each unfilled post
    full_roots: list[tuple[str, int, str]] = []  # (post_id, meta_id, root_id)
    partial_roots: list[tuple[str, int, str]] = []  # (post_id, meta_id, root_id)

    for row in rows:
        if row.in_reply_to_id is None:
            full_roots.append((row.id, row.meta_account_id, row.id))
        else:
            current_id = row.in_reply_to_id
            meta_id = row.meta_account_id
            visited: set[str] = {row.id}
            partial = False

            while True:
                if current_id in visited:
                    partial = True
                    break
                visited.add(current_id)
                parent_reply = post_map.get((meta_id, current_id))
                if parent_reply is None:
                    if (meta_id, current_id) not in post_map:
                        partial = True
                    break
                current_id = parent_reply

            if partial:
                partial_roots.append((row.id, meta_id, current_id))
            else:
                full_roots.append((row.id, meta_id, current_id))

    logger.info("Full roots: %d, Partial roots: %d", len(full_roots), len(partial_roots))

    # Bulk update using executemany with raw SQL — much faster than one execute() per row
    async with async_session() as session:
        for i in range(0, len(full_roots), batch_size):
            chunk = full_roots[i : i + batch_size]
            await session.execute(
                text("UPDATE cached_posts SET root_id = :root_id, root_is_partial = 0 WHERE id = :post_id AND meta_account_id = :meta_id"),
                [{"root_id": r, "post_id": p, "meta_id": m} for p, m, r in chunk],
            )
            await session.commit()
            logger.info("  full-roots batch %d-%d committed", i, i + len(chunk))

        for i in range(0, len(partial_roots), batch_size):
            chunk = partial_roots[i : i + batch_size]
            await session.execute(
                text("UPDATE cached_posts SET root_id = :root_id, root_is_partial = 1 WHERE id = :post_id AND meta_account_id = :meta_id"),
                [{"root_id": r, "post_id": p, "meta_id": m} for p, m, r in chunk],
            )
            await session.commit()
            logger.info("  partial-roots batch %d-%d committed", i, i + len(chunk))

    logger.info("Backfill complete.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(backfill())
