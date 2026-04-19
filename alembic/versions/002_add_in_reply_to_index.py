"""
add in_reply_to index for storm queries

Revision ID: 002
Revises: 001
Create Date: 2026-04-11
"""

from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_posts_in_reply_to",
        "cached_posts",
        ["meta_account_id", "fetched_by_identity_id", "in_reply_to_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_posts_in_reply_to", table_name="cached_posts")
