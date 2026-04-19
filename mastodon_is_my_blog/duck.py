"""
DuckDB analytics layer.

Attaches the live SQLite file read-only via DuckDB's ``sqlite_scanner``.
SQLite remains the source of truth; DuckDB runs analytical queries that
SQLite either cannot express cleanly or scales poorly on.

Each query opens its own short-lived DuckDB connection in a worker thread.
DuckDB connections are not thread-safe so sharing a global connection across
concurrent asyncio.to_thread calls causes races and deadlocks.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import duckdb

from mastodon_is_my_blog.db_path import get_sqlite_file_path

logger = logging.getLogger(__name__)

ATTACH_ALIAS = "src"

SQLITE_INSTALLED = False


def _open_query_connection() -> duckdb.DuckDBPyConnection:
    """Open a fresh DuckDB in-memory connection with SQLite attached read-only."""
    global SQLITE_INSTALLED
    sqlite_path = get_sqlite_file_path()
    con = duckdb.connect(":memory:")
    if not SQLITE_INSTALLED:
        con.execute("INSTALL sqlite;")
        SQLITE_INSTALLED = True
    con.execute("LOAD sqlite;")
    con.execute(f"ATTACH '{sqlite_path}' AS {ATTACH_ALIAS} (TYPE sqlite, READ_ONLY);")
    return con


def startup() -> None:
    global SQLITE_INSTALLED
    if SQLITE_INSTALLED:
        return
    con = _open_query_connection()
    con.close()
    logger.info("DuckDB sqlite extension installed and verified")


def shutdown() -> None:
    pass


async def run(
    sql: str,
    params: list[Any] | None = None,
) -> list[tuple]:
    """Execute ``sql`` in a worker thread with a fresh DuckDB connection."""

    def _go() -> list[tuple]:
        t0 = time.monotonic()
        con = _open_query_connection()
        try:
            if params is None:
                rows = con.execute(sql).fetchall()
            else:
                rows = con.execute(sql, params).fetchall()
        finally:
            con.close()
        elapsed = time.monotonic() - t0
        if elapsed > 0.5:
            logger.warning("Slow DuckDB query (%.2fs): %.120s", elapsed, sql.strip())
        return rows

    return await asyncio.to_thread(_go)


# --- Named analytical queries -----------------------------------------------


async def hashtag_trends(
    meta_id: int,
    identity_id: int,
    bucket: str = "week",
    top: int = 20,
) -> list[dict[str, Any]]:
    """
    Top hashtags per time bucket.

    Returns one row per (bucket_start, tag) with count, limited to the top
    N tags per bucket. ``bucket`` is one of ``'day'``, ``'week'``, ``'month'``.
    Replaces the Python-side JSON-loop in ``routes/posts.get_hashtags``.
    """
    if bucket not in ("day", "week", "month"):
        raise ValueError(f"bucket must be day/week/month, got {bucket!r}")

    sql = f"""
        WITH raw AS (
            SELECT
                created_at,
                unnest(from_json(tags, '["VARCHAR"]')) AS tag
            FROM {ATTACH_ALIAS}.cached_posts
            WHERE meta_account_id = ?
              AND fetched_by_identity_id = ?
              AND content_hub_only = false
              AND tags IS NOT NULL
              AND tags != '[]'
        ),
        exploded AS (
            SELECT
                time_bucket(INTERVAL 1 {bucket}, created_at) AS bucket_start,
                lower(tag) AS tag
            FROM raw
        ),
        counted AS (
            SELECT
                bucket_start,
                tag,
                COUNT(*) AS n,
                row_number() OVER (
                    PARTITION BY bucket_start ORDER BY COUNT(*) DESC, tag
                ) AS rn
            FROM exploded
            GROUP BY bucket_start, tag
        )
        SELECT bucket_start, tag, n
        FROM counted
        WHERE rn <= ?
          AND n > 2
        ORDER BY bucket_start DESC, n DESC, tag;
    """
    rows = await run(sql, [meta_id, identity_id, top])
    return [
        {"bucket_start": r[0].isoformat() if r[0] else None, "tag": r[1], "count": r[2]}
        for r in rows
    ]


async def hashtag_counts(
    meta_id: int,
    identity_id: int,
    user: str | None = None,
) -> list[dict[str, Any]]:
    """
    Flat hashtag leaderboard, sorted by count descending.

    Drop-in replacement for the JSON-loop aggregation in
    ``routes.posts.get_hashtags``. Matches that endpoint's response shape.
    """
    params: list[Any] = [meta_id, identity_id]
    user_clause = ""
    if user and user != "everyone":
        user_clause = "AND author_acct = ?"
        params.append(user)

    sql = f"""
        WITH exploded AS (
            SELECT lower(unnest(from_json(tags, '["VARCHAR"]'))) AS name
            FROM {ATTACH_ALIAS}.cached_posts
            WHERE meta_account_id = ?
              AND fetched_by_identity_id = ?
              AND content_hub_only = false
              AND tags IS NOT NULL
              AND tags != '[]'
              {user_clause}
        )
        SELECT name, COUNT(*) AS n
        FROM exploded
        GROUP BY name
        ORDER BY n DESC, name;
    """
    rows = await run(sql, params)
    return [{"name": r[0], "count": r[1]} for r in rows]


async def content_regex_search(
    meta_id: int,
    identity_id: int,
    pattern: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """
    Regex scan across ``cached_posts.content``.

    DuckDB's ``regexp_matches`` is case-insensitive when invoked with the 'i'
    flag. We apply that by default since post content is HTML and callers
    generally want substring/keyword matches, not byte-exact regex.
    """
    if not pattern:
        raise ValueError("pattern must not be empty")

    sql = f"""
        SELECT id, author_acct, created_at, content
        FROM {ATTACH_ALIAS}.cached_posts
        WHERE meta_account_id = ?
          AND fetched_by_identity_id = ?
          AND content_hub_only = false
          AND regexp_matches(content, ?, 'i')
        ORDER BY created_at DESC
        LIMIT ?;
    """
    rows = await run(sql, [meta_id, identity_id, pattern, limit])
    return [
        {
            "id": r[0],
            "author_acct": r[1],
            "created_at": r[2].isoformat() if r[2] else None,
            "content": r[3],
        }
        for r in rows
    ]


async def posting_heatmap(
    meta_id: int,
    identity_id: int,
    author_acct: str | None = None,
) -> list[dict[str, Any]]:
    """
    Hour-of-day × day-of-week posting counts.

    Returns one row per (dow, hour) cell with a count. ``dow`` is 0 (Sunday)
    through 6 (Saturday), matching DuckDB's ``date_part('dow', ...)``.
    """
    params: list[Any] = [meta_id, identity_id]
    extra = ""
    if author_acct:
        extra = "AND author_acct = ?"
        params.append(author_acct)

    sql = f"""
        SELECT
            CAST(date_part('dow', created_at) AS INTEGER) AS dow,
            CAST(date_part('hour', created_at) AS INTEGER) AS hour,
            COUNT(*) AS n
        FROM {ATTACH_ALIAS}.cached_posts
        WHERE meta_account_id = ?
          AND fetched_by_identity_id = ?
          AND content_hub_only = false
          {extra}
        GROUP BY dow, hour
        ORDER BY dow, hour;
    """
    rows = await run(sql, params)
    return [{"dow": r[0], "hour": r[1], "count": r[2]} for r in rows]


async def top_reposters(
    meta_id: int,
    identity_id: int,
    window_days: int = 30,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    Top reblog-notification senders with delta vs. prior window.

    Counts reblog notifications per account in the current ``window_days``
    window and in the prior window of equal length, and reports the delta.
    """
    if window_days <= 0:
        raise ValueError("window_days must be > 0")

    sql = f"""
        WITH base AS (
            SELECT
                account_acct,
                created_at
            FROM {ATTACH_ALIAS}.cached_notifications
            WHERE meta_account_id = ?
              AND identity_id = ?
              AND type = 'reblog'
              AND created_at >= (now() - INTERVAL ({2 * window_days}) DAY)
        ),
        bucketed AS (
            SELECT
                account_acct,
                CASE
                    WHEN created_at >= (now() - INTERVAL ({window_days}) DAY) THEN 'current'
                    ELSE 'prior'
                END AS bucket
            FROM base
        ),
        counted AS (
            SELECT
                account_acct,
                SUM(CASE WHEN bucket = 'current' THEN 1 ELSE 0 END) AS current_n,
                SUM(CASE WHEN bucket = 'prior' THEN 1 ELSE 0 END) AS prior_n
            FROM bucketed
            GROUP BY account_acct
        )
        SELECT
            account_acct,
            current_n,
            prior_n,
            (current_n - prior_n) AS delta
        FROM counted
        WHERE current_n > 0
        ORDER BY current_n DESC, delta DESC, account_acct
        LIMIT ?;
    """
    rows = await run(sql, [meta_id, identity_id, limit])
    return [
        {
            "account_acct": r[0],
            "current": int(r[1] or 0),
            "prior": int(r[2] or 0),
            "delta": int(r[3] or 0),
        }
        for r in rows
    ]


