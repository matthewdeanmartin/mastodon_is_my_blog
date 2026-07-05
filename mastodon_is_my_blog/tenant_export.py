"""Per-tenant export, purge, and usage accounting for hosted (server) mode.

This is the storage half of the control-plane hand-off API
(spec/paid_hosting/control_plane_handoff.md). Tenancy is currently
MetaAccount-rows-in-one-shared-DB, so everything here works by filtering on
``meta_account_id``. The standalone-SQLite export doubles as the code a later
shared-DB -> per-tenant-DB migration would need.

The exported file must boot under ``MIMB_MODE=local`` (business_model.md §4:
"makes leaving safe, which makes joining safe"), which requires two
transforms:

1. The MetaAccount is renamed to ``default`` — local mode resolves the
   account by ``username == "default"``.
2. ``access_token``/``client_secret`` are stripped from identities — hosted
   tokens are encrypted with the service's key (useless locally, a liability
   to ship). The user reconnects via OAuth after importing.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from sqlalchemy import Table, delete, func, insert, select
from sqlalchemy.ext.asyncio import create_async_engine

from mastodon_is_my_blog.store import (
    Base,
    CachedAccount,
    CachedMyFavourite,
    CachedNotification,
    CachedPost,
    ContentHubGroup,
    ContentHubGroupTerm,
    ContentHubPostMatch,
    Draft,
    FriendsOfFriendsCache,
    MastodonIdentity,
    MetaAccount,
    OAuthPendingConnection,
    SeenPost,
    async_session,
)

# Tables carrying a meta_account_id column, in FK-safe insert order.
# Deliberately excluded: tokens/app_state (legacy/global sync bookkeeping),
# cached_link_previews (URL-keyed shared cache), api_call_log/error_log
# (operational telemetry), oauth_pending_connections (transient secrets —
# an in-flight OAuth dance cannot survive a machine move anyway).
META_SCOPED_MODELS = (
    CachedAccount,
    CachedPost,
    CachedNotification,
    CachedMyFavourite,
    ContentHubGroup,
    ContentHubPostMatch,
    Draft,
    SeenPost,
)


async def get_tenant_meta_account(username: str) -> MetaAccount | None:
    async with async_session() as session:
        stmt = select(MetaAccount).where(MetaAccount.username == username)
        return (await session.execute(stmt)).scalar_one_or_none()


async def get_or_create_meta_account(username: str) -> tuple[MetaAccount, bool]:
    """Idempotent provision: returns (meta_account, created)."""
    async with async_session() as session:
        stmt = select(MetaAccount).where(MetaAccount.username == username)
        meta = (await session.execute(stmt)).scalar_one_or_none()
        if meta is not None:
            return meta, False
        meta = MetaAccount(username=username)
        session.add(meta)
        await session.commit()
        await session.refresh(meta)
        return meta, True


async def tenant_identity_ids(meta_account_id: int) -> list[int]:
    async with async_session() as session:
        stmt = select(MastodonIdentity.id).where(
            MastodonIdentity.meta_account_id == meta_account_id
        )
        return [row[0] for row in (await session.execute(stmt)).all()]


async def collect_tenant_rows(meta_account_id: int) -> dict[Table, list[dict[str, Any]]]:
    """Read every row belonging to one tenant, keyed by table, transformed so
    the result boots as a standalone local-mode database (see module docstring).
    """
    rows_by_table: dict[Table, list[dict[str, Any]]] = {}
    async with async_session() as session:
        meta_rows = (
            (
                await session.execute(
                    select(MetaAccount.__table__).where(
                        MetaAccount.__table__.c.id == meta_account_id
                    )
                )
            )
            .mappings()
            .all()
        )
        rows_by_table[MetaAccount.__table__] = [
            {**dict(row), "username": "default"} for row in meta_rows
        ]

        identity_table = MastodonIdentity.__table__
        identity_rows = (
            (
                await session.execute(
                    select(identity_table).where(
                        identity_table.c.meta_account_id == meta_account_id
                    )
                )
            )
            .mappings()
            .all()
        )
        rows_by_table[identity_table] = [
            {**dict(row), "access_token": "", "client_secret": ""}
            for row in identity_rows
        ]
        identity_ids = [row["id"] for row in identity_rows]

        for model in META_SCOPED_MODELS:
            table = model.__table__
            result = await session.execute(
                select(table).where(table.c.meta_account_id == meta_account_id)
            )
            rows_by_table[table] = [dict(row) for row in result.mappings().all()]

        # Scoped through the tenant's groups / identities rather than directly.
        group_ids = [row["id"] for row in rows_by_table[ContentHubGroup.__table__]]
        terms_table = ContentHubGroupTerm.__table__
        if group_ids:
            result = await session.execute(
                select(terms_table).where(terms_table.c.group_id.in_(group_ids))
            )
            rows_by_table[terms_table] = [dict(row) for row in result.mappings().all()]
        else:
            rows_by_table[terms_table] = []

        fof_table = FriendsOfFriendsCache.__table__
        if identity_ids:
            result = await session.execute(
                select(fof_table).where(fof_table.c.identity_id.in_(identity_ids))
            )
            rows_by_table[fof_table] = [dict(row) for row in result.mappings().all()]
        else:
            rows_by_table[fof_table] = []

    return rows_by_table

# Insert order matters for FKs: parents before children.
EXPORT_INSERT_ORDER = (
    MetaAccount.__table__,
    MastodonIdentity.__table__,
    CachedAccount.__table__,
    CachedPost.__table__,
    CachedNotification.__table__,
    CachedMyFavourite.__table__,
    ContentHubGroup.__table__,
    ContentHubGroupTerm.__table__,
    ContentHubPostMatch.__table__,
    Draft.__table__,
    SeenPost.__table__,
    FriendsOfFriendsCache.__table__,
)

INSERT_BATCH_SIZE = 500


async def build_tenant_sqlite_file(meta_account_id: int, dest_path: Path) -> None:
    """Dump one tenant's rows into a fresh standalone SQLite file at dest_path."""
    rows_by_table = await collect_tenant_rows(meta_account_id)

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if dest_path.exists():
        dest_path.unlink()

    dest_engine = create_async_engine(f"sqlite+aiosqlite:///{dest_path.as_posix()}")
    try:
        async with dest_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            for table in EXPORT_INSERT_ORDER:
                rows = rows_by_table.get(table, [])
                for start in range(0, len(rows), INSERT_BATCH_SIZE):
                    await conn.execute(
                        insert(table), rows[start : start + INSERT_BATCH_SIZE]
                    )
    finally:
        await dest_engine.dispose()


