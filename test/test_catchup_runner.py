import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select

from mastodon_is_my_blog import catchup_runner
from mastodon_is_my_blog.store import CachedAccount, CachedPost
from test.conftest import (
    make_cached_account,
    make_identity,
    make_meta_account,
    make_status,
)


@pytest_asyncio.fixture(autouse=True)
async def clear_catchup_registry():
    catchup_runner.CATCHUP.clear()
    yield
    running_tasks = [
        job.task
        for job in catchup_runner.CATCHUP.values()
        if job.task is not None and not job.task.done()
    ]
    for task in running_tasks:
        task.cancel()
    if running_tasks:
        await asyncio.gather(*running_tasks, return_exceptions=True)
    catchup_runner.CATCHUP.clear()


@pytest.mark.asyncio
async def test_start_job_dispatches_urgent_runner() -> None:
    meta = make_meta_account(meta_id=10)
    identity = make_identity(identity_id=20, meta_account_id=10)
    queue = [make_cached_account(meta_account_id=10, identity_id=20)]

    runner_mock = AsyncMock()
    with (
        patch("mastodon_is_my_blog.catchup.get_catchup_queue", AsyncMock(return_value=queue)),
        patch.object(catchup_runner, "run_urgent", runner_mock),
    ):
        job = await catchup_runner.start_job(meta, identity, "urgent", max_accounts=3)
        await job.task

    assert job.total == 1
    assert catchup_runner.get_job(meta.id, identity.id) is job
    runner_mock.assert_awaited_once_with(job, queue, identity)


@pytest.mark.asyncio
async def test_start_job_rejects_duplicate_running_job() -> None:
    meta = make_meta_account(meta_id=10)
    identity = make_identity(identity_id=20, meta_account_id=10)
    existing = catchup_runner.CatchupJob(meta_id=10, identity_id=20, mode="urgent", total=1)
    existing.task = asyncio.create_task(asyncio.sleep(60))
    catchup_runner.CATCHUP[(10, 20)] = existing

    with pytest.raises(ValueError, match="Job already running"):
        await catchup_runner.start_job(meta, identity, "urgent")


@pytest.mark.asyncio
async def test_run_modes_delegate_expected_parameters() -> None:
    job = catchup_runner.CatchupJob(meta_id=1, identity_id=2, mode="urgent", total=0)
    queue = [make_cached_account()]
    identity = make_identity()

    run_loop_mock = AsyncMock()
    with patch.object(catchup_runner, "_run_loop", run_loop_mock):
        await catchup_runner.run_urgent(job, queue, identity)
        await catchup_runner.run_trickle(job, queue, identity)

    assert run_loop_mock.await_args_list[0].kwargs == {
        "max_pages": 20,
        "inter_account_delay": 0.2,
    }
    assert run_loop_mock.await_args_list[1].kwargs == {
        "max_pages": None,
        "inter_account_delay": 5.0,
    }


@pytest.mark.asyncio
async def test_run_loop_persists_accounts_and_posts(
    db_session_factory,
    patch_async_session,
) -> None:
    patch_async_session(catchup_runner)
    identity = make_identity(acct="me@example.social")
    queue = [
        make_cached_account(
            account_id="friend-1",
            acct="friend@example.social",
            meta_account_id=1,
            identity_id=identity.id,
        )
    ]
    job = catchup_runner.CatchupJob(meta_id=1, identity_id=identity.id, mode="urgent", total=1)

    async def fake_deep_fetch(*args, **kwargs):
        yield [
            make_status(
                "post-100",
                account_id="friend-1",
                acct="friend@example.social",
            )
        ]

    with (
        patch.object(catchup_runner, "client_from_identity", return_value=MagicMock()),
        patch.object(catchup_runner.asyncio, "to_thread", AsyncMock(return_value="target-1")),
        patch.object(catchup_runner, "get_stop_at_id", AsyncMock(return_value=None)),
        patch.object(catchup_runner, "deep_fetch_user_timeline", fake_deep_fetch),
        patch.object(catchup_runner.asyncio, "sleep", AsyncMock()),
    ):
        await catchup_runner._run_loop(
            job,
            queue,
            identity,
            max_pages=20,
            inter_account_delay=0.2,
        )

    async with db_session_factory() as session:
        stored_account = (await session.execute(select(CachedAccount))).scalar_one()
        stored_post = (await session.execute(select(CachedPost))).scalar_one()

    assert stored_account.id == "friend-1"
    assert stored_post.id == "post-100"
    assert job.done == 1
    assert job.errors == 0
    assert job.current_acct is None
    assert job.finished_at is not None


@pytest.mark.asyncio
async def test_run_loop_marks_rate_limited_errors() -> None:
    identity = make_identity(acct="me@example.social")
    queue = [make_cached_account(account_id="friend-1", acct="friend@example.social")]
    job = catchup_runner.CatchupJob(meta_id=1, identity_id=identity.id, mode="urgent", total=1)

    class RetryAfterError(RuntimeError):
        pass

    error = RetryAfterError("slow down")
    error.retry_after = 3

    async def failing_deep_fetch(*args, **kwargs):
        raise error
        yield

    sleep_mock = AsyncMock()
    with (
        patch.object(catchup_runner, "client_from_identity", return_value=MagicMock()),
        patch.object(catchup_runner.asyncio, "to_thread", AsyncMock(return_value="target-1")),
        patch.object(catchup_runner, "get_stop_at_id", AsyncMock(return_value=None)),
        patch.object(catchup_runner, "deep_fetch_user_timeline", failing_deep_fetch),
        patch.object(catchup_runner.asyncio, "sleep", sleep_mock),
    ):
        await catchup_runner._run_loop(
            job,
            queue,
            identity,
            max_pages=20,
            inter_account_delay=0.2,
        )

    assert job.errors == 1
    assert job.done == 1
    assert job.rate_limited is True
    sleep_mock.assert_awaited_once_with(0.4)


def test_resolve_account_id_handles_success_empty_and_error() -> None:
    client = MagicMock()
    client.account_search.return_value = [{"id": 123}]
    assert catchup_runner._resolve_account_id(client, "friend@example.social") == "123"

    client.account_search.return_value = []
    assert catchup_runner._resolve_account_id(client, "friend@example.social") is None

    client.account_search.side_effect = RuntimeError("boom")
    assert catchup_runner._resolve_account_id(client, "friend@example.social") is None


@pytest.mark.asyncio
async def test_cancel_job_and_job_status_reflect_task_state() -> None:
    job = catchup_runner.CatchupJob(meta_id=1, identity_id=2, mode="trickle", total=5)
    job.task = asyncio.create_task(asyncio.sleep(60))
    catchup_runner.CATCHUP[(1, 2)] = job

    assert catchup_runner.cancel_job(1, 2) is True
    status = catchup_runner.job_status(job)

    assert job.cancel_event.is_set()
    assert status["running"] is True
    assert status["mode"] == "trickle"
    assert catchup_runner.cancel_job(99, 99) is False
