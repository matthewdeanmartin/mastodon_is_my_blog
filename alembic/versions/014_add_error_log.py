"""Add error_log table for capturing WARNING+ log records

Revision ID: 014
Revises: 013
Create Date: 2026-04-25
"""

from alembic import op
import sqlalchemy as sa

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "error_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ts", sa.Float(), nullable=False),
        sa.Column("level", sa.Text(), nullable=False),
        sa.Column("logger_name", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("exc_text", sa.Text(), nullable=True),
    )
    op.create_index("ix_error_log_ts", "error_log", ["ts"])


def downgrade() -> None:
    op.drop_index("ix_error_log_ts", table_name="error_log")
    op.drop_table("error_log")
