"""Workbench Aurora connections.

Resolves connection strings through the `wb` CLI and caches aggressively:
the CLI routes through the Workbench backend and a single call can take
up to a minute, while the app proxy times out at ~60 seconds.

Trimmed from cohort-explorer's db.py. All data access in this app is SQL
against Aurora, so the SQLite/S3/seeding machinery is gone.
"""

import json
import logging
import subprocess
import threading
import time

from sqlalchemy import Engine, create_engine

from cache import ttl_cache

logger = logging.getLogger(__name__)

_engines: dict[str, Engine] = {}

_resource_cache: list[dict] | None = None
_resource_cache_lock = threading.Lock()
_resource_cache_ready = threading.Event()
_last_refresh = 0.0
_REFRESH_COOLDOWN = 60.0

_conn_string_cache: dict[str, str] = {}
_conn_string_events: dict[str, threading.Event] = {}


def resolve_connection_string(resource_id: str, access_mode: str = "WRITE_READ",
                              retries: int = 3) -> str:
    if resource_id in _conn_string_cache:
        return _conn_string_cache[resource_id]
    last_err = None
    for attempt in range(retries):
        try:
            result = subprocess.run(
                [
                    "wb", "resource", "resolve",
                    "--id", resource_id,
                    "--access-mode", access_mode,
                    "--include-password",
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=120,
            )
            conn_str = result.stdout.strip()
            _conn_string_cache[resource_id] = conn_str
            return conn_str
        except subprocess.CalledProcessError as e:
            last_err = e
            logger.warning("wb resource resolve attempt %d/%d failed for %s: %s",
                           attempt + 1, retries, resource_id, e.stderr or e.stdout)
    raise last_err


def warm_connection_string(resource_id: str):
    """Resolve a connection string in the background so the first query is fast."""
    if resource_id in _conn_string_cache or resource_id in _conn_string_events:
        return
    event = threading.Event()
    _conn_string_events[resource_id] = event

    def _resolve():
        try:
            resolve_connection_string(resource_id)
        except Exception as e:
            logger.warning("Failed to pre-warm connection string for %s: %s", resource_id, e)
        finally:
            event.set()

    threading.Thread(target=_resolve, daemon=True).start()


def _fetch_resources() -> list[dict]:
    try:
        result = subprocess.run(
            ["wb", "resource", "list", "--format", "json"],
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        logger.warning("wb resource list timed out")
        return []
    except FileNotFoundError:
        logger.warning("wb CLI not installed, no resources")
        return []
    except subprocess.CalledProcessError as e:
        logger.warning("wb resource list failed (rc=%d): %s", e.returncode, e.stderr or e.stdout)
        return []
    return json.loads(result.stdout)


_aws_configured = False
_s3_uri_cache: dict[str, str] = {}


def configure_aws_profiles():
    """Generate per-resource AWS profiles so aws-cli and DuckDB can reach S3."""
    global _aws_configured
    if _aws_configured:
        return
    try:
        subprocess.run(["wb", "workspace", "configure-aws"],
                       capture_output=True, text=True, check=True, timeout=120)
        logger.info("Configured AWS profiles via wb workspace configure-aws")
    except Exception as e:
        logger.warning("Failed to configure AWS profiles: %s", e)
    import glob
    import os
    matches = glob.glob(os.path.expanduser("~/.workbench/aws/*.conf"))
    if matches:
        os.environ["AWS_CONFIG_FILE"] = matches[0]
        logger.info("Set AWS_CONFIG_FILE to %s", matches[0])
    _aws_configured = True


def resolve_s3_uri(resource_id: str) -> str:
    """s3:// URI of a storage-folder resource, without a trailing slash."""
    if resource_id not in _s3_uri_cache:
        result = subprocess.run(
            ["wb", "resource", "resolve", "--id", resource_id],
            capture_output=True, text=True, check=True, timeout=120)
        _s3_uri_cache[resource_id] = result.stdout.strip().rstrip("/")
    return _s3_uri_cache[resource_id]


def _refresh_resource_cache():
    global _resource_cache
    with _resource_cache_lock:
        _resource_cache = _fetch_resources()
        _resource_cache_ready.set()
        logger.info("Resource cache refreshed: %d resources", len(_resource_cache))
    configure_aws_profiles()
    for r in list_aurora_resources():
        warm_connection_string(r["id"])
    threading.Thread(target=_warm_catalogs, daemon=True).start()


def _warm_catalogs():
    """Pre-fill table/file listings so the first click is instant."""
    for r in list_aurora_resources():
        try:
            list_aurora_tables(r["id"])
        except Exception as e:
            logger.warning("Failed to warm tables for %s: %s", r["id"], e)
    import duck  # late import: duck imports db
    for f in list_s3_folders():
        try:
            duck.list_s3_files(f["id"])
        except Exception as e:
            logger.warning("Failed to warm S3 files for %s: %s", f["id"], e)


@ttl_cache(ttl=300)
def list_aurora_tables(resource_id: str) -> list[dict]:
    import queries
    return queries.list_tables(get_engine_for_resource(resource_id))


@ttl_cache(ttl=600, maxsize=4)
def fetch_aurora_table(resource_id: str, table: str, cap: int):
    """Cached capped read. The DataFrame is shared — do not mutate it."""
    import queries
    return queries.fetch_table(get_engine_for_resource(resource_id), table, cap)


def warm_resource_cache():
    threading.Thread(target=_refresh_resource_cache, daemon=True).start()


def resources_ready() -> bool:
    return _resource_cache_ready.is_set()


_retry_lock = threading.Lock()
_last_retry = 0.0
_RETRY_COOLDOWN = 20.0


def retry_if_empty():
    """Re-fetch when the cache is 'ready' but empty.

    On a Workbench VM the app container starts before post-startup.sh has
    logged in the wb CLI, so the first `wb resource list` can fail and the
    cache ends up ready-with-nothing. Callers hit this on every
    /api/datasources poll; the cooldown keeps it to one wb call per 20s
    until resources appear.
    """
    global _last_retry
    if _resource_cache:
        return
    with _retry_lock:
        now = time.monotonic()
        if now - _last_retry < _RETRY_COOLDOWN:
            return
        _last_retry = now
    threading.Thread(target=_refresh_resource_cache, daemon=True).start()


def _ensure_cache(wait: bool = False) -> list[dict]:
    global _last_refresh
    if wait and not _resource_cache_ready.is_set():
        _resource_cache_ready.wait(timeout=120)
    elif (not wait and _resource_cache is not None
          and time.monotonic() - _last_refresh > _REFRESH_COOLDOWN):
        _last_refresh = time.monotonic()
        threading.Thread(target=_refresh_resource_cache, daemon=True).start()
    return _resource_cache or []


def bucket_by_uuid() -> dict[str, dict]:
    """Map resource UUID -> {id, bucket_name, prefix} for S3 resources,
    so callers can resolve a workflow job's outputBucketUuid to a name."""
    out = {}
    for r in _ensure_cache():
        if "S3" not in r.get("resourceType", "") or not r.get("uuid"):
            continue
        out[r["uuid"]] = {"id": r.get("id"),
                          "bucket_name": r.get("bucketName"),
                          "prefix": r.get("prefix")}
    return out


def list_aurora_resources(wait: bool = False) -> list[dict]:
    aurora = []
    for r in _ensure_cache(wait=wait):
        rtype = r.get("resourceType", "")
        if "AURORA_DATABASE" not in rtype:
            continue
        db_data = r if rtype == "AWS_AURORA_DATABASE" else r.get("referencedResource", r)
        aurora.append({
            "id": r.get("id"),
            "database": db_data.get("databaseName"),
            "region": db_data.get("region"),
        })
    return aurora


def list_s3_folders(wait: bool = False) -> list[dict]:
    folders = []
    for r in _ensure_cache(wait=wait):
        rtype = r.get("resourceType", "")
        if "S3" not in rtype:
            continue
        folders.append({"id": r.get("id"), "uuid": r.get("uuid"),
                        "prefix": r.get("prefix")})
    return folders


def list_bq_datasets(wait: bool = False) -> list[dict]:
    datasets = []
    for r in _ensure_cache(wait=wait):
        if r.get("resourceType") != "BQ_DATASET":
            continue
        datasets.append({
            "id": r.get("id"),
            "project": r.get("projectId"),
            "dataset": r.get("datasetId"),
        })
    return datasets


def get_engine_for_resource(resource_id: str) -> Engine:
    if resource_id in _engines:
        return _engines[resource_id]

    def creator():
        import psycopg
        if resource_id in _conn_string_cache:
            try:
                return psycopg.connect(_conn_string_cache[resource_id], autocommit=False)
            except Exception:
                logger.info("Cached connection string expired, refreshing for %s", resource_id)
                _conn_string_cache.pop(resource_id, None)
        conn_str = resolve_connection_string(resource_id)
        return psycopg.connect(conn_str, autocommit=False)

    engine = create_engine(
        "postgresql+psycopg://",
        creator=creator,
        pool_pre_ping=True,
        pool_recycle=600,
        pool_size=5,
    )
    _engines[resource_id] = engine
    return engine
