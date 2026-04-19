from __future__ import annotations

import argparse
import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from html import unescape
from pathlib import Path
from typing import Any
from collections.abc import Sequence

from bs4 import BeautifulSoup
from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "app.db"
os.environ.setdefault("DB_URL", f"sqlite+aiosqlite:///{DEFAULT_DB_PATH.as_posix()}")

from mastodon_is_my_blog.store import (
    CachedAccount,
    CachedNotification,
    CachedPost,
    MastodonIdentity,
    async_session,
    engine,
)

DEFAULT_MIN_TEXT_LENGTH = 495
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "docs-src" / "src" / "_data" / "storms.json"
DEFAULT_BLOGROLL_OUTPUT_PATH = (
    PROJECT_ROOT / "docs-src" / "src" / "_data" / "blogroll.json"
)
BLOGROLL_NOTIFICATION_TYPES = frozenset({"mention", "favourite", "reblog", "status"})
BLOGROLL_CATEGORY_TITLES = {
    "top_friends": "Top Friends",
    "mutuals": "Mutuals",
    "bots": "Bots",
}
BLOGROLL_CATEGORY_PRIORITIES = {
    "mutuals": 1,
    "top_friends": 2,
    "bots": 3,
}


@dataclass(frozen=True)
class AuthorSummary:
    acct: str
    api_base_url: str
    account_id: str
    storm_count: int


def clean_mastodon_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for link in soup.find_all("a"):
        link.decompose()

    text = unescape(soup.get_text(" ", strip=True))
    return re.sub(r"\s+", " ", text).strip()


def count_cleaned_characters(html: str) -> int:
    return len(clean_mastodon_text(html))


