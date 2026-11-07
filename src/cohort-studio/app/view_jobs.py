from __future__ import annotations

import enum
import execution
import threading
import time
import uuid
from execution import FairExecutor as ThreadPoolExecutor

MAX_JOBS = 64
MAX_ACTIVE_JOBS = 8
JOB_TTL_SECONDS = 3600
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="saved-view")
_jobs: dict[str, dict] = {}
_lock = threading.Lock()


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


ACTIVE = frozenset({JobStatus.QUEUED.value, JobStatus.RUNNING.value})
TERMINAL = frozenset({JobStatus.COMPLETE.value, JobStatus.FAILED.value})
TRANSITIONS: dict[str, frozenset[str]] = {
    JobStatus.QUEUED.value: frozenset({JobStatus.RUNNING.value, JobStatus.COMPLETE.value,
                                       JobStatus.FAILED.value}),
    JobStatus.RUNNING.value: frozenset({JobStatus.RUNNING.value, JobStatus.COMPLETE.value,
                                        JobStatus.FAILED.value}),
    JobStatus.COMPLETE.value: frozenset(),
    JobStatus.FAILED.value: frozenset(),
}


def _transition(job: dict | None, status: JobStatus, **fields) -> bool:
    """Apply an allowed status change under `_lock`; terminal jobs never change."""
    if job is None or status.value not in TRANSITIONS[job["status"]]:
        return False
    job.update(fields, status=status.value, updated=time.monotonic())
    return True


def _prune(now: float) -> None:
    expired = [job_id for job_id, job in _jobs.items()
               if job["status"] in TERMINAL
               and now - job["updated"] > JOB_TTL_SECONDS]
    for job_id in expired:
        _jobs.pop(job_id, None)
    while len(_jobs) >= MAX_JOBS:
        terminal = [(job["updated"], job_id) for job_id, job in _jobs.items()
                    if job["status"] in TERMINAL]
        if not terminal:
            break
        _, oldest = min(terminal)
        _jobs.pop(oldest, None)


def _copy(job: dict) -> dict:
    return {key: value for key, value in job.items() if key not in {"updated", "key", "owner"}}


def running(key: str) -> bool:
    with _lock:
        return any(job.get("key") == key and job["status"] in ACTIVE
                   for job in _jobs.values())


def submit(name: str, total_sources: int, work, key: str | None = None, owner: str | None = None) -> dict:
    global _executor
    if not isinstance(name, str) or not name:
        raise ValueError("Saved view name is required.")
    if not isinstance(total_sources, int) or isinstance(total_sources, bool) or total_sources < 0:
        raise ValueError("Saved view source count is invalid.")
    now = time.monotonic()
    with _lock:
        _prune(now)
        if _executor._shutdown:
            _executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="saved-view")
        if key is not None and any(
                job.get("key") == key and job["status"] in ACTIVE
                for job in _jobs.values()):
            raise ValueError("A save or refresh job is already running for this view.")
        if owner and sum(job.get("owner") == owner and job["status"] in ACTIVE for job in _jobs.values()) >= 2:
            raise ValueError("Two saved-view jobs are already active for this session.")
        active = sum(job["status"] in ACTIVE for job in _jobs.values())
        if active >= MAX_ACTIVE_JOBS:
            raise ValueError("Too many saved-view jobs are running. Try again shortly.")
        if len(_jobs) >= MAX_JOBS:
            raise ValueError("Saved-view job history is full. Try again later.")
        job_id = uuid.uuid4().hex
        _jobs[job_id] = {"job_id": job_id, "status": JobStatus.QUEUED.value, "name": name,
                         "completed_sources": 0, "total_sources": total_sources,
                         "error": None, "key": key, "owner": owner, "updated": now}

    def progress(completed: int) -> None:
        if not isinstance(completed, int) or isinstance(completed, bool):
            return
        with _lock:
            job = _jobs.get(job_id)
            if job and job["status"] in ACTIVE:
                _transition(job, JobStatus.RUNNING, completed_sources=max(
                    job["completed_sources"], min(total_sources, max(0, completed))))

    @execution.workload("bulk")
    def run() -> None:
        with _lock:
            if not _transition(_jobs.get(job_id), JobStatus.RUNNING):
                return
        try:
            result = work(progress)
        except Exception as exc:
            error = str(exc).splitlines()[0][:300] or exc.__class__.__name__
            with _lock:
                _transition(_jobs.get(job_id), JobStatus.FAILED, error=error)
            return
        with _lock:
            job = _jobs.get(job_id)
            if _transition(job, JobStatus.COMPLETE, error=None,
                           completed_sources=total_sources):
                if isinstance(result, dict):
                    for key in ("materialized_sources", "refreshed_at", "refresh_mode"):
                        if key in result:
                            job[key] = result[key]

    execution.emit("job.submitted", job_id=job_id, kind="saved_view")
    execution.submit(_executor, run)
    with _lock:
        return _copy(_jobs[job_id])


def get(job_id: str, owner: str | None = None) -> dict | None:
    if not isinstance(job_id, str) or not job_id:
        return None
    now = time.monotonic()
    with _lock:
        _prune(now)
        job = _jobs.get(job_id)
        return _copy(job) if job and job.get("owner") == owner else None


def shutdown(wait: bool = False) -> None:
    if not wait:
        with _lock:
            for job in _jobs.values():
                if job["status"] == JobStatus.QUEUED.value:
                    _transition(job, JobStatus.FAILED, error="App stopped before this job started.")
    _executor.shutdown(wait=wait, cancel_futures=not wait)