async def build_tenant_export_zip(
    meta_account_id: int,
    tenant_id: int,
    job_id: int | str,
    export_dir: Path,
) -> Path:
    """Build the full export bundle: standalone SQLite file + storm/blogroll
    export payloads, zipped as export_tenant_{id}_{job_id}.zip. Idempotent —
    a repeat call for the same (tenant, job) overwrites the same file.
    """
    from mastodon_is_my_blog.storm_export import (
        load_blogroll_export_data,
        load_storm_export_data,
    )

    export_dir.mkdir(parents=True, exist_ok=True)
    db_path = export_dir / f"export_tenant_{tenant_id}_{job_id}.db"
    zip_path = export_dir / f"export_tenant_{tenant_id}_{job_id}.zip"

    await build_tenant_sqlite_file(meta_account_id, db_path)
    storms = await load_storm_export_data(meta_account_id=meta_account_id)
    blogroll = await load_blogroll_export_data(meta_account_id=meta_account_id)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.write(db_path, arcname="app.db")
        bundle.writestr("blog/storms.json", json.dumps(storms, indent=2))
        bundle.writestr("blog/blogroll.json", json.dumps(blogroll, indent=2))
    db_path.unlink()
    return zip_path


async def purge_tenant_data(username: str) -> bool:
    """Delete the MetaAccount and every row scoped to it, including encrypted
    Mastodon tokens (the GDPR-relevant part). Returns False if the tenant was
    already gone. Idempotent by construction.
    """
    async with async_session() as session:
        stmt = select(MetaAccount).where(MetaAccount.username == username)
        meta = (await session.execute(stmt)).scalar_one_or_none()
        if meta is None:
            return False
        meta_id = meta.id

        group_ids_stmt = select(ContentHubGroup.id).where(
            ContentHubGroup.meta_account_id == meta_id
        )
        identity_ids_stmt = select(MastodonIdentity.id).where(
            MastodonIdentity.meta_account_id == meta_id
        )

        await session.execute(
            delete(ContentHubGroupTerm).where(
                ContentHubGroupTerm.group_id.in_(group_ids_stmt)
            )
        )
        await session.execute(
            delete(FriendsOfFriendsCache).where(
                FriendsOfFriendsCache.identity_id.in_(identity_ids_stmt)
            )
        )
        for model in META_SCOPED_MODELS:
            await session.execute(
                delete(model).where(model.meta_account_id == meta_id)
            )
        await session.execute(
            delete(OAuthPendingConnection).where(
                OAuthPendingConnection.meta_account_id == meta_id
            )
        )
        await session.execute(
            delete(MastodonIdentity).where(
                MastodonIdentity.meta_account_id == meta_id
            )
        )
        await session.execute(delete(MetaAccount).where(MetaAccount.id == meta_id))
        await session.commit()
        return True


async def tenant_usage_bytes(meta_account_id: int) -> int:
    """Approximate stored bytes for one tenant in shared-DB mode: the sum of
    the text payload columns of its cached posts and accounts. Indexes,
    notifications, and row overhead are not counted.
    """
    async with async_session() as session:
        post_bytes = (
            await session.execute(
                select(
                    func.coalesce(
                        func.sum(
                            func.length(CachedPost.content)
                            + func.length(func.coalesce(CachedPost.media_attachments, ""))
                            + func.length(func.coalesce(CachedPost.tags, ""))
                        ),
                        0,
                    )
                ).where(CachedPost.meta_account_id == meta_account_id)
            )
        ).scalar_one()
        account_bytes = (
            await session.execute(
                select(
                    func.coalesce(
                        func.sum(
                            func.length(CachedAccount.note)
                            + func.length(CachedAccount.fields)
                            + func.length(CachedAccount.display_name)
                        ),
                        0,
                    )
                ).where(CachedAccount.meta_account_id == meta_account_id)
            )
        ).scalar_one()
    return int(post_bytes) + int(account_bytes)
