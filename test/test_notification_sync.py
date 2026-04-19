from datetime import datetime, timezone
from test.conftest import (
    make_cached_account,
    make_cached_notification,
    make_identity,
    make_notification_payload,
)
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import func, select

from mastodon_is_my_blog import notification_sync
from mastodon_is_my_blog.store import CachedNotification


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (
            datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
            datetime(2024, 1, 1, 12, 0),
        ),
        (datetime(2024, 1, 1, 12, 0), datetime(2024, 1, 1, 12, 0)),
    ],
)
def test_to_naive_utc_normalizes_datetimes(value, expected) -> None:
    assert notification_sync.to_naive_utc(value) == expected


@pytest.mark.asyncio
async def test_sync_notifications_persists_rows_and_syncs_top_mutuals(
    db_session,
    db_session_factory,
    patch_async_session,
) -> None:
    patch_async_session(notification_sync)
    identity = make_identity(acct="me@example.social")
    recent_time = datetime.now(timezone.utc)
    db_session.add_all(
        [
            make_cached_account(
                account_id="mutual-1",
                acct="mutual1@example.social",
                identity_id=identity.id,
                is_following=True,
                is_followed_by=True,
            ),
            make_cached_account(
                account_id="mutual-2",
                acct="mutual2@example.social",
                identity_id=identity.id,
                is_following=True,
                is_followed_by=True,
            ),
            make_cached_account(
                account_id="non-mutual",
                acct="nonmutual@example.social",
                identity_id=identity.id,
                is_following=True,
                is_followed_by=False,
            ),
        ]
    )
    await db_session.commit()

    client = MagicMock()
    client.notifications.return_value = [
        make_notification_payload(
            "notif-1",
            notification_type="mention",
            account_id="mutual-1",
            account_acct="mutual1@example.social",
            status_id="status-1",
            created_at=recent_time,
        ),
        make_notification_payload(
            "notif-2",
            notification_type="favourite",
            account_id="mutual-2",
            account_acct="mutual2@example.social",
            status_id="status-2",
            created_at=recent_time,
        ),
        make_notification_payload(
            "notif-3",
            notification_type="follow",
            account_id="non-mutual",
            account_acct="nonmutual@example.social",
            status_id=None,
            created_at=recent_time,
        ),
    ]
    timeline_sync_mock = AsyncMock(return_value={"status": "success"})

    with (
        patch.object(notification_sync, "client_from_identity", return_value=client),
        patch.object(
            notification_sync,
            "sync_user_timeline_for_identity",
            timeline_sync_mock,
        ),
    ):
        stats = await notification_sync.sync_notifications_for_identity(1, identity)

    assert stats == {
        "total": 3,
        "mentions": 1,
        "replies": 0,
        "favorites": 1,
        "reblogs": 0,
        "follows": 1,
        "accounts_synced": 3,
        "timelines_synced": 2,
    }
    synced_accounts = sorted(
        await_call.kwargs["acct"] for await_call in timeline_sync_mock.await_args_list
    )
    assert synced_accounts == [
        "mutual1@example.social",
        "mutual2@example.social",
    ]

    async with db_session_factory() as session:
        notif_count = (
            await session.execute(select(func.count()).select_from(CachedNotification))
        ).scalar_one()

    assert notif_count == 3


@pytest.mark.asyncio
async def test_sync_notifications_continues_when_timeline_sync_fails(
    db_session,
    patch_async_session,
) -> None:
    patch_async_session(notification_sync)
    identity = make_identity(acct="me@example.social")
    recent_time = datetime.now(timezone.utc)
    db_session.add_all(
        [
            make_cached_account(
                account_id="mutual-1",
                acct="mutual1@example.social",
                identity_id=identity.id,
                is_following=True,
                is_followed_by=True,
            ),
            make_cached_account(
                account_id="mutual-2",
                acct="mutual2@example.social",
                identity_id=identity.id,
                is_following=True,
                is_followed_by=True,
            ),
            make_cached_notification(
                "notif-existing",
                identity_id=identity.id,
                account_id="mutual-1",
                account_acct="mutual1@example.social",
                created_at=recent_time.replace(tzinfo=None),
            ),
        ]
    )
    await db_session.commit()

    client = MagicMock()
    client.notifications.return_value = [
        make_notification_payload(
            "notif-existing",
            notification_type="mention",
            account_id="mutual-1",
            account_acct="mutual1@example.social",
            status_id="status-1",
            created_at=recent_time,
        ),
        make_notification_payload(
            "notif-new-1",
            notification_type="status",
            account_id="mutual-1",
            account_acct="mutual1@example.social",
            status_id="status-2",
            created_at=recent_time,
        ),
        make_notification_payload(
            "notif-new-2",
            notification_type="reblog",
            account_id="mutual-2",
            account_acct="mutual2@example.social",
            status_id="status-3",
            created_at=recent_time,
        ),
    ]

    async def fake_timeline_sync(*, acct: str, **kwargs):
        if acct == "mutual1@example.social":
            raise RuntimeError("network")
        return {"status": "success"}

    timeline_sync_mock = AsyncMock(side_effect=fake_timeline_sync)
    with (
        patch.object(notification_sync, "client_from_identity", return_value=client),
        patch.object(
            notification_sync,
            "sync_user_timeline_for_identity",
            timeline_sync_mock,
        ),
    ):
        stats = await notification_sync.sync_notifications_for_identity(1, identity)

    assert stats["total"] == 3
    assert stats["replies"] == 1
    assert stats["reblogs"] == 1
    assert stats["timelines_synced"] == 1


@pytest.mark.asyncio
async def test_sync_notifications_reraises_fetch_failures() -> None:
    identity = make_identity(acct="me@example.social")
    client = MagicMock()
    client.notifications.side_effect = RuntimeError("boom")

    with patch.object(notification_sync, "client_from_identity", return_value=client):
        with pytest.raises(RuntimeError, match="boom"):
            await notification_sync.sync_notifications_for_identity(1, identity)
