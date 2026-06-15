"""Integration fixtures: run the blog's Mastodon client against a real HTTP mock.

These tests do **not** touch a live Mastodon and need no API keys. Instead they
boot the ``mastodon_mock`` package (published on PyPI) as a uvicorn server on a
free port and point the blog's own client factory at it. ``mastodon_mock`` is a
*stateful* simulation — a status you POST shows up in the next GET of that
account's timeline — so the blog's fetch/post/read-back code paths can be
exercised end to end over HTTP, exactly as they would be against a real instance.

The free-port allocation, readiness polling and teardown that this file used to
hand-roll now live in ``mastodon_mock.testing.MockServer`` (shipped in the
``mastodon_mock[test]`` extra); we just hand it our seed and read ``base_url``.

The whole package self-skips when it cannot run:

* on Python < 3.13 (the mock's ``requires-python``), or
* if ``mastodon_mock`` is not installed (install ``mastodon_mock[test]``).

Run just this suite::

    uv run pytest test_integration
"""

from __future__ import annotations

import sys
from collections.abc import Iterator

import pytest

# --- Hard preconditions: skip the entire package rather than error on collect ---

if sys.version_info < (3, 13):
    pytest.skip(
        "mastodon_mock requires Python >= 3.13; skipping mock integration suite",
        allow_module_level=True,
    )

pytest.importorskip(
    "mastodon_mock",
    reason="install mastodon_mock[test] to run these tests",
)

from mastodon import Mastodon  # noqa: E402

from mastodon_mock.config import (  # noqa: E402
    SeedAccount,
    SeedConfig,
    SeedFollow,
    SeedStatus,
)
from mastodon_mock.testing import MockServer  # noqa: E402

from mastodon_is_my_blog.mastodon_apis.masto_client import client as build_blog_client  # noqa: E402
from mastodon_is_my_blog.mastodon_apis.masto_client_timed import (  # noqa: E402
    TimedMastodonClient,
)

# Stable handles the tests assert against.
ALICE_TOKEN = "alice_token"
BOB_TOKEN = "bob_token"

# A seed rich enough for read paths: alice follows bob, bob has a couple of
# statuses so alice's home timeline is non-empty and account_statuses returns rows.
INTEGRATION_SEED = SeedConfig(
    accounts=[
        SeedAccount(username="alice", display_name="Alice", access_token=ALICE_TOKEN),
        SeedAccount(username="bob", display_name="Bob", access_token=BOB_TOKEN),
    ],
    follows=[SeedFollow(follower="alice", following="bob")],
    statuses=[
        SeedStatus(account="bob", text="hello from the seed"),
        SeedStatus(account="bob", text="a second seed post"),
    ],
)


@pytest.fixture(scope="session")
def mock_server_url() -> Iterator[str]:
    """Session-scoped mock server backed by the integration seed.

    Each test session gets one in-memory mock instance. State accumulates across
    tests within the session, which is exactly the point: it lets us prove the
    server is stateful (post here, read it back there). ``MockServer`` owns the
    free port, readiness wait, and teardown.
    """
    with MockServer(seed=INTEGRATION_SEED) as server:
        yield server.base_url


@pytest.fixture
def raw_client(mock_server_url: str) -> Mastodon:
    """A bare Mastodon.py client (alice) pointed at the mock.

    Useful for assertions about raw API behaviour without the blog's timing
    wrapper in the way.
    """
    return Mastodon(access_token=ALICE_TOKEN, api_base_url=mock_server_url)


@pytest.fixture
def blog_client(mock_server_url: str) -> TimedMastodonClient:
    """The *blog's own* client factory, pointed at the mock.

    This exercises ``mastodon_apis.masto_client.client`` — credential validation,
    URL normalisation, and the ``TimedMastodonClient`` wrapper the app uses in
    production — against the mock instead of a live server. The mock ignores the
    client_id/secret (it authenticates on the bearer token), but the factory
    still requires them to be non-empty, so we pass placeholders.
    """
    built = build_blog_client(
        base_url=mock_server_url,
        client_id="integration-client-id",
        client_secret="integration-client-secret",
        access_token=ALICE_TOKEN,
    )
    assert isinstance(built, TimedMastodonClient)
    return built
