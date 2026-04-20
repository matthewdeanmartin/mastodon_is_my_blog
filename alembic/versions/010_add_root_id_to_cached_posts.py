"""
Add root_id and root_is_partial columns to cached_posts for thread grouping

Revision ID: 010
Revises: 009
Create Date: 2026-04-19
"""

import sqlalchemy as sa

from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cached_posts", sa.Column("root_id", sa.String(), nullable=True))
    op.add_column("cached_posts", sa.Column("root_is_partial", sa.Boolean(), nullable=False, server_default="0"))
    op.create_index(
        "ix_posts_root_id",
        "cached_posts",
        ["meta_account_id", "root_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_posts_root_id", table_name="cached_posts")
    op.drop_column("cached_posts", "root_is_partial")
    op.drop_column("cached_posts", "root_id")
