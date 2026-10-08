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


def _bucket_map() -> dict:
    """UUID -> bucket info, best-effort — never fail the jobs listing."""
    try:
        import db
        return db.bucket_by_uuid()
    except Exception as e:
        logger.warning("bucket resolution unavailable: %s", e)
        return {}


def _normalize(job: dict, buckets: dict) -> dict:
    msg = job.get("statusMessage")
    uuid = job.get("outputBucketUuid")
    bucket = buckets.get(uuid, {})
    return {
        "run_id": job.get("runId"),
        "name": job.get("displayName") or job.get("runId"),
        "status": (job.get("status") or "UNKNOWN").upper(),
        "workflow_type": job.get("workflowType"),
        "engine_type": job.get("engineType"),
        "created_by": job.get("createdBy"),
        "created_date": job.get("createdDate"),
        "end_time": job.get("endTime"),
        "output_bucket_uuid": uuid,
        "output_bucket_path": job.get("outputBucketPath"),
        # Resolved from the resource cache so the UI can show a name, not
        # just an opaque UUID. May be None if the bucket isn't a resource
        # this workspace can see.
        "output_bucket_name": bucket.get("bucket_name"),
        "output_bucket_resource": bucket.get("id"),
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
        buckets = _bucket_map()
        jobs = [_normalize(j, buckets) for j in raw]
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


_registry_cache: list | None = None
_registry_at = 0.0


def list_workflows(force: bool = False) -> dict:
    """Registered workflows for the submit dropdown. Cached ~5 min."""
    global _registry_cache, _registry_at
    now = time.monotonic()
    if _registry_cache is not None and not force and now - _registry_at < 300:
        return {"available": True, "workflows": _registry_cache}
    try:
        result = subprocess.run(
            ["wb", "workflow", "list", "--format", "JSON", "--limit", "1000"],
            capture_output=True, text=True, check=True, timeout=30)
        raw = json.loads(result.stdout or "[]")
        wfs = [{"id": w.get("id"), "name": w.get("displayName") or w.get("id"),
                "type": w.get("workflowType"),
                "description": w.get("description")} for w in raw]
        _registry_cache, _registry_at = wfs, now
        return {"available": True, "workflows": wfs}
    except Exception as e:
        logger.warning("wb workflow list failed: %s", e)
        return {"available": False, "workflows": []}


def export_cohort_csv(df, resource_id: str, path: str) -> dict:
    """Write a cohort DataFrame as a CSV into an S3 bucket resource, so it
    can be fed to a workflow as batch input. Returns the s3:// URI."""
    import db
    uri = f"{db.resolve_s3_uri(resource_id)}/{path.lstrip('/')}"
    out = subprocess.run(
        ["aws", "s3", "cp", "-", uri, "--profile", resource_id,
         "--content-type", "text/csv"],
        input=df.to_csv(index=False), capture_output=True, text=True,
        timeout=300)
    if out.returncode != 0:
        raise RuntimeError(
            (out.stderr or out.stdout or "").strip().split("\n")[-1][:300])
    return {"s3_uri": uri, "resource_id": resource_id, "path": path,
            "rows": int(len(df))}


def submit_job(workflow: str, output_bucket_id: str, job_id: str = "",
               batch_input_bucket_id: str = "", batch_input_csv_path: str = "",
               column_mapping: str = "", row_selection: str = "",
               profile: str = "") -> dict:
    """Launch a workflow job via `wb workflow job run`. Returns the created
    job (normalized). Raises RuntimeError with the CLI message on failure."""
    args = ["wb", "workflow", "job", "run", "--workflow", workflow,
            "--output-bucket-id", output_bucket_id, "--format", "JSON"]
    if job_id:
        args += ["--job-id", job_id]
    if batch_input_bucket_id and batch_input_csv_path:
        args += ["--batch-input-bucket-id", batch_input_bucket_id,
                 "--batch-input-csv-path", batch_input_csv_path]
        if column_mapping:
            args += ["--column-mapping", column_mapping]
        if row_selection:
            args += ["--row-selection", row_selection]
    if profile:
        args += ["--profile", profile]
    out = subprocess.run(args, capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(
            (out.stderr or out.stdout or "").strip().split("\n")[-1][:300])
    job = json.loads(out.stdout or "{}")
    _cache_bust()
    return _normalize(job, _bucket_map())


def _cache_bust():
    """Drop the jobs cache so a freshly-submitted job shows immediately."""
    global _cache, _cache_at
    _cache, _cache_at = None, 0.0
