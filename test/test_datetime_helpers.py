"""
Tests for datetime_helpers — the timezone landmine in this app.

The DB stores naive UTC. Mastodon's API returns aware UTC. Mixing the two in
arithmetic raises ``TypeError: can't subtract offset-naive and offset-aware
datetimes``. These tests exist so future devs trip the wire here, not in
production on the profile or peeps page.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from mastodon_is_my_blog.datetime_helpers import to_naive_utc, utc_now


def test_utc_now_is_naive() -> None:
    """utc_now() must be naive — DB columns are naive."""
    now = utc_now()
    assert now.tzinfo is None


def test_utc_now_subtracts_with_db_naive_value_without_typeerror() -> None:
    """The exact thing that blew up the profile page must keep working."""
    db_value = datetime(2024, 3, 1)  # naive, like rows out of SQLite DateTime
    delta = utc_now() - db_value
    assert delta.total_seconds() > 0


def test_utc_now_minus_aware_value_raises_so_we_catch_drift_locally() -> None:
    """
    Sanity: prove the landmine is still there. If someone "fixes" utc_now()
    to return an aware value, this test should fail and force them to
    update everything that subtracts a naive DB value from it.
    """
    aware = datetime.now(timezone.utc)
    with pytest.raises(TypeError):
        _ = utc_now() - aware  # type: ignore[operator]


def test_to_naive_utc_strips_tz_from_aware() -> None:
    aware = datetime(2024, 3, 1, 12, 0, tzinfo=timezone.utc)
    naive = to_naive_utc(aware)
    assert naive == datetime(2024, 3, 1, 12, 0)
    assert naive is not None and naive.tzinfo is None


def test_to_naive_utc_converts_offset_to_utc_then_strips() -> None:
    """An aware non-UTC value must be converted to UTC before stripping."""
    plus_five = timezone(timedelta(hours=5))
    aware = datetime(2024, 3, 1, 17, 0, tzinfo=plus_five)
    naive = to_naive_utc(aware)
    # 17:00 +05:00 == 12:00 UTC
    assert naive == datetime(2024, 3, 1, 12, 0)
    assert naive is not None and naive.tzinfo is None


def test_to_naive_utc_passes_through_naive() -> None:
    naive = datetime(2024, 3, 1)
    out = to_naive_utc(naive)
    assert out is naive  # same object — no-op for already-naive


def test_to_naive_utc_handles_none() -> None:
    assert to_naive_utc(None) is None


def test_to_naive_utc_makes_subtraction_safe() -> None:
    """The whole point: after to_naive_utc, you can subtract from utc_now()."""
    aware_from_api = datetime(2024, 3, 1, tzinfo=timezone.utc)
    naive_from_db = datetime(2024, 3, 1)
    now = utc_now()

    # Both should work without TypeError
    delta_a = now - to_naive_utc(aware_from_api)  # type: ignore[operator]
    delta_b = now - to_naive_utc(naive_from_db)  # type: ignore[operator]
    assert delta_a.total_seconds() > 0
    assert delta_b.total_seconds() > 0
