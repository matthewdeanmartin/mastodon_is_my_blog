# mastodon_is_my_blog/perf.py
import functools
import logging
import time
from contextlib import asynccontextmanager
from typing import Callable

from fastapi import Request

logger = logging.getLogger(__name__)


class PerformanceLogger:
    """Context manager for timing code blocks"""

    def __init__(self, operation: str, logger: logging.Logger = logger):
        self.operation: str = operation
        self.logger: logging.Logger = logger
        self.start_time: float = 0.0

    def __enter__(self) -> "PerformanceLogger":
        self.start_time = time.perf_counter()
        self.logger.info(f"Starting: {self.operation}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        elapsed: float = time.perf_counter() - self.start_time
        if exc_type:
            self.logger.error(
                f"Failed: {self.operation} after {elapsed:.3f}s - {exc_val}"
            )
        else:
            self.logger.info(f"Completed: {self.operation} in {elapsed:.3f}s")


@asynccontextmanager
async def async_perf_log(operation: str, logger: logging.Logger = logger):
    """Async context manager for timing async operations"""
    start: float = time.perf_counter()
    logger.info(f"Starting: {operation}")
    try:
        yield
    finally:
        elapsed: float = time.perf_counter() - start
        logger.info(f"Completed: {operation} in {elapsed:.3f}s")


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


# Middleware to log all requests
async def performance_middleware(request: Request, call_next):
    """FastAPI middleware to log request timing"""
    start_time: float = time.perf_counter()

    # Log request start
    logger.info(f"Request started: {request.method} {request.url.path}")

    try:
        response = await call_next(request)
        elapsed: float = time.perf_counter() - start_time

        # Log successful request
        logger.info(
            f"Request completed: {request.method} {request.url.path} "
            f"Status: {response.status_code} Time: {elapsed:.3f}s"
        )

        # Add timing header
        response.headers["X-Process-Time"] = f"{elapsed:.3f}"
        return response
    except Exception as e:
        elapsed: float = time.perf_counter() - start_time
        logger.error(
            f"Request failed: {request.method} {request.url.path} "
            f"Error: {str(e)} Time: {elapsed:.3f}s"
        )
        raise
