import copy
import csv
import datetime as date_types
import decimal
import uuid as uuid_types
from contextlib import contextmanager
import gzip
import io
import json
import os
import shutil
import tempfile
import execution
import threading
import time
import uuid
from execution import FairExecutor as ThreadPoolExecutor
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
    for suffix in (".part", ".tsv", ".tsv.gz", ".json", ".parquet"):
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


def start(live_source, filters, format="tsv", *, owner=None):
    if format not in ("tsv", "tsv.gz", "json", "parquet"):
        raise ValueError("Unsupported export format.")
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
        owner = owner or execution.owner_id.get()
        if not owner:
            raise ValueError("An authenticated session is required for export.")
        if sum(j.get("owner") == owner and j["active"] for j in _JOBS.values()) >= 2:
            raise ExportBusy("Two exports are already active for this session.")
        if len(_JOBS) >= MAX_JOBS:
            raise ExportBusy("Eight exports are retained. Remove an old export or wait for expiry.")
        if shutil.disk_usage(_ROOT).free < MIN_FREE_BYTES:
            raise ExportBusy("Not enough temporary disk space for an export.")
        job_id = uuid.uuid4().hex
        job = {"id": job_id, "owner": owner, "status": "queued", "rows": 0, "bytes": 0,
               "created_at": datetime.now(timezone.utc).isoformat(), "error": None,
               "cancel": threading.Event(), "connection": None,
               "connection_lock": threading.Lock(), "active": True,
               "finished": 0, "format": format}
        _JOBS[job_id] = job
        try:
            execution.submit(_POOL, _run, job, copy.deepcopy(live_source), copy.deepcopy(filters))
        except Exception:
            _JOBS.pop(job_id, None)
            _remove_files(job)
            raise
        execution.emit("job.submitted", job_id=job_id, kind="export")
        return _public(job)


def _owned(job_id, owner=None):
    job = _JOBS[job_id]
    identity = owner or execution.owner_id.get()
    if not identity or job["owner"] != identity:
        raise KeyError(job_id)
    return job


def status(job_id, *, owner=None):
    with _LOCK:
        _cleanup()
        return _public(_owned(job_id, owner))


def cancel(job_id, *, owner=None):
    with _LOCK:
        job = _owned(job_id, owner)
        completed = job["status"] == "complete"
        job["cancel"].set()
        job["status"] = "cancelled"
        job["finished"] = time.monotonic()
        if completed or not job["active"]:
            _remove_files(job)
            job["bytes"] = 0
        if not job["active"]:
            del _JOBS[job_id]
    with job["connection_lock"]:
        with _LOCK:
            connection = job["connection"]
        if connection is not None:
            try:
                connection.cancel()
            except Exception:
                pass
    return {"id": job_id, "status": "cancelled"}


def download(job_id, *, owner=None):
    with _LOCK:
        _cleanup()
        job = _owned(job_id, owner)
        if job["status"] != "complete":
            raise ValueError("The export is not complete.")
        return _ROOT / (job_id + "." + job["format"])


def _check(job, started):
    if job["cancel"].is_set():
        raise ExportCancelled()
    if time.monotonic() - started > MAX_DURATION_SECONDS:
        raise ValueError("Export exceeded the 30-minute limit. Narrow the filters and retry.")


def _tsv_value(value):
    if isinstance(value, (dict, list)):
        return _json_dump(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "\\x" + bytes(value).hex()
    return value


def _json_dump(value):
    if isinstance(value, decimal.Decimal):
        if not value.is_finite():
            raise ValueError("JSON export does not support non-finite decimals.")
        return str(value)
    if isinstance(value, (date_types.date, date_types.time, date_types.datetime, uuid_types.UUID)):
        value = str(value) if isinstance(value, uuid_types.UUID) else value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = "\\x" + bytes(value).hex()
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_json_dump(item) for item in value) + "]"
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("JSON export requires string object keys.")
        return "{" + ",".join(json.dumps(key, ensure_ascii=False) + ":" + _json_dump(item)
                                for key, item in value.items()) + "}"
    if value is None or isinstance(value, (str, bool, int, float)):
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    raise ValueError(f"JSON export does not support {type(value).__name__} values.")


