"""
Tracker for long-running bulk-sync asyncio tasks (friends backfill, notifications backfill).

Separate from catchup_runner — that queue targets per-author timeline pagination.
These jobs are one-shot "download everything" operations keyed by (meta_id, identity_id, kind).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class BulkJob:
    kind: str
    meta_id: int
    identity_id: int
    started_at: float = field(default_factory=time.time)
    done: int = 0
    total: int | None = None
    stage: str = "starting"
    finished: bool = False
    ok: bool = False
    error: str | None = None
    result: dict[str, Any] | None = None
    task: asyncio.Task | None = None
    cancel_requested: bool = False


_JOBS: dict[tuple[str, int, int], BulkJob] = {}


def job_key(kind: str, meta_id: int, identity_id: int) -> tuple[str, int, int]:
    return (kind, meta_id, identity_id)


def get_job(kind: str, meta_id: int, identity_id: int) -> BulkJob | None:
    return _JOBS.get(job_key(kind, meta_id, identity_id))


def job_status(job: BulkJob) -> dict[str, Any]:
    return {
        "kind": job.kind,
        "identity_id": job.identity_id,
        "started_at": job.started_at,
        "done": job.done,
        "total": job.total,
        "stage": job.stage,
        "finished": job.finished,
        "ok": job.ok,
        "error": job.error,
        "result": job.result,
        "cancel_requested": job.cancel_requested,
    }


async def start_bulk_job(
    kind: str,
    meta_id: int,
    identity_id: int,
    runner: Callable[[Callable[[int, int | None, str], None], Callable[[], bool]], Any],
) -> BulkJob:
    """
    Start a bulk-sync task. runner is an async callable that receives
    (on_progress, cancelled) and performs the work, returning a result dict.

    Raises ValueError if a job of this kind is already running for the identity.
    """
    key = job_key(kind, meta_id, identity_id)
    existing = _JOBS.get(key)
    if existing is not None and not existing.finished:
        raise ValueError(f"{kind} job already running for identity {identity_id}")

    job = BulkJob(kind=kind, meta_id=meta_id, identity_id=identity_id)
    _JOBS[key] = job

    def on_progress(done: int, total: int | None, stage: str) -> None:
        job.done = done
        job.total = total
        job.stage = stage

    def cancelled() -> bool:
        return job.cancel_requested

    async def wrapped():
        try:
            result = await runner(on_progress, cancelled)
            job.result = result
            job.ok = True
        except Exception as exc:
            job.error = str(exc)
            job.ok = False
        finally:
            job.finished = True
            job.stage = "done" if job.ok else "error"

    job.task = asyncio.create_task(wrapped())
    return job


def cancel_job(kind: str, meta_id: int, identity_id: int) -> bool:
    job = _JOBS.get(job_key(kind, meta_id, identity_id))
    if job is None or job.finished:
        return False
    job.cancel_requested = True
    return True