def slugify_text(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "post"


def summarize_text(text: str, *, limit: int = 180) -> str:
    if len(text) <= limit:
        return text
    clipped = text[:limit].rsplit(" ", 1)[0].strip()
    return f"{clipped}..."


def parse_media_attachments(raw_media: str | None) -> list[dict[str, Any]]:
    if not raw_media:
        return []

    attachments = json.loads(raw_media)
    parsed_media = []
    for attachment in attachments:
        url = attachment.get("url") or attachment.get("preview_url")
        preview_url = attachment.get("preview_url") or attachment.get("url")
        if not url and not preview_url:
            continue

        parsed_media.append(
            {
                "type": attachment.get("type", "unknown"),
                "url": url,
                "preview_url": preview_url,
                "description": attachment.get("description"),
            }
        )
    return parsed_media


def post_permalink(identity: MastodonIdentity, post_id: str) -> str:
    return f"{identity.api_base_url.rstrip('/')}/@{identity.acct}/{post_id}"


def mastodon_social_permalink(acct: str) -> str:
    normalized_acct = acct.lstrip("@")
    return f"https://mastodon.social/@{normalized_acct}"


def normalize_acct_key(acct: str) -> str:
    return acct.strip().lower()


def sort_posts(posts: Sequence[CachedPost]) -> list[CachedPost]:
    return sorted(posts, key=lambda post: (post.created_at, post.id))


def build_branch(
    post: CachedPost,
    *,
    identity: MastodonIdentity,
    author_id: str,
    children_map: dict[str, list[CachedPost]],
) -> dict[str, Any]:
    branches = [
        build_branch(
            child,
            identity=identity,
            author_id=author_id,
            children_map=children_map,
        )
        for child in sort_posts(children_map.get(post.id, []))
        if str(child.author_id) == author_id
    ]
    clean_text = clean_mastodon_text(post.content)
    return {
        "id": post.id,
        "created_at": post.created_at.isoformat(),
        "content_html": post.content,
        "content_text": clean_text,
        "cleaned_length": len(clean_text),
        "excerpt": summarize_text(clean_text, limit=140),
        "media": parse_media_attachments(post.media_attachments),
        "original_url": post_permalink(identity, post.id),
        "children": branches,
    }


def build_storm_exports(
    *,
    identities: Sequence[MastodonIdentity],
    posts: Sequence[CachedPost],
    min_text_length: int = DEFAULT_MIN_TEXT_LENGTH,
) -> dict[str, Any]:
    identity_by_author_id = {
        str(identity.account_id): identity for identity in identities
    }
    local_author_ids = set(identity_by_author_id)

    deduped_posts: dict[str, CachedPost] = {}
    for post in posts:
        if post.visibility != "public" or post.is_reblog:
            continue
        if str(post.author_id) not in local_author_ids:
            continue
        deduped_posts.setdefault(post.id, post)

    own_posts = list(deduped_posts.values())
    children_map: dict[str, list[CachedPost]] = {}
    roots: list[CachedPost] = []

    for post in own_posts:
        if post.in_reply_to_id:
            children_map.setdefault(post.in_reply_to_id, []).append(post)
        else:
            roots.append(post)

    storms: list[dict[str, Any]] = []
    storm_counts: dict[str, int] = {identity.acct: 0 for identity in identities}

    for root in sorted(
        roots, key=lambda post: (post.created_at, post.id), reverse=True
    ):
        identity = identity_by_author_id.get(str(root.author_id))
        if identity is None:
            continue

        branches = [
            build_branch(
                child,
                identity=identity,
                author_id=str(root.author_id),
                children_map=children_map,
            )
            for child in sort_posts(children_map.get(root.id, []))
            if str(child.author_id) == str(root.author_id)
        ]
        clean_text = clean_mastodon_text(root.content)
        cleaned_length = len(clean_text)
        if cleaned_length < min_text_length and not branches:
            continue

        created_at = root.created_at.date().isoformat()
        title_source = clean_text or f"{identity.acct} storm"
        title = summarize_text(title_source, limit=80)
        slug = f"{created_at}-{slugify_text(title_source[:70])}-{root.id}"

        storms.append(
            {
                "id": root.id,
                "slug": slug,
                "title": title,
                "author": {
                    "acct": identity.acct,
                    "api_base_url": identity.api_base_url,
                    "account_id": str(identity.account_id),
                },
                "created_at": root.created_at.isoformat(),
                "content_html": root.content,
                "content_text": clean_text,
                "cleaned_length": cleaned_length,
                "excerpt": summarize_text(clean_text),
                "media": parse_media_attachments(root.media_attachments),
                "original_url": post_permalink(identity, root.id),
                "reply_count": len(branches),
                "branches": branches,
            }
        )
        storm_counts[identity.acct] = storm_counts.get(identity.acct, 0) + 1

    authors = [
        AuthorSummary(
            acct=identity.acct,
            api_base_url=identity.api_base_url,
            account_id=str(identity.account_id),
            storm_count=storm_counts.get(identity.acct, 0),
        ).__dict__
        for identity in sorted(identities, key=lambda item: item.acct.lower())
    ]

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "min_text_length": min_text_length,
        "storm_count": len(storms),
        "authors": authors,
        "storms": storms,
    }


def categorize_blogroll_account(
    account: CachedAccount,
    *,
    interacted_accounts: set[tuple[int, str]],
) -> str | None:
    if not account.is_following:
        return None
    if account.bot:
        return "bots"
    if (
        account.is_followed_by
        and (account.mastodon_identity_id, account.id) in interacted_accounts
    ):
        return "top_friends"
    if account.is_followed_by:
        return "mutuals"
    return None


def build_blogroll_entry(account: CachedAccount) -> dict[str, Any]:
    display_name = account.display_name.strip() or account.acct
    return {
        "acct": account.acct,
        "display_name": display_name,
        "avatar": account.avatar,
        "mastodon_social_url": mastodon_social_permalink(account.acct),
        "note": clean_mastodon_text(account.note) if account.note else "",
        "last_status_at": (
            account.last_status_at.isoformat() if account.last_status_at else None
        ),
    }


