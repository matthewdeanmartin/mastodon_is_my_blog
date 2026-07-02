"""Add resumable scan state to the New Friends cache.

Revision ID: 015
Revises: 014
Create Date: 2026-07-01
"""

import sqlalchemy as sa

from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("friends_of_friends_cache") as batch:
        batch.add_column(
            sa.Column(
                "source_friend_ids_json", sa.Text(), nullable=False, server_default="[]"
            )
        )
        batch.add_column(
            sa.Column(
                "next_friend_index", sa.Integer(), nullable=False, server_default="0"
            )
        )
        batch.add_column(
            sa.Column(
                "scan_max_friends", sa.Integer(), nullable=False, server_default="0"
            )
        )
        batch.add_column(sa.Column("scan_blog_roll_filter", sa.String(), nullable=True))
        batch.add_column(
            sa.Column(
                "scan_complete", sa.Boolean(), nullable=False, server_default=sa.true()
            )
        )
    op.create_index(
        "ix_posts_identity_root",
        "cached_posts",
        ["meta_account_id", "fetched_by_identity_id", "root_id", "created_at"],
    )
    op.create_index(
        "ix_accounts_meta_identity_following_activity",
        "cached_accounts",
        [
            "meta_account_id",
            "mastodon_identity_id",
            "is_following",
            "last_status_at",
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_accounts_meta_identity_following_activity", table_name="cached_accounts"
    )
    op.drop_index("ix_posts_identity_root", table_name="cached_posts")
    with op.batch_alter_table("friends_of_friends_cache") as batch:
        batch.drop_column("scan_complete")
        batch.drop_column("scan_blog_roll_filter")
        batch.drop_column("scan_max_friends")
        batch.drop_column("next_friend_index")
        batch.drop_column("source_friend_ids_json")
