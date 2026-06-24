import json
import logging
import subprocess
import threading
from pathlib import Path

from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)

_engines: dict[str, Engine] = {}
_session_factories: dict[str, sessionmaker[Session]] = {}
_active_resource_id: str | None = None

_resource_cache: list[dict] | None = None
_resource_cache_lock = threading.Lock()
_resource_cache_ready = threading.Event()

_conn_string_cache: dict[str, str] = {}


def resolve_connection_string(resource_id: str, access_mode: str = "WRITE_READ") -> str:
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
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.warning("wb CLI not available, no resources")
        return []
    return json.loads(result.stdout)


def _refresh_resource_cache():
    global _resource_cache
    with _resource_cache_lock:
        _resource_cache = _fetch_resources()
        _resource_cache_ready.set()
        logger.info("Resource cache refreshed: %d resources", len(_resource_cache))


def _ensure_cache(wait: bool = False) -> list[dict]:
    if wait and not _resource_cache_ready.is_set():
        _resource_cache_ready.wait(timeout=120)
    elif _resource_cache is not None:
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
            "name": r.get("id"),
            "database": db_data.get("databaseName"),
            "rw_endpoint": db_data.get("rwEndpoint"),
            "ro_endpoint": db_data.get("roEndpoint"),
            "port": db_data.get("port"),
            "region": db_data.get("region"),
            "resource_type": rtype,
        })
    return aurora


def list_s3_folders(wait: bool = False) -> list[dict]:
    folders = []
    for r in _ensure_cache(wait=wait):
        rtype = r.get("resourceType", "")
        if "S3" not in rtype:
            continue
        folders.append({
            "id": r.get("id"),
            "name": r.get("id"),
            "resource_type": rtype,
        })
    return folders


def warm_resource_cache():
    threading.Thread(target=_refresh_resource_cache, daemon=True).start()


_conn_warm_events: dict[str, threading.Event] = {}


def warm_connection_string(resource_id: str):
    event = threading.Event()
    _conn_warm_events[resource_id] = event

    def _resolve():
        try:
            resolve_connection_string(resource_id)
        except Exception as e:
            logger.warning("Failed to warm connection for %s: %s", resource_id, e)
        finally:
            event.set()

    threading.Thread(target=_resolve, daemon=True).start()


def wait_connection_string(resource_id: str, timeout: float = 120):
    event = _conn_warm_events.get(resource_id)
    if event:
        event.wait(timeout=timeout)


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


def get_sqlite_engine() -> Engine:
    if "sqlite" in _engines:
        return _engines["sqlite"]

    db_path = Path(__file__).parent / "cohort_explorer.db"
    logger.info("Using SQLite at %s", db_path)
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    _engines["sqlite"] = engine
    return engine


def set_active_resource(resource_id: str | None):
    global _active_resource_id
    _active_resource_id = resource_id
    if resource_id and resource_id not in _session_factories:
        engine = get_engine_for_resource(resource_id)
        _session_factories[resource_id] = sessionmaker(bind=engine)
    logger.info("Active resource set to: %s", resource_id or "sqlite")


def get_active_resource_id() -> str | None:
    return _active_resource_id


def get_db():
    rid = _active_resource_id
    if rid and rid in _session_factories:
        factory = _session_factories[rid]
    else:
        key = "sqlite"
        if key not in _session_factories:
            _session_factories[key] = sessionmaker(bind=get_sqlite_engine())
        factory = _session_factories[key]

    db = factory()
    try:
        yield db
    finally:
        db.close()
