"""
Add stable config name to Mastodon identities

Revision ID: 007
Revises: 006
Create Date: 2026-04-15
"""

import sqlalchemy as sa

from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("mastodon_identities") as batch_op:
        batch_op.add_column(sa.Column("config_name", sa.String(), nullable=True))
        batch_op.create_index(
            "ix_mastodon_identities_config_name",
            ["config_name"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("mastodon_identities") as batch_op:
        batch_op.drop_index("ix_mastodon_identities_config_name")
        batch_op.drop_column("config_name")