@contextmanager
def _preserve_json_numbers(conn, format):
    if conn.dialect.name != "postgresql":
        yield
        return
    from psycopg.pq import Format
    from psycopg.types.json import set_json_loads

    driver = conn.connection.driver_connection
    adapters = driver.adapters
    loaders = [(oid, adapters.get_loader(oid, representation))
               for oid in (114, 3802) for representation in (Format.TEXT, Format.BINARY)]
    if any(loader is None for _, loader in loaders):
        raise ValueError("Could not preserve PostgreSQL JSON numeric precision.")
    set_json_loads(lambda data: json.loads(data, parse_float=decimal.Decimal), context=driver)
    try:
        yield
    finally:
        for oid, loader in loaders:
            adapters.register_loader(oid, loader)


def _arrow_type(desc):
    import pyarrow as pa
    oid = getattr(desc, "type_code", None)
    simple = {16: pa.bool_(), 17: pa.binary(), 20: pa.int64(), 21: pa.int16(),
              23: pa.int32(), 26: pa.uint32(), 700: pa.float32(), 701: pa.float64(),
              1082: pa.date32(), 1083: pa.time64("us"), 1114: pa.timestamp("us"),
              1184: pa.timestamp("us", tz="UTC"), 18: pa.string(), 19: pa.string(),
              25: pa.string(), 1042: pa.string(), 1043: pa.string(), 2950: pa.string(),
              114: pa.string(), 3802: pa.string()}
    arrays = {1000: 16, 1005: 21, 1007: 23, 1016: 20, 1009: 25, 1015: 1043,
              1021: 700, 1022: 701, 1182: 1082, 1115: 1114, 1185: 1184, 2951: 2950}
    if oid == 1700:
        precision, scale = getattr(desc, "precision", None), getattr(desc, "scale", None)
        if isinstance(precision, int) and isinstance(scale, int) and 0 <= scale <= precision <= 38:
            return pa.decimal128(precision, scale)
        raise ValueError("Parquet export requires a NUMERIC column with explicit precision and scale. Cast the column and retry.")
    if oid in arrays:
        return pa.list_(simple[arrays[oid]])
    if oid not in simple:
        raise ValueError(f"Parquet export cannot preserve PostgreSQL type {oid}. Cast the column to a supported type.")
    return simple[oid]


def _arrow_value(value, desc):
    if value is None:
        return None
    oid = desc.type_code
    if oid in (114, 3802):
        return _json_dump(value)
    if oid == 2950:
        return str(value)
    if oid == 2951:
        return [str(item) if item is not None else None for item in value]
    if oid == 17:
        return bytes(value)
    return value


def _record_progress(job, started, path, count):
    _check(job, started)
    if shutil.disk_usage(_ROOT).free < MIN_FREE_BYTES:
        raise ValueError("Temporary disk space is low. Export stopped without a downloadable file.")
    size = path.stat().st_size
    with _LOCK:
        total = sum(j["bytes"] for j in _JOBS.values() if j is not job)
        if size > MAX_JOB_BYTES or total + size > MAX_TOTAL_BYTES:
            raise ValueError("Export exceeds the temporary storage limit. Narrow the filters and retry.")
        job["rows"] += count
        job["bytes"] = size


