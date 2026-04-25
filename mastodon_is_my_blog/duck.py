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
    global SQLITE_INSTALLED  # pylint: disable=global-variable-not-assigned
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
    return [{"bucket_start": r[0].isoformat() if r[0] else None, "tag": r[1], "count": r[2]} for r in rows]


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


async def forum_thread_summaries(
    meta_id: int,
    identity_id: int,
    include_content_hub: bool = False,
) -> list[dict[str, Any]]:
    """
    Aggregate cached posts into thread summaries for the forum view.

    Returns one row per root_id with: reply_count, unique_participant_count,
    latest_reply_at, root_post fields, tags union, and per-thread uncommon words.
    Only threads with ≥1 reply and ≥2 unique participants are returned.
    """
    content_hub_clause = "" if include_content_hub else "AND content_hub_only = false"

    sql = f"""
        WITH posts AS (
            SELECT
                id,
                root_id,
                author_acct,
                created_at,
                content,
                has_question,
                tags,
                thread_uncommon_words,
                in_reply_to_id
            FROM {ATTACH_ALIAS}.cached_posts
            WHERE meta_account_id = ?
              AND fetched_by_identity_id = ?
              AND is_reblog = false
              AND root_id IS NOT NULL
              {content_hub_clause}
        ),
        thread_stats AS (
            SELECT
                root_id,
                COUNT(*) AS total_posts,
                COUNT(*) - 1 AS reply_count,
                COUNT(DISTINCT author_acct) AS unique_participants,
                MAX(CASE WHEN id != root_id THEN created_at ELSE NULL END) AS latest_reply_at
            FROM posts
            GROUP BY root_id
            HAVING COUNT(*) > 1 AND COUNT(DISTINCT author_acct) >= 2
        ),
        root_posts AS (
            SELECT
                p.id,
                p.root_id,
                p.author_acct,
                p.created_at,
                p.content,
                p.has_question,
                p.tags AS root_tags,
                p.thread_uncommon_words,
                p.in_reply_to_id
            FROM posts p
            INNER JOIN thread_stats ts ON p.id = ts.root_id
        ),
        exploded_tags AS (
            SELECT p.root_id, lower(tag) AS tag
            FROM posts p
            INNER JOIN thread_stats ts ON p.root_id = ts.root_id,
            LATERAL unnest(from_json(p.tags, '["VARCHAR"]')) AS t(tag)
            WHERE p.tags IS NOT NULL AND p.tags != '[]'
        ),
        tags_union AS (
            SELECT root_id, string_agg(DISTINCT tag, ',') AS all_tags
            FROM exploded_tags
            GROUP BY root_id
        )
        SELECT
            ts.root_id,
            ts.reply_count,
            ts.unique_participants,
            ts.latest_reply_at,
            rp.author_acct,
            rp.created_at AS root_created_at,
            rp.content AS root_content,
            rp.has_question,
            rp.root_tags,
            rp.thread_uncommon_words,
            rp.in_reply_to_id IS NOT NULL AS root_is_partial,
            COALESCE(tu.all_tags, '') AS tags_csv
        FROM thread_stats ts
        JOIN root_posts rp ON rp.root_id = ts.root_id
        LEFT JOIN tags_union tu ON tu.root_id = ts.root_id
        ORDER BY COALESCE(ts.latest_reply_at, rp.created_at) DESC;
    """
    rows = await run(sql, [meta_id, identity_id])
    results = []
    for r in rows:
        tags_csv: str = r[11] or ""
        tags_set = {t for t in tags_csv.split(",") if t} if tags_csv else set()
        uncommon: list[str] = []
        if r[9]:
            try:
                import json as _json

                uncommon = _json.loads(r[9])
            except Exception:
                pass
        results.append(
            {
                "root_id": r[0],
                "reply_count": int(r[1] or 0),
                "unique_participants": int(r[2] or 0),
                "latest_reply_at": r[3].isoformat() if r[3] else None,
                "author_acct": r[4],
                "root_created_at": r[5].isoformat() if r[5] else None,
                "root_content": r[6],
                "has_question": bool(r[7]),
                "root_tags": r[8],
                "uncommon_words": uncommon,
                "root_is_partial": bool(r[10]),
                "tags": tags_set,
            }
        )
    return results


