"""Backfill the columns that used to be added by the sqlite-only
``ensure_cached_posts_schema`` / ``ensure_meta_accounts_schema`` PRAGMA shims in
store.py.

Those helpers ran ``PRAGMA table_info`` + ``ALTER TABLE ... ADD COLUMN`` at
startup so pre-existing *local SQLite* DBs gained columns without a migration.
That path is skipped on turso/postgres (Phase 1), so those backends need the
columns created here as a real migration. On a fresh DB ``create_all`` already
made the columns; this revision only adds them where missing, mirroring the old
idempotent shim.

See spec/turso_support_phases.md (Phase 2).

Revision ID: 016
Revises: 015
Create Date: 2026-07-08
"""

import sqlalchemy as sa

from alembic import op

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    posts_cols = _columns("cached_posts")
    with op.batch_alter_table("cached_posts") as batch:
        if "actor_acct" not in posts_cols:
            batch.add_column(sa.Column("actor_acct", sa.String(), nullable=True))
        if "actor_id" not in posts_cols:
            batch.add_column(sa.Column("actor_id", sa.String(), nullable=True))
        if "has_book" not in posts_cols:
            batch.add_column(
                sa.Column(
                    "has_book", sa.Boolean(), nullable=False, server_default=sa.false()
                )
            )

    # Backfill actor_* from author_* for rows predating those columns (the old
    # shim did the same UPDATE).
    op.execute(
        "UPDATE cached_posts "
        "SET actor_acct = COALESCE(actor_acct, author_acct), "
        "    actor_id = COALESCE(actor_id, author_id) "
        "WHERE actor_acct IS NULL OR actor_id IS NULL"
    )
    op.create_index(
        "ix_posts_meta_actor",
        "cached_posts",
        ["meta_account_id", "actor_acct", "created_at"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_posts_meta_identity_actor",
        "cached_posts",
        ["meta_account_id", "fetched_by_identity_id", "actor_acct", "created_at"],
        if_not_exists=True,
    )

    meta_cols = _columns("meta_accounts")
    with op.batch_alter_table("meta_accounts") as batch:
        if "enabled" not in meta_cols:
            batch.add_column(
                sa.Column(
                    "enabled", sa.Boolean(), nullable=False, server_default=sa.true()
                )
            )
        if "max_identities" not in meta_cols:
            batch.add_column(sa.Column("max_identities", sa.Integer(), nullable=True))
        if "max_storage_bytes" not in meta_cols:
            batch.add_column(
                sa.Column("max_storage_bytes", sa.Integer(), nullable=True)
            )


def downgrade() -> None:
    op.drop_index("ix_posts_meta_identity_actor", table_name="cached_posts")
    op.drop_index("ix_posts_meta_actor", table_name="cached_posts")
    with op.batch_alter_table("meta_accounts") as batch:
        batch.drop_column("max_storage_bytes")
        batch.drop_column("max_identities")
        batch.drop_column("enabled")
    with op.batch_alter_table("cached_posts") as batch:
        batch.drop_column("has_book")
        batch.drop_column("actor_id")
        batch.drop_column("actor_acct")
