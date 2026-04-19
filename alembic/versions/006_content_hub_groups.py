"""
Add content hub tables and extend cached_posts with discovery metadata

New tables: content_hub_groups, content_hub_group_terms, content_hub_post_matches
New columns on cached_posts: discovery_source, content_hub_only

Revision ID: 006
Revises: 005
Create Date: 2026-04-12
"""

import sqlalchemy as sa

from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Extend cached_posts ---
    with op.batch_alter_table("cached_posts") as batch_op:
        batch_op.add_column(
            sa.Column(
                "discovery_source",
                sa.String(20),
                nullable=False,
                server_default="timeline",
            )
        )
        batch_op.add_column(
            sa.Column(
                "content_hub_only",
                sa.Boolean,
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.create_index(
            "ix_posts_content_hub_only",
            ["meta_account_id", "fetched_by_identity_id", "content_hub_only"],
        )

    # --- content_hub_groups ---
    op.create_table(
        "content_hub_groups",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "meta_account_id",
            sa.Integer,
            sa.ForeignKey("meta_accounts.id"),
            nullable=False,
        ),
        sa.Column(
            "identity_id",
            sa.Integer,
            sa.ForeignKey("mastodon_identities.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("slug", sa.String, nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column(
            "is_read_only", sa.Boolean, nullable=False, server_default=sa.false()
        ),
        sa.Column("last_fetched_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index(
        "ix_hub_groups_identity",
        "content_hub_groups",
        ["meta_account_id", "identity_id"],
    )
    op.create_index(
        "ix_hub_groups_slug",
        "content_hub_groups",
        ["meta_account_id", "identity_id", "slug"],
    )

    # --- content_hub_group_terms ---
    op.create_table(
        "content_hub_group_terms",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "group_id",
            sa.Integer,
            sa.ForeignKey("content_hub_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("term", sa.String, nullable=False),
        sa.Column("term_type", sa.String(20), nullable=False),
        sa.Column("normalized_term", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_hub_terms_group", "content_hub_group_terms", ["group_id"])
    op.create_index(
        "ix_hub_terms_normalized", "content_hub_group_terms", ["normalized_term"]
    )

    # --- content_hub_post_matches ---
    op.create_table(
        "content_hub_post_matches",
        sa.Column(
            "group_id",
            sa.Integer,
            sa.ForeignKey("content_hub_groups.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("post_id", sa.String, primary_key=True),
        sa.Column(
            "meta_account_id",
            sa.Integer,
            sa.ForeignKey("meta_accounts.id"),
            primary_key=True,
        ),
        sa.Column(
            "fetched_by_identity_id",
            sa.Integer,
            sa.ForeignKey("mastodon_identities.id"),
            nullable=False,
        ),
        sa.Column(
            "matched_term_id",
            sa.Integer,
            sa.ForeignKey("content_hub_group_terms.id"),
            nullable=True,
        ),
        sa.Column("matched_via", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index(
        "ix_hub_matches_group_post",
        "content_hub_post_matches",
        ["group_id", "meta_account_id"],
    )
    op.create_index(
        "ix_hub_matches_post",
        "content_hub_post_matches",
        ["post_id", "meta_account_id"],
    )


def downgrade() -> None:
    op.drop_table("content_hub_post_matches")
    op.drop_table("content_hub_group_terms")
    op.drop_table("content_hub_groups")

    with op.batch_alter_table("cached_posts") as batch_op:
        batch_op.drop_index("ix_posts_content_hub_only")
        batch_op.drop_column("content_hub_only")
        batch_op.drop_column("discovery_source")