async def forum_friend_reply_counts(
    meta_id: int,
    identity_id: int,
    root_ids: list[str],
    following_accts: set[str],
) -> dict[str, int]:
    """Return count of replies by followed accounts per root_id."""
    if not root_ids or not following_accts:
        return {}

    placeholders = ", ".join("?" for _ in root_ids)
    acct_placeholders = ", ".join("?" for _ in following_accts)

    sql = f"""
        SELECT root_id, COUNT(*) AS n
        FROM src.cached_posts
        WHERE meta_account_id = ?
          AND fetched_by_identity_id = ?
          AND id != root_id
          AND root_id IN ({placeholders})
          AND author_acct IN ({acct_placeholders})
        GROUP BY root_id;
    """
    params: list[Any] = [meta_id, identity_id, *root_ids, *following_accts]
    rows = await run(sql, params)
    return {r[0]: int(r[1]) for r in rows}


async def activity_calendar(
    meta_id: int,
    identity_id: int,
    author_acct: str | None = None,
    years: int = 2,
) -> list[dict[str, Any]]:
    """
    Daily post counts for the past ``years`` calendar years (always full years,
    Jan 1 through Dec 31), used to render a GitHub-style contribution calendar.

    Returns one row per day that has ≥1 post: {date, count}.
    """
    import datetime as _dt

    current_year = _dt.datetime.utcnow().year
    start_year = current_year - (years - 1)
    cutoff = f"{start_year}-01-01"

    params: list[Any] = [meta_id, identity_id, cutoff]
    extra = ""
    if author_acct:
        extra = "AND author_acct = ?"
        params.append(author_acct)

    sql = f"""
        SELECT
            CAST(created_at AS DATE) AS day,
            COUNT(*) AS n
        FROM {ATTACH_ALIAS}.cached_posts
        WHERE meta_account_id = ?
          AND fetched_by_identity_id = ?
          AND content_hub_only = false
          AND created_at >= CAST(? AS DATE)
          {extra}
        GROUP BY day
        ORDER BY day;
    """
    rows = await run(sql, params)
    return [{"date": str(r[0]), "count": int(r[1])} for r in rows]


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


# ---------------------------------------------------------------------------
# Observability: API call log analytics
# ---------------------------------------------------------------------------


async def api_call_volume(
    bucket: str = "day",
    days: int = 30,
) -> list[dict[str, Any]]:
    """Call count per time bucket (hour/day/week) across all methods."""
    if bucket not in ("hour", "day", "week"):
        raise ValueError(f"bucket must be hour/day/week, got {bucket!r}")
    cutoff = f"now() - INTERVAL {days} DAY"
    sql = f"""
        SELECT
            time_bucket(INTERVAL 1 {bucket}, to_timestamp(ts)) AS bucket_start,
            COUNT(*) AS n
        FROM {ATTACH_ALIAS}.api_call_log
        WHERE ts >= epoch(({cutoff}))
        GROUP BY bucket_start
        ORDER BY bucket_start;
    """
    rows = await run(sql)
    return [{"bucket_start": r[0].isoformat() if r[0] else None, "count": int(r[1])} for r in rows]


