"""Workbench workflow jobs — surface running/recent runs in the app.

Shells out to `wb workflow job list --format=JSON` and normalizes the
result. Jobs write their outputs to an S3 bucket resource
(outputBucketUuid + outputBucketPath), which lets the UI warn when a
loaded datasource is the output of a job that is still running.

Every failure degrades to "unavailable" — the container's `wb` build may
predate the `workflow` command, or there may be no workspace — so this
never raises into the request path.
"""

import json
import logging
import subprocess
import time

logger = logging.getLogger(__name__)

# Job status is the one thing in this app that changes under the user, so
# the cache is deliberately short and there is a manual Refresh button.
_TTL = 45
_cache: dict | None = None
_cache_at = 0.0

# "Running" is everything NOT in this terminal set — HealthOmics adds
# states we may not have seen (PENDING, STARTING, STOPPING), and an
# allowlist would silently drop them.
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "CANCELED", "DELETED"}


def _run(limit: int) -> list[dict]:
    """Raw `wb workflow job list` JSON, or [] on any failure."""
    result = subprocess.run(
        ["wb", "workflow", "job", "list", "--format", "JSON",
         "--limit", str(limit)],
        capture_output=True, text=True, check=True, timeout=30)
    return json.loads(result.stdout or "[]")


def _normalize(job: dict) -> dict:
    msg = job.get("statusMessage")
    return {
        "run_id": job.get("runId"),
        "name": job.get("displayName") or job.get("runId"),
        "status": (job.get("status") or "UNKNOWN").upper(),
        "workflow_type": job.get("workflowType"),
        "engine_type": job.get("engineType"),
        "created_by": job.get("createdBy"),
        "created_date": job.get("createdDate"),
        "end_time": job.get("endTime"),
        "output_bucket_uuid": job.get("outputBucketUuid"),
        "output_bucket_path": job.get("outputBucketPath"),
        "status_message": msg[:200] if msg else None,
    }


def list_jobs(limit: int = 50, force: bool = False) -> dict:
    """Normalized jobs plus availability + running count. Cached ~45s."""
    global _cache, _cache_at
    now = time.monotonic()
    if _cache is not None and not force and now - _cache_at < _TTL:
        return _cache
    try:
        raw = _run(limit)
        jobs = [_normalize(j) for j in raw]
        running = sum(1 for j in jobs if j["status"] not in TERMINAL)
        out = {"available": True, "jobs": jobs, "running_count": running}
    except FileNotFoundError:
        out = {"available": False, "jobs": [], "running_count": 0}
    except subprocess.TimeoutExpired:
        logger.warning("wb workflow job list timed out")
        out = {"available": False, "jobs": [], "running_count": 0}
    except subprocess.CalledProcessError as e:
        logger.warning("wb workflow job list failed (rc=%d): %s",
                       e.returncode, (e.stderr or e.stdout or "")[:200])
        out = {"available": False, "jobs": [], "running_count": 0}
    except Exception as e:  # malformed JSON, etc. — never break the request
        logger.warning("wb workflow job list error: %s", e)
        out = {"available": False, "jobs": [], "running_count": 0}
    _cache, _cache_at = out, now
    return out


def is_running(status: str) -> bool:
    return (status or "").upper() not in TERMINAL
