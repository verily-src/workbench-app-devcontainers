import copy
import csv
import os
import shutil
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from sql_utils import statement as text

import database as db
import live_query

MAX_JOBS = 8
MAX_JOB_BYTES = 2 * 1024 ** 3
MAX_TOTAL_BYTES = 4 * 1024 ** 3
MIN_FREE_BYTES = 64 * 1024 ** 2
TTL_SECONDS = 3600
BATCH_ROWS = 2000
TIMEOUT_MS = 300_000
MAX_DURATION_SECONDS = 1800
_ROOT = Path(tempfile.mkdtemp(prefix="studio-exports-"))
_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="studio-export")
_LOCK = threading.RLock()
_JOBS = {}
_CLOSED = False
_STOP = threading.Event()
_JANITOR = None


class ExportBusy(ValueError):
    pass


class ExportCancelled(Exception):
    pass


def _public(job):
    return {key: job[key] for key in
            ("id", "status", "rows", "bytes", "created_at", "error")}


def _remove_files(job):
    for suffix in (".part", ".tsv"):
        (_ROOT / (job["id"] + suffix)).unlink(missing_ok=True)


def _cleanup():
    now = time.monotonic()
    for job_id, job in list(_JOBS.items()):
        if job["status"] in ("complete", "failed", "cancelled") and not job["active"]:
            if now - job["finished"] >= TTL_SECONDS:
                _remove_files(job)
                del _JOBS[job_id]


def _reap():
    while not _STOP.wait(60):
        with _LOCK:
            _cleanup()


def start(live_source, filters):
    global _ROOT, _POOL, _CLOSED, _JANITOR
    live_query._where(filters, live_source["columns"])
    with _LOCK:
        if _CLOSED:
            _ROOT = Path(tempfile.mkdtemp(prefix="studio-exports-"))
            _POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="studio-export")
            _CLOSED = False
            _STOP.clear()
        if _JANITOR is None or not _JANITOR.is_alive():
            _JANITOR = threading.Thread(target=_reap, daemon=True, name="export-cleanup")
            _JANITOR.start()
        _cleanup()
        if len(_JOBS) >= MAX_JOBS:
            raise ExportBusy("Eight exports are retained. Remove an old export or wait for expiry.")
        if shutil.disk_usage(_ROOT).free < MIN_FREE_BYTES:
            raise ExportBusy("Not enough temporary disk space for an export.")
        job_id = uuid.uuid4().hex
        job = {"id": job_id, "status": "queued", "rows": 0, "bytes": 0,
               "created_at": datetime.now(timezone.utc).isoformat(), "error": None,
               "cancel": threading.Event(), "connection": None, "active": True,
               "finished": 0}
        _JOBS[job_id] = job
        _POOL.submit(_run, job, copy.deepcopy(live_source), copy.deepcopy(filters))
        return _public(job)


def status(job_id):
    with _LOCK:
        _cleanup()
        return _public(_JOBS[job_id])


def cancel(job_id):
    with _LOCK:
        job = _JOBS[job_id]
        completed = job["status"] == "complete"
        job["cancel"].set()
        job["status"] = "cancelled"
        job["finished"] = time.monotonic()
        connection = job["connection"]
        if completed or not job["active"]:
            _remove_files(job)
            job["bytes"] = 0
        if not job["active"]:
            del _JOBS[job_id]
        if connection is not None:
            try:
                connection.cancel()
            except Exception:
                pass
    return {"id": job_id, "status": "cancelled"}


def download(job_id):
    with _LOCK:
        _cleanup()
        job = _JOBS[job_id]
        if job["status"] != "complete":
            raise ValueError("The export is not complete.")
        return _ROOT / (job_id + ".tsv")


def _check(job, started):
    if job["cancel"].is_set():
        raise ExportCancelled()
    if time.monotonic() - started > MAX_DURATION_SECONDS:
        raise ValueError("Export exceeded the 30-minute limit. Narrow the filters and retry.")


def _run(job, source, filters):
    started = time.monotonic()
    part = _ROOT / (job["id"] + ".part")
    try:
        _check(job, started)
        with _LOCK:
            _check(job, started)
            job["status"] = "running"
        where, params = live_query._where(filters, source["columns"])
        params = {**source.get("params", {}), **params}
        fields = ", ".join(live_query._q(name) for name in source["columns"].values())
        sql = f"SELECT {fields} FROM ({source['sql']}) AS exported WHERE {where}"
        with db.get_engine_for_resource(source["resource_id"]).begin() as conn:
            with _LOCK:
                job["connection"] = conn.connection.driver_connection
            try:
                conn.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                conn.exec_driver_sql("SET LOCAL search_path = pg_catalog")
                conn.exec_driver_sql(f"SET LOCAL statement_timeout = {TIMEOUT_MS}")
                _check(job, started)
                result = conn.execution_options(yield_per=BATCH_ROWS).execute(text(sql), params)
                with result, part.open("w", encoding="utf-8", newline="") as stream:
                    writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
                    writer.writerow(source["columns"])
                    for rows in result.partitions(BATCH_ROWS):
                        _check(job, started)
                        if shutil.disk_usage(_ROOT).free < MIN_FREE_BYTES:
                            raise ValueError("Temporary disk space is low. Export stopped without a downloadable file.")
                        writer.writerows(rows)
                        stream.flush()
                        size = stream.tell()
                        with _LOCK:
                            total = sum(j["bytes"] for j in _JOBS.values() if j is not job)
                            if size > MAX_JOB_BYTES or total + size > MAX_TOTAL_BYTES:
                                raise ValueError("Export exceeds the temporary storage limit. Narrow the filters and retry.")
                            job["rows"] += len(rows)
                            job["bytes"] = size
                    stream.flush()
                    os.fsync(stream.fileno())
                    size = stream.tell()
            finally:
                with _LOCK:
                    job["connection"] = None
        with _LOCK:
            _check(job, started)
            total = sum(j["bytes"] for j in _JOBS.values() if j is not job)
            if size > MAX_JOB_BYTES or total + size > MAX_TOTAL_BYTES:
                raise ValueError("Export exceeds the temporary storage limit.")
            os.replace(part, _ROOT / (job["id"] + ".tsv"))
            job["bytes"] = size
            job["status"] = "complete"
    except Exception as exc:
        with _LOCK:
            if job["cancel"].is_set() or isinstance(exc, ExportCancelled):
                job["status"] = "cancelled"
            else:
                job["status"] = "failed"
                job["error"] = str(exc).split("\n")[0][:300]
            _remove_files(job)
            job["bytes"] = 0
    finally:
        with _LOCK:
            job["connection"] = None
            job["active"] = False
            job["finished"] = time.monotonic()


def shutdown():
    global _CLOSED, _JANITOR
    with _LOCK:
        if _CLOSED:
            return
        _CLOSED = True
        _STOP.set()
        ids = list(_JOBS)
    for job_id in ids:
        try:
            cancel(job_id)
        except KeyError:
            pass
    _POOL.shutdown(wait=True, cancel_futures=False)
    shutil.rmtree(_ROOT, ignore_errors=True)

    if _JANITOR is not None:
        _JANITOR.join(timeout=2)
        _JANITOR = None
    with _LOCK:
        _JOBS.clear()