async def api_call_by_method(
    days: int = 30,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Per-method call count, total elapsed seconds, and total payload bytes."""
    cutoff = f"now() - INTERVAL {days} DAY"
    sql = f"""
        SELECT
            method_name,
            COUNT(*) AS calls,
            ROUND(SUM(elapsed_s), 3) AS total_elapsed_s,
            SUM(payload_bytes) AS total_bytes,
            ROUND(AVG(elapsed_s), 4) AS avg_elapsed_s,
            SUM(CASE WHEN throttled = 1 THEN 1 ELSE 0 END) AS throttle_count,
            SUM(CASE WHEN ok = 0 THEN 1 ELSE 0 END) AS error_count
        FROM {ATTACH_ALIAS}.api_call_log
        WHERE ts >= epoch(({cutoff}))
        GROUP BY method_name
        ORDER BY calls DESC
        LIMIT ?;
    """
    rows = await run(sql, [limit])
    return [
        {
            "method_name": r[0],
            "calls": int(r[1]),
            "total_elapsed_s": float(r[2] or 0),
            "total_bytes": int(r[3] or 0),
            "avg_elapsed_s": float(r[4] or 0),
            "throttle_count": int(r[5] or 0),
            "error_count": int(r[6] or 0),
        }
        for r in rows
    ]


async def api_latency_trend(
    method_name: str | None = None,
    bucket: str = "day",
    days: int = 30,
) -> list[dict[str, Any]]:
    """P50/P95 latency per time bucket, optionally filtered to one method."""
    if bucket not in ("hour", "day", "week"):
        raise ValueError(f"bucket must be hour/day/week, got {bucket!r}")
    cutoff = f"now() - INTERVAL {days} DAY"
    method_clause = "AND method_name = ?" if method_name else ""
    params: list[Any] = [method_name] if method_name else []
    sql = f"""
        SELECT
            time_bucket(INTERVAL 1 {bucket}, to_timestamp(ts)) AS bucket_start,
            ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY elapsed_s), 4) AS p50,
            ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY elapsed_s), 4) AS p95,
            COUNT(*) AS n
        FROM {ATTACH_ALIAS}.api_call_log
        WHERE ts >= epoch(({cutoff}))
          AND ok = 1
          {method_clause}
        GROUP BY bucket_start
        ORDER BY bucket_start;
    """
    rows = await run(sql, params if params else None)
    return [
        {
            "bucket_start": r[0].isoformat() if r[0] else None,
            "p50": float(r[1] or 0),
            "p95": float(r[2] or 0),
            "count": int(r[3]),
        }
        for r in rows
    ]


async def api_throttle_events(
    days: int = 30,
) -> list[dict[str, Any]]:
    """Throttle events grouped by day and method."""
    cutoff = f"now() - INTERVAL {days} DAY"
    sql = f"""
        SELECT
            CAST(to_timestamp(ts) AS DATE) AS day,
            method_name,
            COUNT(*) AS n
        FROM {ATTACH_ALIAS}.api_call_log
        WHERE ts >= epoch(({cutoff}))
          AND throttled = 1
        GROUP BY day, method_name
        ORDER BY day DESC, n DESC;
    """
    rows = await run(sql)
    return [{"day": str(r[0]), "method_name": r[1], "count": int(r[2])} for r in rows]


async def api_data_volume(
    days: int = 30,
) -> list[dict[str, Any]]:
    """Total MB transferred per day."""
    cutoff = f"now() - INTERVAL {days} DAY"
    sql = f"""
        SELECT
            CAST(to_timestamp(ts) AS DATE) AS day,
            ROUND(SUM(payload_bytes) / 1048576.0, 4) AS mb
        FROM {ATTACH_ALIAS}.api_call_log
        WHERE ts >= epoch(({cutoff}))
        GROUP BY day
        ORDER BY day;
    """
    rows = await run(sql)
    return [{"day": str(r[0]), "mb": float(r[1] or 0)} for r in rows]


async def api_error_rate(
    days: int = 30,
) -> list[dict[str, Any]]:
    """Daily error count and rate (errors / total calls)."""
    cutoff = f"now() - INTERVAL {days} DAY"
    sql = f"""
        SELECT
            CAST(to_timestamp(ts) AS DATE) AS day,
            COUNT(*) AS total,
            SUM(CASE WHEN ok = 0 THEN 1 ELSE 0 END) AS errors,
            ROUND(SUM(CASE WHEN ok = 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*), 4) AS rate
        FROM {ATTACH_ALIAS}.api_call_log
        WHERE ts >= epoch(({cutoff}))
        GROUP BY day
        ORDER BY day;
    """
    rows = await run(sql)
    return [
        {
            "day": str(r[0]),
            "total": int(r[1]),
            "errors": int(r[2] or 0),
            "rate": float(r[3] or 0),
        }
        for r in rows
    ]


async def api_summary(days: int = 7) -> dict[str, Any]:
    """Aggregate totals for summary cards."""
    cutoff = f"now() - INTERVAL {days} DAY"
    sql = f"""
        SELECT
            COUNT(*) AS total_calls,
            ROUND(SUM(payload_bytes) / 1048576.0, 3) AS total_mb,
            SUM(CASE WHEN throttled = 1 THEN 1 ELSE 0 END) AS throttle_events,
            ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY elapsed_s), 4) AS median_latency_s
        FROM {ATTACH_ALIAS}.api_call_log
        WHERE ts >= epoch(({cutoff}));
    """
    rows = await run(sql)
    if not rows or rows[0][0] is None:
        return {"total_calls": 0, "total_mb": 0.0, "throttle_events": 0, "median_latency_s": 0.0}
    r = rows[0]
    return {
        "total_calls": int(r[0] or 0),
        "total_mb": float(r[1] or 0),
        "throttle_events": int(r[2] or 0),
        "median_latency_s": float(r[3] or 0),
    }