async def notification_trends(
    meta_id: int,
    identity_id: int,
    notification_type: str | None = None,
    bucket: str = "day",
) -> dict[str, list[dict[str, Any]]]:
    """
    Time-series counts of notifications by type and by top actor.

    Returns two parallel series so the UI can render stacked-bar + leaderboard
    in one round-trip. ``notification_type`` optionally filters both series
    to a single type (e.g. 'favourite').
    """
    if bucket not in ("day", "week", "month"):
        raise ValueError(f"bucket must be day/week/month, got {bucket!r}")

    params: list[Any] = [meta_id, identity_id]
    type_clause = ""
    if notification_type:
        type_clause = "AND type = ?"
        params.append(notification_type)

    by_type_sql = f"""
        SELECT
            time_bucket(INTERVAL 1 {bucket}, created_at) AS bucket_start,
            type,
            COUNT(*) AS n
        FROM {ATTACH_ALIAS}.cached_notifications
        WHERE meta_account_id = ?
          AND identity_id = ?
          {type_clause}
        GROUP BY bucket_start, type
        ORDER BY bucket_start, type;
    """
    by_actor_sql = f"""
        SELECT account_acct, COUNT(*) AS n
        FROM {ATTACH_ALIAS}.cached_notifications
        WHERE meta_account_id = ?
          AND identity_id = ?
          {type_clause}
        GROUP BY account_acct
        ORDER BY n DESC
        LIMIT 25;
    """
    by_type, by_actor = await asyncio.gather(
        run(by_type_sql, params),
        run(by_actor_sql, params),
    )

    return {
        "by_type": [
            {
                "bucket_start": r[0].isoformat() if r[0] else None,
                "type": r[1],
                "count": r[2],
            }
            for r in by_type
        ],
        "by_actor": [{"account_acct": r[0], "count": r[1]} for r in by_actor],
    }
