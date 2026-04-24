"""Add api_call_log table for observability

Revision ID: 012
Revises: 011
Create Date: 2026-04-23
"""

from alembic import op
import sqlalchemy as sa

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_call_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ts", sa.Float(), nullable=False),
        sa.Column("method_name", sa.Text(), nullable=False),
        sa.Column("identity_acct", sa.Text(), nullable=True),
        sa.Column("elapsed_s", sa.Float(), nullable=False),
        sa.Column("payload_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ok", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("throttled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_type", sa.Text(), nullable=True),
    )
    op.create_index("ix_api_call_log_ts", "api_call_log", ["ts"])
    op.create_index("ix_api_call_log_method_ts", "api_call_log", ["method_name", "ts"])


def downgrade() -> None:
    op.drop_index("ix_api_call_log_method_ts", table_name="api_call_log")
    op.drop_index("ix_api_call_log_ts", table_name="api_call_log")
    op.drop_table("api_call_log")
