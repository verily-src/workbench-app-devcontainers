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
import cloud_cli
import resource_discovery as discovery
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
# Set when the list came from the on-disk snapshot: the first refresh
# attempt then runs the start-up warm-up even though the cache is not empty.
_needs_warm = False
_state = discovery.State()

_conn_string_cache: dict[str, str] = {}
_conn_string_events: dict[str, threading.Event] = {}
_conn_string_locks: dict[str, threading.Lock] = {}
_conn_string_locks_guard = threading.Lock()


def _resolve_lock(resource_id: str) -> threading.Lock:
    with _conn_string_locks_guard:
        return _conn_string_locks.setdefault(resource_id, threading.Lock())


class ConnectionStringError(RuntimeError):
    """`wb resource resolve` failed. The message carries the CLI's own reason
    (e.g. "not authorized to read workspace X"), not the command line."""

    def __init__(self, resource_id: str, cause: subprocess.CalledProcessError):
        text = (cause.stderr or cause.stdout or "").strip()
        reason = next((ln.removeprefix("[ERROR]").strip()
                       for ln in text.splitlines() if ln.strip()), "")
        super().__init__(
            f"Could not get credentials for {resource_id}: "
            f"{reason or f'wb exited with status {cause.returncode}'}")


CONNECT_TIMEOUT_S = 10


def resolve_connection_string(resource_id: str, access_mode: str = "WRITE_READ",
                              retries: int = 3) -> str:
    if resource_id in _conn_string_cache:
        return _conn_string_cache[resource_id]
    # One `wb resource resolve` per resource at a time: a query that arrives
    # while warm-up is resolving waits for that result instead of spawning a
    # second CLI call (each can take up to 120 s).
    with _resolve_lock(resource_id):
        if resource_id in _conn_string_cache:
            return _conn_string_cache[resource_id]
        return _resolve_connection_string(resource_id, access_mode, retries)


