"""
Catch-up helpers: priority queue and deep paginated fetch.

4.2  get_catchup_queue  — returns CachedAccount rows in priority order.
4.3  deep_fetch_user_timeline — walks max_id pages until stop_at_id,
     max_pages, or the instance stops responding.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable, Coroutine
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from mastodon import Mastodon
from sqlalchemy import and_, case, func, select

from mastodon_is_my_blog.mastodon_apis.masto_client import client_from_identity
from mastodon_is_my_blog.store import (
    CachedAccount,
    CachedNotification,
    CachedPost,
    MastodonIdentity,
    async_session,
)
from mastodon_is_my_blog.datetime_helpers import utc_now

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate-limit budget (shared across all pages in one deep fetch run)
# ---------------------------------------------------------------------------

@dataclass
class RateBudget:
    """
    Simple token bucket.  Callers request a slot before each API call.
    If the bucket is empty the coroutine sleeps until a token is available.

    Default: 300 requests per 5 minutes = 1 req / second steady state.
    """

    capacity: int = 300
    refill_seconds: float = 300.0
    tokens: float = field(default=0.0, init=False)
    last_refill: datetime = field(default_factory=utc_now, init=False)

    def __post_init__(self) -> None:
        self.tokens = float(self.capacity)

    def _refill(self) -> None:
        now = utc_now()
        elapsed = (now - self.last_refill).total_seconds()
        added = elapsed * (self.capacity / self.refill_seconds)
        self.tokens = min(self.capacity, self.tokens + added)
        self.last_refill = now

    async def acquire(self) -> None:
        """Wait until a token is available, then consume one."""
        while True:
            self._refill()
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return
            # Sleep until the next token arrives
            await asyncio.sleep(self.refill_seconds / self.capacity)


# ---------------------------------------------------------------------------
# 4.2  Catchup queue
# ---------------------------------------------------------------------------

async def get_catchup_queue(
    meta_id: int,
    identity_id: int,
    max_accounts: int | None = None,
) -> list[CachedAccount]:
    """
    Return CachedAccount rows in catch-up priority order:

    1. Mutuals (is_following AND is_followed_by)
    2. Top-friends — highest CachedNotification count in the last 30 days
    3. is_following, sorted by last_status_at DESC (recently active)
    4. is_following, last_status_at NULL or > 30 days old

    Only accounts with is_following=True are included (no stranger boosts).
    """
    cutoff = utc_now() - timedelta(days=30)

    async with async_session() as session:
        # Subquery: notification count per account_id in the last 30 days
        notif_count_sq = (
            select(
                CachedNotification.account_id,
                func.count(CachedNotification.id).label("notif_count"),
            )
            .where(
                and_(
                    CachedNotification.meta_account_id == meta_id,
                    CachedNotification.identity_id == identity_id,
                    CachedNotification.created_at >= cutoff,
                )
            )
            .group_by(CachedNotification.account_id)
            .subquery()
        )

        # Priority column:
        #   1 = mutual  (is_following AND is_followed_by)
        #   2 = top-friend (mutual with notifications)  — elevated over plain mutuals
        #   3 = following, recently active
        #   4 = following, inactive / never active
        #
        # We want lower numbers first so ORDER BY priority ASC puts best first.
        priority_col = case(
            (
                and_(
                    CachedAccount.is_following.is_(True),
                    CachedAccount.is_followed_by.is_(True),
                    notif_count_sq.c.notif_count > 0,
                ),
                1,
            ),
            (
                and_(
                    CachedAccount.is_following.is_(True),
                    CachedAccount.is_followed_by.is_(True),
                ),
                2,
            ),
            (
                and_(
                    CachedAccount.is_following.is_(True),
                    CachedAccount.last_status_at.isnot(None),
                    CachedAccount.last_status_at >= cutoff,
                ),
                3,
            ),
            else_=4,
        ).label("priority")

        notif_count_col = func.coalesce(notif_count_sq.c.notif_count, 0).label("notif_count")

        stmt = (
            select(CachedAccount, priority_col, notif_count_col)
            .outerjoin(
                notif_count_sq,
                notif_count_sq.c.account_id == CachedAccount.id,
            )
            .where(
                and_(
                    CachedAccount.meta_account_id == meta_id,
                    CachedAccount.mastodon_identity_id == identity_id,
                    CachedAccount.is_following.is_(True),
                )
            )
            .order_by(
                priority_col,
                # Within the same priority tier: most recently active first,
                # then by notif count descending as a secondary tiebreaker.
                notif_count_col.desc(),
                CachedAccount.last_status_at.desc().nulls_last(),
            )
        )

        if max_accounts is not None:
            stmt = stmt.limit(max_accounts)

        rows = (await session.execute(stmt)).all()
        # Extract just the CachedAccount objects (first element of each row tuple)
        return [row[0] for row in rows]


# ---------------------------------------------------------------------------
# 4.3  Deep paginated fetch helper
# ---------------------------------------------------------------------------

PageCallback = Callable[[list[dict]], Coroutine[None, None, None]]


async def deep_fetch_user_timeline(
    m: Mastodon,
    target_id: str,
    *,
    stop_at_id: str | None = None,
    max_pages: int | None = None,
    on_page: PageCallback | None = None,
    inter_page_delay: float = 0.5,
    rate_budget: RateBudget | None = None,
) -> AsyncIterator[list[dict]]:
    """
    Walk account_statuses pages using max_id until one of:
      - the API returns an empty page
      - every status in a page has id <= stop_at_id
      - max_pages is reached
      - the response carries no next max_id

    Yields each page of raw Mastodon status dicts.  If on_page is provided
    it is awaited for each page (useful for progressive bulk-upsert).

    inter_page_delay: seconds to sleep between pages (rate-limit courtesy).
    rate_budget: shared RateBudget; acquire() is called before each page.

    On HTTP 429, reads Retry-After and sleeps before retrying once.
    """
    page_num = 0
    max_id: str | None = None

    while True:
        if max_pages is not None and page_num >= max_pages:
            logger.debug(
                "deep_fetch target=%s: reached max_pages=%d, stopping",
                target_id,
                max_pages,
            )
            break

        if rate_budget is not None:
            await rate_budget.acquire()

        # Fetch one page (up to 40 statuses — friendliest cap across instances)
        try:
            kwargs: dict = {"limit": 40}
            if max_id is not None:
                kwargs["max_id"] = max_id

            page: list[dict] = await asyncio.to_thread(
                m.account_statuses, target_id, **kwargs
            )
        except Exception as exc:
            # Mastodon.py raises MastodonRatelimitError on 429
            retry_after = getattr(exc, "retry_after", None)
            if retry_after is not None:
                wait = float(retry_after)
                logger.warning(
                    "deep_fetch target=%s: 429, sleeping %.0fs", target_id, wait
                )
                await asyncio.sleep(wait)
                # Retry the same page once — don't advance max_id
                try:
                    page = await asyncio.to_thread(
                        m.account_statuses, target_id, **kwargs
                    )
                except Exception as retry_exc:
                    logger.error(
                        "deep_fetch target=%s: retry after 429 also failed: %s",
                        target_id,
                        retry_exc,
                    )
                    break
            else:
                logger.error(
                    "deep_fetch target=%s: unexpected error: %s", target_id, exc
                )
                break

        if not page:
            logger.debug("deep_fetch target=%s: empty page, done", target_id)
            break

        # Stop if all statuses on this page are already cached
        if stop_at_id is not None:
            # Mastodon IDs are snowflake-ish: lexicographic comparison is valid
            # because they are always numeric strings of equal length at a given
            # instance, and newer posts have higher IDs.
            if all(str(s["id"]) <= stop_at_id for s in page):
                logger.debug(
                    "deep_fetch target=%s: all ids <= stop_at_id %s, done",
                    target_id,
                    stop_at_id,
                )
                break

        page_num += 1

        yield page

        if on_page is not None:
            await on_page(page)

        # Advance the cursor to the oldest id on this page
        max_id = str(min(s["id"] for s in page))

        # Mastodon.py returns a list of dicts; there's no built-in "next" cursor
        # we can inspect here, but if page is shorter than the requested limit
        # the instance has no more history to give us.
        if len(page) < 40:
            logger.debug(
                "deep_fetch target=%s: short page (%d), done", target_id, len(page)
            )
            break

        if inter_page_delay > 0:
            await asyncio.sleep(inter_page_delay)


async def get_stop_at_id(
    meta_id: int,
    identity_id: int,
    author_acct: str,
) -> str | None:
    """
    Return the most recent cached post id we already have for this author
    under the given (meta, identity) scope.  Used as the stop_at_id for
    deep_fetch_user_timeline so we don't re-fetch already-stored pages.
    """
    async with async_session() as session:
        stmt = select(func.max(CachedPost.id)).where(
            and_(
                CachedPost.meta_account_id == meta_id,
                CachedPost.fetched_by_identity_id == identity_id,
                CachedPost.author_acct == author_acct,
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
