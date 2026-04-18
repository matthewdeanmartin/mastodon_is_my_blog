"""Add has_job column to cached_posts

Revision ID: 008
Revises: 007
Create Date: 2026-04-18
"""

import sqlalchemy as sa
from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("cached_posts") as batch_op:
        batch_op.add_column(
            sa.Column("has_job", sa.Boolean(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("cached_posts") as batch_op:
        batch_op.drop_column("has_job")
