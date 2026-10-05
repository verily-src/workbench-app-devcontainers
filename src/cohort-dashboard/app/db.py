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


def _refresh_resource_cache():
    global _resource_cache
    with _resource_cache_lock:
        _resource_cache = _fetch_resources()
        _resource_cache_ready.set()
        logger.info("Resource cache refreshed: %d resources", len(_resource_cache))
    for r in list_aurora_resources():
        warm_connection_string(r["id"])


def warm_resource_cache():
    threading.Thread(target=_refresh_resource_cache, daemon=True).start()


def resources_ready() -> bool:
    return _resource_cache_ready.is_set()


def _ensure_cache(wait: bool = False) -> list[dict]:
    global _last_refresh
    if wait and not _resource_cache_ready.is_set():
        _resource_cache_ready.wait(timeout=120)
    elif (not wait and _resource_cache is not None
          and time.monotonic() - _last_refresh > _REFRESH_COOLDOWN):
        _last_refresh = time.monotonic()
        threading.Thread(target=_refresh_resource_cache, daemon=True).start()
    return _resource_cache or []


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
