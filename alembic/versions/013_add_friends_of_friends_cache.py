"""Add friends_of_friends_cache table for New Friends feature

Revision ID: 013
Revises: 012
Create Date: 2026-04-25
"""

import sqlalchemy as sa

from alembic import op

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "friends_of_friends_cache" in inspector.get_table_names():
        return
    op.create_table(
        "friends_of_friends_cache",
        sa.Column(
            "identity_id",
            sa.Integer(),
            sa.ForeignKey("mastodon_identities.id"),
            primary_key=True,
        ),
        sa.Column("fetched_at", sa.DateTime(), nullable=True),
        sa.Column("data_json", sa.Text(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_table("friends_of_friends_cache")
