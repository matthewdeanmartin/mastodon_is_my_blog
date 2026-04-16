from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return a naive UTC timestamp for database values and comparisons."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
