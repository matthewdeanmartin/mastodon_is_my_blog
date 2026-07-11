# mastodon_is_my_blog/perf.py
import collections
import functools
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Callable

from fastapi import Request

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ring buffer for sync-stage timings
# ---------------------------------------------------------------------------

RING_BUFFER_SIZE = 200


@dataclass
class StageTiming:
    stage: str
    elapsed_s: float
    rows_fetched: int = 0
    rows_written: int = 0
    rows_skipped: int = 0
    cache_hits: int = 0
    extra: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    ok: bool = True
    error: str | None = None


@dataclass
class FeedQueryTiming:
    query: str
    elapsed_s: float
    row_count: int = 0
    ts: float = field(default_factory=time.time)


@dataclass
class PreviewCardTiming:
    url: str
    elapsed_s: float
    cache_status: str = "miss"  # hit | miss | stale | error
    ts: float = field(default_factory=time.time)


# Module-level ring buffers — in-process, not persisted across restarts.
stage_timings: collections.deque[StageTiming] = collections.deque(maxlen=RING_BUFFER_SIZE)
feed_timings: collections.deque[FeedQueryTiming] = collections.deque(maxlen=RING_BUFFER_SIZE)
card_timings: collections.deque[PreviewCardTiming] = collections.deque(maxlen=RING_BUFFER_SIZE)

# ---------------------------------------------------------------------------
# Preview cache counters (scaffold — real cache in Phase 1)
# ---------------------------------------------------------------------------


@dataclass
class PreviewCacheCounters:
    hits: int = 0
    misses: int = 0
    stale: int = 0
    errors: int = 0

    def as_dict(self) -> dict:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "stale": self.stale,
            "errors": self.errors,
            "total": self.hits + self.misses + self.stale + self.errors,
            "hit_rate": (round(self.hits / (self.hits + self.misses + self.stale), 3) if (self.hits + self.misses + self.stale) > 0 else 0.0),
        }


preview_cache_counters = PreviewCacheCounters()


def record_preview_hit() -> None:
    preview_cache_counters.hits += 1
    card_timings.append(PreviewCardTiming(url="<cached>", elapsed_s=0.0, cache_status="hit"))


def record_preview_miss() -> None:
    preview_cache_counters.misses += 1


def record_preview_stale() -> None:
    preview_cache_counters.stale += 1


def record_preview_error() -> None:
    preview_cache_counters.errors += 1


def record_card_timing(url: str, elapsed_s: float, cache_status: str = "miss") -> None:
    card_timings.append(PreviewCardTiming(url=url, elapsed_s=elapsed_s, cache_status=cache_status))


# ---------------------------------------------------------------------------
# Existing helpers (unchanged API)
# ---------------------------------------------------------------------------


class PerformanceLogger:
    """Context manager for timing code blocks"""

    def __init__(self, operation: str, perf_logger: logging.Logger = logger):
        self.operation: str = operation
        self.logger: logging.Logger = perf_logger
        self.start_time: float = 0.0

    def __enter__(self) -> "PerformanceLogger":
        self.start_time = time.perf_counter()
        self.logger.info(f"Starting: {self.operation}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        elapsed: float = time.perf_counter() - self.start_time
        if exc_type:
            self.logger.error(f"Failed: {self.operation} after {elapsed:.3f}s - {exc_val}")
        else:
            self.logger.info(f"Completed: {self.operation} in {elapsed:.3f}s")


@asynccontextmanager
async def async_perf_log(operation: str, perf_logger: logging.Logger = logger):
    """Async context manager for timing async operations"""
    start: float = time.perf_counter()
    perf_logger.info(f"Starting: {operation}")
    try:
        yield
    finally:
        elapsed: float = time.perf_counter() - start
        perf_logger.info(f"Completed: {operation} in {elapsed:.3f}s")


def time_function(func: Callable) -> Callable:
    """Decorator to time sync functions"""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with PerformanceLogger(f"Function: {func.__name__}"):
            return func(*args, **kwargs)

    return wrapper


def time_async_function(func: Callable) -> Callable:
    """Decorator to time async functions"""

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        async with async_perf_log(f"Function: {func.__name__}"):
            return await func(*args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# Richer sync-stage timing context manager
# ---------------------------------------------------------------------------


@asynccontextmanager
async def sync_stage(stage_name: str):
    """
    Async context manager that records a StageTiming into the ring buffer.

    Usage::

        async with sync_stage("sync_friends") as t:
            # ... do work ...
            t.rows_fetched = len(friends)
            t.rows_written = written
    """
    timing = StageTiming(stage=stage_name, elapsed_s=0.0)
    start = time.perf_counter()
    try:
        yield timing
    except Exception as exc:
        timing.ok = False
        timing.error = str(exc)
        raise
    finally:
        timing.elapsed_s = time.perf_counter() - start
        stage_timings.append(timing)
        logger.info(
            "sync_stage %s: %.3fs fetched=%d written=%d skipped=%d ok=%s",
            stage_name,
            timing.elapsed_s,
            timing.rows_fetched,
            timing.rows_written,
            timing.rows_skipped,
            timing.ok,
        )


# ---------------------------------------------------------------------------
# Middleware to log all requests
# ---------------------------------------------------------------------------


async def performance_middleware(request: Request, call_next):
    """FastAPI middleware to log request timing"""
    start_time: float = time.perf_counter()

    logger.info(f"Request started: {request.method} {request.url.path}")

    try:
        response = await call_next(request)
        elapsed: float = time.perf_counter() - start_time

        logger.info(f"Request completed: {request.method} {request.url.path} Status: {response.status_code} Time: {elapsed:.3f}s")

        if request.url.path.startswith("/api/posts"):
            feed_timings.append(
                FeedQueryTiming(
                    query=f"{request.method} {request.url.path}",
                    elapsed_s=elapsed,
                )
            )

        response.headers["X-Process-Time"] = f"{elapsed:.3f}"
        return response
    except Exception as e:
        elapsed = time.perf_counter() - start_time
        logger.error(f"Request failed: {request.method} {request.url.path} Error: {str(e)} Time: {elapsed:.3f}s")
        raise
