"""
Datetime helpers for the app.

# WARNING TO FUTURE DEVS — TIMEZONES ARE A LANDMINE HERE

This app stores **naive UTC** datetimes in the SQLite database. SQLAlchemy's
``DateTime`` column type round-trips them as naive (no ``tzinfo``). Comparing
or subtracting an aware datetime against a naive one raises::

    TypeError: can't subtract offset-naive and offset-aware datetimes

This has bitten the Profile and Peeps pages multiple times. Symptoms:
endpoints 500 with that exact message, usually on a ``now - some_date``
expression where ``now`` was built with ``datetime.now(UTC)`` (aware) and
``some_date`` came out of the DB (naive).

## Rules

- Use :func:`utc_now` for "now" everywhere in app code. It returns naive UTC.
- Never use ``datetime.now(timezone.utc)`` / ``datetime.now(UTC)`` for
  arithmetic that involves DB-sourced datetimes.
- ``datetime.utcnow()`` is deprecated in 3.12+. Prefer :func:`utc_now`.
- If a value enters from the Mastodon API, it is **aware** (``tzinfo=UTC``).
  Strip ``tzinfo`` with :func:`to_naive_utc` before comparing it against
  another value, before storing it, or before doing arithmetic with another
  app-sourced value.
- Don't sprinkle ``replace(tzinfo=None) if x.tzinfo else x`` everywhere —
  use :func:`to_naive_utc`. It is a no-op for already-naive values.
"""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return a naive UTC timestamp suitable for DB writes and comparisons."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_naive_utc(dt: datetime | None) -> datetime | None:
    """
    Coerce a datetime to naive UTC.

    - If ``dt`` is None, returns None.
    - If ``dt`` is naive, returns it unchanged (assumed already UTC — that is
      this app's invariant).
    - If ``dt`` is aware, converts to UTC and strips ``tzinfo``.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)
