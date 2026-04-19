"""
add cached_link_previews table

Revision ID: 004
Revises: 003
Create Date: 2026-04-11
"""

import sqlalchemy as sa

from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cached_link_previews",
        sa.Column("url_key", sa.String(), nullable=False),
        sa.Column("final_url", sa.String(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("site_name", sa.Text(), nullable=True),
        sa.Column("image", sa.String(), nullable=True),
        sa.Column("favicon", sa.String(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="ok"),
        sa.Column("fetched_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("error_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("url_key"),
    )
    op.create_index("ix_card_expires", "cached_link_previews", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_card_expires", table_name="cached_link_previews")
    op.drop_table("cached_link_previews")
