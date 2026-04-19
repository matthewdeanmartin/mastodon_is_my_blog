"""
add identity composite indexes

Revision ID: 001
Revises:
Create Date: 2026-04-11
"""

from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_posts_meta_identity_created",
        "cached_posts",
        ["meta_account_id", "fetched_by_identity_id", "created_at"],
    )
    op.create_index(
        "ix_posts_meta_identity_author",
        "cached_posts",
        ["meta_account_id", "fetched_by_identity_id", "author_acct", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_posts_meta_identity_author", table_name="cached_posts")
    op.drop_index("ix_posts_meta_identity_created", table_name="cached_posts")