def build_blogroll_export(
    *,
    accounts: Sequence[CachedAccount],
    notifications: Sequence[CachedNotification],
) -> dict[str, Any]:
    interacted_accounts = {
        (notification.identity_id, notification.account_id)
        for notification in notifications
        if notification.type in BLOGROLL_NOTIFICATION_TYPES
    }
    categorized_accounts: dict[str, dict[str, Any]] = {}

    for account in accounts:
        category = categorize_blogroll_account(
            account, interacted_accounts=interacted_accounts
        )
        if category is None:
            continue

        acct_key = normalize_acct_key(account.acct)
        candidate_priority = BLOGROLL_CATEGORY_PRIORITIES[category]
        candidate_sort = account.last_status_at or datetime.min
        existing = categorized_accounts.get(acct_key)

        if (
            existing is None
            or candidate_priority > existing["priority"]
            or (
                candidate_priority == existing["priority"]
                and candidate_sort > existing["sort_last_status_at"]
            )
        ):
            categorized_accounts[acct_key] = {
                "category": category,
                "priority": candidate_priority,
                "sort_last_status_at": candidate_sort,
                "entry": build_blogroll_entry(account),
            }

    accounts_by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in categorized_accounts.values():
        accounts_by_category[item["category"]].append(item)

    categories = []
    for category_id in ("top_friends", "mutuals", "bots"):
        sorted_entries = sorted(
            accounts_by_category.get(category_id, []),
            key=lambda item: (
                item["entry"]["display_name"].lower(),
                item["entry"]["acct"].lower(),
            ),
        )
        sorted_entries.sort(key=lambda item: item["sort_last_status_at"], reverse=True)
        categories.append(
            {
                "id": category_id,
                "title": BLOGROLL_CATEGORY_TITLES[category_id],
                "count": len(sorted_entries),
                "accounts": [item["entry"] for item in sorted_entries],
            }
        )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "warning": (
            "This is anonymous access so I don't know your base Mastodon instance; "
            "all links go to mastodon.social."
        ),
        "categories": categories,
    }


async def load_storm_export_data(
    *, min_text_length: int = DEFAULT_MIN_TEXT_LENGTH
) -> dict[str, Any]:
    async with async_session() as session:
        identities = (
            (
                await session.execute(
                    select(MastodonIdentity).order_by(MastodonIdentity.acct)
                )
            )
            .scalars()
            .all()
        )
        if not identities:
            return build_storm_exports(
                identities=[], posts=[], min_text_length=min_text_length
            )
        posts = (
            (
                await session.execute(
                    select(CachedPost).where(
                        CachedPost.author_id.in_(
                            [str(identity.account_id) for identity in identities]
                        )
                    )
                )
            )
            .scalars()
            .all()
        )

    return build_storm_exports(
        identities=identities, posts=posts, min_text_length=min_text_length
    )


async def load_blogroll_export_data() -> dict[str, Any]:
    async with async_session() as session:
        identities = (
            (
                await session.execute(
                    select(MastodonIdentity).order_by(MastodonIdentity.acct)
                )
            )
            .scalars()
            .all()
        )
        identity_ids = [identity.id for identity in identities]
        if not identity_ids:
            return build_blogroll_export(accounts=[], notifications=[])

        accounts = (
            (
                await session.execute(
                    select(CachedAccount).where(
                        CachedAccount.mastodon_identity_id.in_(identity_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        notifications = (
            (
                await session.execute(
                    select(CachedNotification).where(
                        CachedNotification.identity_id.in_(identity_ids)
                    )
                )
            )
            .scalars()
            .all()
        )

    return build_blogroll_export(accounts=accounts, notifications=notifications)


def write_json_export(output_path: Path, payload: dict[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{json.dumps(payload, indent=2)}\n", encoding="utf-8")


async def run_export(
    output_path: Path,
    *,
    min_text_length: int = DEFAULT_MIN_TEXT_LENGTH,
    blogroll_output_path: Path = DEFAULT_BLOGROLL_OUTPUT_PATH,
) -> None:
    storm_payload = await load_storm_export_data(min_text_length=min_text_length)
    blogroll_payload = await load_blogroll_export_data()
    write_json_export(output_path, storm_payload)
    write_json_export(blogroll_output_path, blogroll_payload)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Mastodon storms for Eleventy.")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Path to the generated storms.json file.",
    )
    parser.add_argument(
        "--min-text-length",
        type=int,
        default=DEFAULT_MIN_TEXT_LENGTH,
        help="Minimum cleaned text length for long single-post storms.",
    )
    parser.add_argument(
        "--blogroll-output",
        type=Path,
        default=DEFAULT_BLOGROLL_OUTPUT_PATH,
        help="Path to the generated blogroll.json file.",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    try:
        await run_export(
            args.output,
            min_text_length=args.min_text_length,
            blogroll_output_path=args.blogroll_output,
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