def _write_columnar(job, result, part, started, columns):
    format = job["format"]
    if len(columns) != len(set(columns)):
        raise ValueError("Export requires unique column names.")
    if format == "json":
        with part.open("w", encoding="utf-8") as stream:
            stream.write("[")
            first = True
            for rows in result.partitions(BATCH_ROWS):
                _check(job, started)
                for index, row in enumerate(rows):
                    if index % 100 == 0:
                        _check(job, started)
                    obj = dict(zip(columns, row))
                    stream.write(("" if first else ",") + _json_dump(obj))
                    first = False
                stream.flush()
                _record_progress(job, started, part, len(rows))
            stream.write("]")
            stream.flush()
            os.fsync(stream.fileno())
    else:
        import pyarrow as pa
        import pyarrow.parquet as pq
        descriptions = list(result.cursor.description)
        if len(descriptions) != len(columns):
            raise ValueError("Export columns changed; reload the source.")
        schema = pa.schema([pa.field(name, _arrow_type(desc)) for name, desc in zip(columns, descriptions)])
        with pq.ParquetWriter(str(part), schema) as writer:
            for rows in result.partitions(BATCH_ROWS):
                _check(job, started)
                batch = pa.RecordBatch.from_arrays(
                    [pa.array([_arrow_value(row[i], desc) for row in rows], type=schema.types[i])
                     for i, desc in enumerate(descriptions)], schema=schema)
                writer.write_batch(batch)
                _record_progress(job, started, part, len(rows))
        with part.open("rb") as stream:
            os.fsync(stream.fileno())
    _record_progress(job, started, part, 0)
    return part.stat().st_size


@execution.workload("bulk")
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
        with db.get_engine_for_resource(source["resource_id"]).begin() as conn, _preserve_json_numbers(conn, job["format"]):
            with job["connection_lock"]:
                with _LOCK:
                    _check(job, started)
                    job["connection"] = conn.connection.driver_connection
            try:
                conn.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                conn.exec_driver_sql("SET LOCAL search_path = pg_catalog")
                conn.exec_driver_sql(f"SET LOCAL statement_timeout = {TIMEOUT_MS}")
                _check(job, started)
                result = conn.execution_options(yield_per=BATCH_ROWS).execute(text(sql), params)
                if job["format"] in {"json", "parquet"}:
                    with result:
                        size = _write_columnar(job, result, part, started, list(source["columns"]))
                else:
                    with result, part.open("wb") as raw:
                        compressed = gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=6, mtime=0) if job["format"] == "tsv.gz" else raw
                        with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as stream:
                            writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
                            writer.writerow(source["columns"])
                            for rows in result.partitions(BATCH_ROWS):
                                _check(job, started)
                                if shutil.disk_usage(_ROOT).free < MIN_FREE_BYTES:
                                    raise ValueError("Temporary disk space is low. Export stopped without a downloadable file.")
                                writer.writerows([_tsv_value(value) for value in row] for row in rows)
                                stream.flush()
                                size = raw.tell()
                                with _LOCK:
                                    total = sum(j["bytes"] for j in _JOBS.values() if j is not job)
                                    if size > MAX_JOB_BYTES or total + size > MAX_TOTAL_BYTES:
                                        raise ValueError("Export exceeds the temporary storage limit. Narrow the filters and retry.")
                                    job["rows"] += len(rows)
                                    job["bytes"] = size
                            stream.flush()
                            if job["format"] == "tsv":
                                os.fsync(raw.fileno())
                        if not raw.closed:
                            raw.flush()
                            os.fsync(raw.fileno())
                        size = part.stat().st_size
            finally:
                with job["connection_lock"]:
                    with _LOCK:
                        job["connection"] = None
        with _LOCK:
            _check(job, started)
            total = sum(j["bytes"] for j in _JOBS.values() if j is not job)
            if size > MAX_JOB_BYTES or total + size > MAX_TOTAL_BYTES:
                raise ValueError("Export exceeds the temporary storage limit.")
            os.replace(part, _ROOT / (job["id"] + "." + job["format"]))
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
            cancel(job_id, owner=_JOBS[job_id]["owner"])
        except KeyError:
            pass
    _POOL.shutdown(wait=True, cancel_futures=False)
    shutil.rmtree(_ROOT, ignore_errors=True)

    if _JANITOR is not None:
        _JANITOR.join(timeout=2)
        _JANITOR = None
    with _LOCK:
        _JOBS.clear()
