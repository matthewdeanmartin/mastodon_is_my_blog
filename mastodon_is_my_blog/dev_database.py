from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from mastodon_is_my_blog.environment import load_environment


def require_postgres_url(db_url: str | None) -> str:
    if not db_url:
        raise SystemExit(
            "make dev requires DB_URL in .env. "
            "Set it to postgresql+asyncpg://USER:PASSWORD@HOST:PORT/DATABASE."
        )
    url = make_url(db_url)
    if not url.drivername.startswith("postgresql"):
        raise SystemExit(
            f"make dev requires Postgres, but DB_URL selects {url.drivername!r}. "
            "Use make dev-sqlite for SQLite."
        )
    if url.drivername != "postgresql+asyncpg":
        url = url.set(drivername="postgresql+asyncpg")
    return url.render_as_string(hide_password=False)


async def inspect_database(db_url: str) -> None:
    url = make_url(db_url)
    display_url = url.render_as_string(hide_password=True)
    engine = create_async_engine(db_url)
    try:
        async with engine.connect() as connection:
            database = await connection.scalar(text("SELECT current_database()"))
            posts = await connection.scalar(text("SELECT to_regclass('public.cached_posts')"))
            accounts = await connection.scalar(text("SELECT to_regclass('public.cached_accounts')"))
            post_count = await connection.scalar(text("SELECT count(*) FROM cached_posts")) if posts else 0
            account_count = await connection.scalar(text("SELECT count(*) FROM cached_accounts")) if accounts else 0
    except Exception as exc:
        raise SystemExit(f"Cannot start development server: failed to connect to {display_url}: {exc}") from exc
    finally:
        await engine.dispose()

    print("Development database preflight")
    print("  backend:  postgres")
    print(f"  location: {display_url}")
    print(f"  database: {database}")
    print(f"  data:     {post_count:,} posts, {account_count:,} accounts")
    if post_count == 0 and account_count == 0:
        print("  warning:  database contains no cached application data")


def main() -> None:
    load_environment()
    import os

    db_url = require_postgres_url(os.environ.get("DB_URL"))
    asyncio.run(inspect_database(db_url))


if __name__ == "__main__":
    main()
