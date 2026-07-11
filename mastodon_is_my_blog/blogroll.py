"""Blogroll categorization shared by the static export and the API routes.

Kept free of import side effects so routes can use it: storm_export pins
DB_URL at import time and must stay CLI-only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mastodon_is_my_blog.store import CachedAccount

BLOGROLL_NOTIFICATION_TYPES = frozenset({"mention", "favourite", "reblog", "status"})
BLOGROLL_CATEGORY_TITLES = {
    "top_friends": "Top Friends",
    "mutuals": "Mutuals",
    "bots": "Bots",
}
BLOGROLL_CATEGORY_PRIORITIES = {
    "mutuals": 1,
    "bots": 2,
    "top_friends": 3,
}


def categorize_blogroll_account(
    account: CachedAccount,
    *,
    interacted_accounts: set[tuple[int, str]],
) -> str | None:
    if not account.is_following:
        return None
    # Checked before the bot flag: bridgy-style bridges mark real people as
    # bots, and a mutual you interact with is a top friend either way.
    if account.is_followed_by and (account.mastodon_identity_id, account.id) in interacted_accounts:
        return "top_friends"
    if account.bot:
        return "bots"
    if account.is_followed_by:
        return "mutuals"
    return None