def _resolve_connection_string(resource_id: str, access_mode: str, retries: int) -> str:
    last_err = None
    for attempt in range(retries):
        try:
            result = cloud_cli.run(
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
    raise ConnectionStringError(resource_id, last_err) from last_err


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


def _list_resources(extra: list[str], timeout: float = 120) -> list[dict]:
    """One `wb resource list` call; raises discovery.DiscoveryError."""
    args = ["wb", "resource", "list", "--format", "json", *extra]
    try:
        result = cloud_cli.run(args, capture_output=True, text=True, check=True,
                               timeout=timeout)
        return discovery.sanitize(json.loads(result.stdout or "[]"))
    except Exception as e:
        err = discovery.classify(e)
        if isinstance(e, subprocess.CalledProcessError):
            # Logged for operators only; never surfaced to the browser.
            logger.warning("%s failed (rc=%d): %s", " ".join(args[:3] + extra), e.returncode,
                           (e.stderr or e.stdout or "")[:500])
        else:
            logger.warning("%s failed: %s", " ".join(args[:3] + extra), err.code)
        raise err from None


def _fetch_resources() -> list[dict]:
    """All Studio-relevant workspace resources, allowlisted.

    Raises discovery.DiscoveryError when nothing could be listed and
    discovery.PartialDiscovery when some kinds listed and others failed: a
    single broken resource (e.g. a BigQuery reference in an AWS-only
    workspace) fails the full `wb resource list`, so the listing falls back
    to one call per resource type.
    """
    try:
        return _list_resources([])
    except discovery.DiscoveryError as e:
        err = e
    if err.code == "no_workspace" and discovery.workspace_id():
        try:
            return _list_resources([f"--workspace={discovery.workspace_id()}"])
        except discovery.DiscoveryError as e:
            err = e
    if err.code in discovery.GLOBAL_CODES:
        raise err
    workspace = [f"--workspace={discovery.workspace_id()}"] if discovery.workspace_id() else []
    found: list[dict] = []
    failed: dict[str, discovery.DiscoveryError] = {}
    failed_types: set[str] = set()
    for kind, types in discovery.KIND_TYPES.items():
        for rtype in types:
            try:
                found.extend(_list_resources([f"--type={rtype}", *workspace], timeout=90))
            except discovery.DiscoveryError as e:
                if e.code in discovery.GLOBAL_CODES:
                    raise e
                failed.setdefault(kind, e)
                failed_types.add(rtype)
    if len(failed) == len(discovery.KIND_TYPES):
        raise err
    if failed:
        raise discovery.PartialDiscovery(found, failed, failed_types)
    return found


_aws_configured = False
_aws_profile_ids: set[str] = set()
_s3_uri_cache: dict[str, str] = {}


def configure_aws_profiles(resource_ids=None):
    """Generate per-resource AWS profiles so aws-cli and DuckDB can reach S3.

    Runs once at startup, and again when `resource_ids` names an S3 resource
    that has no profile yet (e.g. a folder created after the app started);
    otherwise `--profile <new-folder>` fails until the app restarts.
    """
    global _aws_configured
    wanted = set(resource_ids or ())
    if _aws_configured and wanted <= _aws_profile_ids:
        return
    try:
        cloud_cli.run(["wb", "workspace", "configure-aws"],
                       capture_output=True, text=True, check=True, timeout=120)
        logger.info("Configured AWS profiles via wb workspace configure-aws")
        _aws_profile_ids.update(wanted)
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
        result = cloud_cli.run(
            ["wb", "resource", "resolve", "--id", resource_id],
            capture_output=True, text=True, check=True, timeout=120)
        _s3_uri_cache[resource_id] = result.stdout.strip().rstrip("/")
    return _s3_uri_cache[resource_id]


def _have_data() -> bool:
    return bool(_resource_cache)


def discovery_status() -> dict:
    """Freshness of the resource list, for /api/datasources."""
    return _state.snapshot(_have_data())


def _clock() -> float:
    """Monotonic seconds (a hook so tests can step time)."""
    return time.monotonic()


def _start_timer(delay: float, fn) -> None:
    """Hook for tests: run `fn` after `delay` seconds on a daemon thread."""
    timer = threading.Timer(delay, fn)
    timer.daemon = True
    timer.start()


def _spawn(fn) -> None:
    """Hook for tests: run `fn` on a daemon thread."""
    threading.Thread(target=fn, daemon=True).start()


def request_refresh(manual: bool = False) -> bool:
    """Start one background refresh if the gate allows; True when started.

    Every trigger (periodic access, empty-cache retry, the backoff timer and
    the Retry button) comes through here, so at most one `wb resource list`
    cycle is in flight and failures back off instead of queueing CLI calls.
    A manual retry skips the backoff wait but not an in-flight refresh.
    """
    now = _clock()
    with _state.lock:
        if _state.in_flight or _resource_cache_lock.locked():
            return False
        if manual:
            if now - _state.last_manual < discovery.MANUAL_DEBOUNCE_S:
                return False
            _state.last_manual = now
        elif now < _state.next_allowed:
            return False
        _state.in_flight = True
    _spawn(_refresh_resource_cache)
    return True


def _retry_from_timer():
    with _state.lock:
        _state.timer_pending = False
        if _state.failures == 0:
            return          # a manual retry already succeeded
        _state.next_allowed = 0.0
    request_refresh()


def _refresh_resource_cache():
    global _resource_cache, _last_refresh, _needs_warm
    if not _resource_cache_lock.acquire(blocking=False):
        return
    initial = not _resource_cache
    with _state.lock:
        _state.in_flight = True
    failure = None
    failed_kinds: dict[str, discovery.DiscoveryError] = {}
    try:
        try:
            fetched = _fetch_resources()
        except discovery.PartialDiscovery as p:
            failed_kinds = p.failed
            # Keep the last known entries of the kinds that failed.
            fetched = discovery.merge_partial(p.resources, _resource_cache or [],
                                              failed_kinds, p.failed_types)
        except Exception as e:
            failure = discovery.classify(e)
            fetched = None
        if fetched is None:
            logger.warning("Resource discovery failed (%s); keeping %d cached resources",
                           failure.code, len(_resource_cache or []))
            if _resource_cache is None:
                _resource_cache = []
        elif fetched or not _resource_cache:
            _resource_cache = fetched
            if fetched and not failed_kinds:
                discovery.save(fetched, _s3_uri_cache)
        else:
            logger.warning("Resource discovery returned no results; retaining the last successful snapshot")
            failure = discovery.DiscoveryError(
                "empty", "The Workbench CLI listed no resources; showing the previous list.")
        _last_refresh = time.monotonic()
        _resource_cache_ready.set()
        _record_outcome(failure, failed_kinds)
        logger.info("Resource cache refreshed: %d resources", len(_resource_cache or []))
    finally:
        with _state.lock:
            _state.in_flight = False
        _resource_cache_lock.release()
    # Warm after the first attempt that leaves something to warm (a list
    # loaded from the snapshot counts, even if this refresh failed).
    first = bool(_resource_cache) and (initial or _needs_warm)
    if first:
        _needs_warm = False
    s3_ids = [r.get("id") for r in _resource_cache or []
              if "S3" in r.get("resourceType", "") and r.get("id")]
    if _resource_cache and (first or set(s3_ids) - _aws_profile_ids):
        configure_aws_profiles(s3_ids)
    if first and _resource_cache:
        for r in list_aurora_resources():
            warm_connection_string(r["id"])
        threading.Thread(target=_warm_catalogs, daemon=True).start()


def _record_outcome(failure, failed_kinds) -> None:
    now = _clock()
    schedule = None
    with _state.lock:
        _state.in_flight = False
        _state.attempted = True
        if failure is None and not failed_kinds:
            _state.ok = True
            _state.error = None
            _state.failed_kinds = {}
            _state.failures = 0
            _state.retry_at = None
            _state.from_cache = False
            _state.updated_at = time.time()
            _state.next_allowed = now + (discovery.EMPTY_REFRESH_S if not _resource_cache
                                         else discovery.REFRESH_INTERVAL_S)
            return
        _state.ok = failure is None
        _state.error = failure
        _state.failed_kinds = {k: discovery.kind_failure_message(k, e)
                               for k, e in failed_kinds.items()}
        if failure is None:
            # The kinds that did list are current; the failed ones are cached.
            _state.updated_at = time.time() if not _state.updated_at else _state.updated_at
        _state.failures += 1
        delay = discovery.retry_delay(_state.failures)
        _state.next_allowed = now + delay
        _state.retry_at = time.time() + delay
        if not _state.timer_pending:
            _state.timer_pending = True
            schedule = delay
    if schedule is not None:
        _start_timer(schedule, _retry_from_timer)


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


def load_cached_resources() -> bool:
    """Serve the last good discovery snapshot until a refresh lands."""
    global _resource_cache, _needs_warm
    snap = discovery.load()
    if not snap or _resource_cache:
        return False
    _resource_cache = snap["resources"]
    _needs_warm = True
    for rid, uri in snap["s3_uris"].items():
        _s3_uri_cache.setdefault(rid, uri)
    with _state.lock:
        _state.from_cache = True
        _state.updated_at = snap["updated_at"]
    _resource_cache_ready.set()
    logger.info("Loaded %d resources from the discovery snapshot", len(_resource_cache))
    return True


def warm_resource_cache():
    load_cached_resources()
    request_refresh()


def resources_ready() -> bool:
    return _resource_cache_ready.is_set()


def retry_if_empty():
    """Re-fetch when the cache is 'ready' but empty.

    On a Workbench VM the app container starts before post-startup.sh has
    logged in the wb CLI, so the first `wb resource list` can fail and the
    cache ends up ready-with-nothing. Callers hit this on every
    /api/datasources poll; the refresh gate's backoff keeps it to one wb
    call per retry window until resources appear.
    """
    if _resource_cache:
        return
    request_refresh()


def _ensure_cache(wait: bool = False) -> list[dict]:
    if wait and not _resource_cache_ready.is_set():
        _resource_cache_ready.wait(timeout=120)
    elif (not wait and _resource_cache is not None
          and time.monotonic() - _last_refresh > (300 if _resource_cache else _REFRESH_COOLDOWN)):
        request_refresh()
    return _resource_cache or []


def _reset_for_tests() -> None:
    global _resource_cache, _last_refresh, _needs_warm, _resource_cache_ready
    _resource_cache = None
    _last_refresh = 0.0
    _needs_warm = False
    _resource_cache_ready = threading.Event()
    _s3_uri_cache.clear()
    _state.reset()


def bucket_by_uuid(refresh: bool = False) -> dict[str, dict]:
    """Map resource UUID -> {id, bucket_name, prefix} for S3 resources,
    so callers can resolve a workflow job's outputBucketUuid to a name."""
    out = {}
    try:
        resources = _fetch_resources() if refresh else _ensure_cache()
    except discovery.PartialDiscovery as p:
        resources = p.resources
    except discovery.DiscoveryError:
        resources = _ensure_cache()
    for r in resources:
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


def list_workbench_bq_datasets(wait: bool = False) -> list[dict]:
    """Workbench BigQuery references only (registered sources are listed separately)."""
    return list_bq_datasets(wait=wait, include_registered=False)


def list_bq_datasets(wait: bool = False, include_registered: bool = True) -> list[dict]:
    """BigQuery sources: Workbench dataset and table references, plus
    sources registered in Studio (ids prefixed "bq:"). A table reference
    exposes just that table."""
    datasets = []
    for r in _ensure_cache(wait=wait):
        rtype = r.get("resourceType")
        if rtype not in ("BQ_DATASET", "BQ_DATA_TABLE", "BQ_TABLE"):
            continue
        table = (r.get("dataTableId") or r.get("tableId") or "") if rtype != "BQ_DATASET" else ""
        datasets.append({
            "id": r.get("id"),
            "project": r.get("projectId"),
            "dataset": r.get("datasetId"),
            "table": table,
            "billing_project": "",
        })
    if include_registered:
        import source_registry
        for item in source_registry.entries("bq"):
            datasets.append({"id": f"bq:{item['id']}", "project": item["project"],
                             "dataset": item["dataset"], "table": item["table"],
                             "billing_project": item["billing_project"]})
    return datasets


def get_engine_for_resource(resource_id: str) -> Engine:
    if resource_id in _engines:
        return _engines[resource_id]

    def creator():
        import psycopg
        if resource_id in _conn_string_cache:
            try:
                return psycopg.connect(_conn_string_cache[resource_id], autocommit=False,
                                       connect_timeout=CONNECT_TIMEOUT_S)
            except Exception:
                logger.info("Cached connection string expired, refreshing for %s", resource_id)
                _conn_string_cache.pop(resource_id, None)
        conn_str = resolve_connection_string(resource_id)
        return psycopg.connect(conn_str, autocommit=False,
                               connect_timeout=CONNECT_TIMEOUT_S)

    engine = create_engine(
        "postgresql+psycopg://",
        creator=creator,
        pool_pre_ping=True,
        pool_recycle=600,
        pool_size=5,
    )
    _engines[resource_id] = engine
    return engine
