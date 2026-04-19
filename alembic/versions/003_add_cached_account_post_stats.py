"""
add cached post stats to cached_accounts

Revision ID: 003
Revises: 002
Create Date: 2026-04-11
"""

import sqlalchemy as sa

from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cached_accounts",
        sa.Column(
            "cached_post_count", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "cached_accounts",
        sa.Column(
            "cached_reply_count", sa.Integer(), nullable=False, server_default="0"
        ),
    )


def downgrade() -> None:
    op.drop_column("cached_accounts", "cached_reply_count")
    op.drop_column("cached_accounts", "cached_post_count")
