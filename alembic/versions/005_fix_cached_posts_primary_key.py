"""
fix cached_posts primary key to include fetched_by_identity_id

The ORM model defines (id, meta_account_id, fetched_by_identity_id) as the
composite primary key, but the original table was created with only
(id, meta_account_id). This caused ON CONFLICT clauses in bulk upserts to fail
because the conflict target didn't match any unique constraint.

SQLite cannot ALTER TABLE to change a primary key, so we recreate the table.

Revision ID: 005
Revises: 004
Create Date: 2026-04-12
"""


from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None

# All column definitions matching the current ORM model
COLUMNS = """
    id VARCHAR NOT NULL,
    meta_account_id INTEGER NOT NULL,
    fetched_by_identity_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at DATETIME NOT NULL,
    visibility VARCHAR(20) NOT NULL,
    author_acct VARCHAR NOT NULL,
    author_id VARCHAR NOT NULL,
    is_reblog BOOLEAN NOT NULL,
    is_reply BOOLEAN NOT NULL,
    in_reply_to_id VARCHAR,
    in_reply_to_account_id VARCHAR,
    has_media BOOLEAN NOT NULL,
    has_video BOOLEAN NOT NULL,
    has_news BOOLEAN NOT NULL,
    has_tech BOOLEAN NOT NULL,
    has_link BOOLEAN NOT NULL,
    has_question BOOLEAN NOT NULL,
    media_attachments TEXT,
    tags TEXT,
    replies_count INTEGER NOT NULL,
    reblogs_count INTEGER NOT NULL,
    favourites_count INTEGER NOT NULL,
    PRIMARY KEY (id, meta_account_id, fetched_by_identity_id),
    FOREIGN KEY(meta_account_id) REFERENCES meta_accounts (id),
    FOREIGN KEY(fetched_by_identity_id) REFERENCES mastodon_identities (id)
"""


def upgrade() -> None:
    # 1. Create new table with the correct 3-column PK
    op.execute(f"CREATE TABLE cached_posts_new ({COLUMNS})")

    # 2. Copy all data; rows with NULL fetched_by_identity_id would fail the NOT NULL
    #    constraint, but we verified there are none in the live DB.
    op.execute("""
        INSERT INTO cached_posts_new
        SELECT
            id, meta_account_id, fetched_by_identity_id,
            content, created_at, visibility, author_acct, author_id,
            is_reblog, is_reply, in_reply_to_id, in_reply_to_account_id,
            has_media, has_video, has_news, has_tech, has_link, has_question,
            media_attachments, tags,
            replies_count, reblogs_count, favourites_count
        FROM cached_posts
    """)

    # 3. Drop old table and rename
    op.execute("DROP TABLE cached_posts")
    op.execute("ALTER TABLE cached_posts_new RENAME TO cached_posts")

    # 4. Recreate all indexes (dropped with the old table)
    op.create_index("ix_cached_posts_author_acct", "cached_posts", ["author_acct"])
    op.create_index("ix_cached_posts_author_id", "cached_posts", ["author_id"])
    op.create_index(
        "ix_posts_meta_author",
        "cached_posts",
        ["meta_account_id", "author_acct", "created_at"],
    )
    op.create_index(
        "ix_posts_meta_clean",
        "cached_posts",
        ["meta_account_id", "is_reblog", "is_reply"],
    )
    op.create_index(
        "ix_posts_meta_created",
        "cached_posts",
        ["meta_account_id", "created_at"],
    )
    op.create_index(
        "ix_posts_meta_identity_created",
        "cached_posts",
        ["meta_account_id", "fetched_by_identity_id", "created_at"],
    )
    op.create_index(
        "ix_posts_meta_identity_author",
        "cached_posts",
        ["meta_account_id", "fetched_by_identity_id", "author_acct", "created_at"],
    )
    op.create_index(
        "ix_posts_in_reply_to",
        "cached_posts",
        ["meta_account_id", "fetched_by_identity_id", "in_reply_to_id"],
    )


def downgrade() -> None:
    # Recreate original 2-column PK table
    original_columns = (
        COLUMNS.replace(
            "PRIMARY KEY (id, meta_account_id, fetched_by_identity_id)",
            "PRIMARY KEY (id, meta_account_id)",
        )
        .replace(
            "fetched_by_identity_id INTEGER NOT NULL",
            "fetched_by_identity_id INTEGER",
        )
        .replace(
            "    FOREIGN KEY(fetched_by_identity_id) REFERENCES mastodon_identities (id)\n",
            "",
        )
    )

    op.execute(f"CREATE TABLE cached_posts_old ({original_columns})")
    op.execute("""
        INSERT INTO cached_posts_old
        SELECT
            id, meta_account_id, fetched_by_identity_id,
            content, created_at, visibility, author_acct, author_id,
            is_reblog, is_reply, in_reply_to_id, in_reply_to_account_id,
            has_media, has_video, has_news, has_tech, has_link, has_question,
            media_attachments, tags,
            replies_count, reblogs_count, favourites_count
        FROM cached_posts
    """)
    op.execute("DROP TABLE cached_posts")
    op.execute("ALTER TABLE cached_posts_old RENAME TO cached_posts")

    # Recreate indexes
    op.create_index("ix_cached_posts_author_acct", "cached_posts", ["author_acct"])
    op.create_index("ix_cached_posts_author_id", "cached_posts", ["author_id"])
    op.create_index(
        "ix_posts_meta_author",
        "cached_posts",
        ["meta_account_id", "author_acct", "created_at"],
    )
    op.create_index(
        "ix_posts_meta_clean",
        "cached_posts",
        ["meta_account_id", "is_reblog", "is_reply"],
    )
    op.create_index(
        "ix_posts_meta_created",
        "cached_posts",
        ["meta_account_id", "created_at"],
    )
    op.create_index(
        "ix_posts_meta_identity_created",
        "cached_posts",
        ["meta_account_id", "fetched_by_identity_id", "created_at"],
    )
    op.create_index(
        "ix_posts_meta_identity_author",
        "cached_posts",
        ["meta_account_id", "fetched_by_identity_id", "author_acct", "created_at"],
    )
    op.create_index(
        "ix_posts_in_reply_to",
        "cached_posts",
        ["meta_account_id", "fetched_by_identity_id", "in_reply_to_id"],
    )
