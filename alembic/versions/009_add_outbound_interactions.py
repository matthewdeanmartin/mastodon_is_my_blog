"""Add cached_my_favourites table for outbound favourite tracking

Revision ID: 009
Revises: 008
Create Date: 2026-04-18
"""

import sqlalchemy as sa
from alembic import op

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cached_my_favourites",
        sa.Column("status_id", sa.String(), nullable=False),
        sa.Column("meta_account_id", sa.Integer(), nullable=False),
        sa.Column("identity_id", sa.Integer(), nullable=False),
        sa.Column("target_account_id", sa.String(), nullable=False),
        sa.Column("target_acct", sa.String(), nullable=False),
        sa.Column("favourited_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["meta_account_id"], ["meta_accounts.id"]),
        sa.ForeignKeyConstraint(["identity_id"], ["mastodon_identities.id"]),
        sa.PrimaryKeyConstraint("status_id", "meta_account_id", "identity_id"),
    )
    op.create_index(
        "ix_my_favourites_target_account",
        "cached_my_favourites",
        ["meta_account_id", "identity_id", "target_account_id"],
    )
    op.create_index(
        "ix_my_favourites_favourited_at",
        "cached_my_favourites",
        ["meta_account_id", "identity_id", "favourited_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_my_favourites_favourited_at", table_name="cached_my_favourites")
    op.drop_index("ix_my_favourites_target_account", table_name="cached_my_favourites")
    op.drop_table("cached_my_favourites")
