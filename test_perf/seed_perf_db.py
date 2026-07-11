"""
Seed a realistic, large (~1 GB by default) mimb database for performance
baselining.

The script writes through the app's own SQLAlchemy engine, so the *same*
seeder fills either backend — point it at the target with the usual env vars
before running (they are read at import time by ``store.py``):

    # sqlite (file path of your choice)
    DB_URL=sqlite+aiosqlite:///perf/mimb_perf.db \
        uv run python -m test_perf.seed_perf_db --target-mb 1000

    # postgres
    DB_BACKEND=postgres APP_POSTGRES_URL=postgresql://user:pw@localhost/mimb_perf \
        uv run python -m test_perf.seed_perf_db --target-mb 1000

The data shape mirrors what a long-running install accumulates and is tuned so
every query benchmarked in test_perf/ has real work to do:

* cached_posts spread over N months (denser recently), ~25% replies attached
  to thread roots (feeds ``forum_thread_summaries``), hashtags with a zipf
  distribution (``hashtag_trends``/``hashtag_counts``), content-flag booleans
  (``get_counts_optimized``), HTML content of realistic length.
* cached_notifications concentrated in the last 90 days so the
  ``now() - INTERVAL`` windows in ``top_reposters`` see rows.
* seen_posts for a slice of recent posts (unread-count queries).
* api_call_log rows over the last 30 days (api_* analytics).

Deterministic (seeded RNG): re-running against a fresh DB produces the same
database, so baselines stay comparable across reseeds.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, insert, select

# Post row overhead beyond the HTML content itself (ids, flags, tags, index
# entries). Used only to convert --target-mb into a post count.
APPROX_BYTES_PER_POST_OVERHEAD = 260
MEAN_CONTENT_CHARS = 620

WORDS = (
    "the quick brown fox jumps over lazy dog fediverse mastodon server post "
    "reply thread boost favourite follow hashtag timeline instance federation "
    "python rust linux debugging coffee garden bicycle weather election news "
    "book reading music album guitar photography camera lens hiking mountain "
    "recipe sourdough kubernetes deploy database index query performance cache "
    "birds migration climate science paper preprint conference talk keynote"
).split()

TAG_POOL_SIZE = 500
RECENT_ROOTS_WINDOW = 400


def snowflake(i: int) -> str:
    """Increasing Mastodon-style numeric string ids."""
    return str(110_000_000_000_000_000 + i * 1_000)


def make_content(rng: random.Random) -> str:
    # Log-normal-ish length: mostly short-to-medium posts, a long tail.
    n_words = max(5, int(rng.lognormvariate(4.3, 0.7)))  # median ~74 words
    words = rng.choices(WORDS, k=n_words)
    return "<p>" + " ".join(words) + "</p>"


def spread_created_at(rng: random.Random, months: int, now: datetime) -> datetime:
    """Spread over `months`, quadratically denser toward the present."""
    frac = rng.random() ** 2  # 0 = now, 1 = oldest
    delta = timedelta(days=frac * months * 30.44, seconds=rng.randrange(86_400))
    return now - delta


def build_post(
    rng: random.Random,
    i: int,
    *,
    meta_id: int,
    identity_id: int,
    accounts: list[tuple[str, str]],
    tag_weights: list[int],
    recent_roots: list[tuple[str, str, datetime]],
    months: int,
    now: datetime,
) -> dict:
    post_id = snowflake(i)
    author_id, author_acct = accounts[int(len(accounts) * rng.random() ** 2)]

    is_reply = bool(recent_roots) and rng.random() < 0.25
    if is_reply:
        root_id, root_author, root_created = rng.choice(recent_roots)
        in_reply_to_id = root_id
        created_at = root_created + timedelta(minutes=rng.randrange(1, 2_880))
    else:
        root_id = post_id
        in_reply_to_id = None
        created_at = spread_created_at(rng, months, now)
        recent_roots.append((post_id, author_id, created_at))
        if len(recent_roots) > RECENT_ROOTS_WINDOW:
            recent_roots.pop(0)

    tags: list[str] = []
    if rng.random() < 0.4:
        tags = [f"tag{t}" for t in rng.choices(range(TAG_POOL_SIZE), weights=tag_weights, k=rng.randint(1, 3))]

    is_reblog = not is_reply and rng.random() < 0.15
    return {
        "id": post_id,
        "meta_account_id": meta_id,
        "fetched_by_identity_id": identity_id,
        "content": make_content(rng),
        "discovery_source": "timeline",
        "content_hub_only": rng.random() < 0.03,
        "created_at": created_at,
        "visibility": "public",
        "author_acct": author_acct,
        "author_id": author_id,
        "actor_acct": author_acct,
        "actor_id": author_id,
        "is_reblog": is_reblog,
        "is_reply": is_reply,
        "in_reply_to_id": in_reply_to_id,
        "in_reply_to_account_id": None,
        "has_media": rng.random() < 0.18,
        "has_video": rng.random() < 0.05,
        "has_news": rng.random() < 0.08,
        "has_tech": rng.random() < 0.10,
        "has_link": rng.random() < 0.25,
        "has_job": rng.random() < 0.01,
        "has_question": rng.random() < 0.07,
        "has_book": rng.random() < 0.03,
        "media_attachments": None,
        "tags": json.dumps(tags),
        "replies_count": rng.randrange(4),
        "reblogs_count": rng.randrange(10),
        "favourites_count": rng.randrange(25),
        "root_id": root_id,
        "root_is_partial": False,
        "thread_uncommon_words": (json.dumps(rng.choices(WORDS, k=3)) if not is_reply and rng.random() < 0.1 else None),
    }


async def seed(args: argparse.Namespace) -> None:
    # Imported here so callers can set DB_URL/DB_BACKEND env first.
    from mastodon_is_my_blog.store import (
        ApiCallLog,
        Base,
        CachedAccount,
        CachedNotification,
        CachedPost,
        MastodonIdentity,
        MetaAccount,
        SeenPost,
        engine,
    )

    print(f"Seeding via engine: {engine.url.render_as_string(hide_password=True)}")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with engine.begin() as conn:
        existing = (await conn.execute(select(func.count()).select_from(CachedPost.__table__))).scalar_one()
    if existing and not args.append:
        sys.exit(f"Refusing to seed: cached_posts already has {existing:,} rows. Point DB_URL at a fresh database, or pass --append.")

    rng = random.Random(42)
    # Naive UTC to match the app's DateTime columns.
    now = datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None)

    n_posts = args.posts or max(10_000, (args.target_mb * 1_048_576) // (MEAN_CONTENT_CHARS + APPROX_BYTES_PER_POST_OVERHEAD))
    n_accounts = args.accounts
    n_notifications = n_posts // 6
    print(f"Plan: {n_posts:,} posts, {n_accounts:,} accounts, {n_notifications:,} notifications (~{args.target_mb} MB target)")

    # --- meta account + identity ------------------------------------------
    async with engine.begin() as conn:
        row = (await conn.execute(select(MetaAccount.__table__.c.id).where(MetaAccount.__table__.c.id == args.meta_id))).first()
        if not row:
            await conn.execute(insert(MetaAccount.__table__).values(id=args.meta_id, username="perf", created_at=now, enabled=True))
        row = (await conn.execute(select(MastodonIdentity.__table__.c.id).where(MastodonIdentity.__table__.c.id == args.identity_id))).first()
        if not row:
            await conn.execute(
                insert(MastodonIdentity.__table__).values(
                    id=args.identity_id,
                    meta_account_id=args.meta_id,
                    api_base_url="https://perf.example",
                    client_id="perf-client",
                    client_secret="perf-secret",
                    access_token="perf-token",
                    acct="perf@perf.example",
                    account_id="1",
                )
            )

    # --- accounts -----------------------------------------------------------
    accounts = [(f"9{i:08d}", f"user{i}@perf.example") for i in range(n_accounts)]
    account_rows = [
        {
            "id": acct_id,
            "meta_account_id": args.meta_id,
            "mastodon_identity_id": args.identity_id,
            "acct": acct,
            "display_name": acct.split("@")[0].title(),
            "avatar": "https://perf.example/avatar.png",
            "url": f"https://perf.example/@{acct.split('@')[0]}",
            "note": "",
            "bot": False,
            "locked": False,
            "created_at": now - timedelta(days=rng.randrange(2000)),
            "header": "",
            "fields": "[]",
            "followers_count": rng.randrange(5_000),
            "following_count": rng.randrange(2_000),
            "statuses_count": rng.randrange(20_000),
            "is_following": rng.random() < 0.5,
            "is_followed_by": rng.random() < 0.3,
            "last_status_at": now - timedelta(days=rng.randrange(90)),
            "cached_post_count": 0,
            "cached_reply_count": 0,
        }
        for acct_id, acct in accounts
    ]
    async with engine.begin() as conn:
        await conn.execute(insert(CachedAccount.__table__), account_rows)
    print(f"  accounts: {n_accounts:,} done")

    # zipf-ish tag popularity
    tag_weights = [max(1, int(10_000 / (rank + 1))) for rank in range(TAG_POOL_SIZE)]

    # --- posts ---------------------------------------------------------------
    t0 = time.monotonic()
    recent_roots: list[tuple[str, str, datetime]] = []
    seen_candidates: list[str] = []
    batch: list[dict] = []
    written = 0
    for i in range(n_posts):
        post = build_post(
            rng,
            i,
            meta_id=args.meta_id,
            identity_id=args.identity_id,
            accounts=accounts,
            tag_weights=tag_weights,
            recent_roots=recent_roots,
            months=args.months,
            now=now,
        )
        batch.append(post)
        if rng.random() < 0.25:
            seen_candidates.append(post["id"])
        if len(batch) >= args.batch_size:
            async with engine.begin() as conn:
                await conn.execute(insert(CachedPost.__table__), batch)
            written += len(batch)
            batch = []
            if written % 100_000 < args.batch_size:
                rate = written / (time.monotonic() - t0)
                print(f"  posts: {written:,}/{n_posts:,} ({rate:,.0f} rows/s)")
    if batch:
        async with engine.begin() as conn:
            await conn.execute(insert(CachedPost.__table__), batch)
        written += len(batch)
    print(f"  posts: {written:,} done in {time.monotonic() - t0:,.0f}s")

    # --- notifications (recent-heavy so windowed queries see rows) -----------
    notif_rows = []
    for i in range(n_notifications):
        acct_id, acct = rng.choice(accounts)
        notif_rows.append(
            {
                "id": f"n{i}",
                "meta_account_id": args.meta_id,
                "identity_id": args.identity_id,
                "type": rng.choices(["mention", "favourite", "reblog", "follow"], weights=[3, 5, 3, 1])[0],
                "created_at": now - timedelta(days=90 * rng.random() ** 2, seconds=rng.randrange(86_400)),
                "account_id": acct_id,
                "account_acct": acct,
                "status_id": snowflake(rng.randrange(n_posts)),
            }
        )
        if len(notif_rows) >= args.batch_size:
            async with engine.begin() as conn:
                await conn.execute(insert(CachedNotification.__table__), notif_rows)
            notif_rows = []
    if notif_rows:
        async with engine.begin() as conn:
            await conn.execute(insert(CachedNotification.__table__), notif_rows)
    print(f"  notifications: {n_notifications:,} done")

    # --- seen posts -----------------------------------------------------------
    seen_rows = [{"post_id": pid, "meta_account_id": args.meta_id, "seen_at": now - timedelta(days=rng.randrange(60))} for pid in seen_candidates]
    for start in range(0, len(seen_rows), args.batch_size):
        async with engine.begin() as conn:
            await conn.execute(insert(SeenPost.__table__), seen_rows[start : start + args.batch_size])
    print(f"  seen_posts: {len(seen_rows):,} done")

    # --- api call log ----------------------------------------------------------
    api_rows = [
        {
            "ts": time.time() - rng.random() * 30 * 86_400,
            "method_name": rng.choice(["timeline_home", "account_statuses", "notifications", "status_post"]),
            "identity_acct": "perf@perf.example",
            "elapsed_s": rng.random() * 2,
            "payload_bytes": rng.randrange(100_000),
            "ok": 1 if rng.random() > 0.02 else 0,
            "throttled": 1 if rng.random() < 0.01 else 0,
            "error_type": None,
        }
        for _ in range(args.api_calls)
    ]
    for start in range(0, len(api_rows), args.batch_size):
        async with engine.begin() as conn:
            await conn.execute(insert(ApiCallLog.__table__), api_rows[start : start + args.batch_size])
    print(f"  api_call_log: {len(api_rows):,} done")

    async with engine.begin() as conn:
        total = (await conn.execute(select(func.count()).select_from(CachedPost.__table__))).scalar_one()
    await engine.dispose()
    print(f"Done. cached_posts now holds {total:,} rows.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target-mb", type=int, default=1000, help="approximate target size (default 1000)")
    parser.add_argument("--posts", type=int, default=0, help="explicit post count (overrides --target-mb)")
    parser.add_argument("--accounts", type=int, default=3000)
    parser.add_argument("--months", type=int, default=18, help="history depth for post timestamps")
    parser.add_argument("--api-calls", type=int, default=50_000)
    parser.add_argument("--batch-size", type=int, default=5_000)
    parser.add_argument("--meta-id", type=int, default=1)
    parser.add_argument("--identity-id", type=int, default=1)
    parser.add_argument("--append", action="store_true", help="allow seeding into a non-empty database")
    asyncio.run(seed(parser.parse_args()))


if __name__ == "__main__":
    main()
