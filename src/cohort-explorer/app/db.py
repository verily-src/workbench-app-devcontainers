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

_aurora_cache: list[dict] | None = None
_aurora_cache_lock = threading.Lock()


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
        timeout=30,
    )
    return result.stdout.strip()


def _fetch_aurora_resources() -> list[dict]:
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
        logger.warning("wb CLI not available, no Aurora resources")
        return []

    resources = json.loads(result.stdout)
    aurora = []
    for r in resources:
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


def _refresh_aurora_cache():
    global _aurora_cache
    with _aurora_cache_lock:
        result = _fetch_aurora_resources()
        _aurora_cache = result
        logger.info("Aurora resource cache refreshed: %d resources", len(result))


def list_aurora_resources() -> list[dict]:
    if _aurora_cache is not None:
        threading.Thread(target=_refresh_aurora_cache, daemon=True).start()
    return _aurora_cache or []


def warm_aurora_cache():
    threading.Thread(target=_refresh_aurora_cache, daemon=True).start()


def refresh_aurora_cache() -> list[dict]:
    _refresh_aurora_cache()
    return _aurora_cache or []


def get_engine_for_resource(resource_id: str) -> Engine:
    if resource_id in _engines:
        return _engines[resource_id]

    def creator():
        import psycopg
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
