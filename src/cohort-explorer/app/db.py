import logging
import os
import subprocess
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)

_engine = None
_SessionLocal: sessionmaker[Session] | None = None


def _resolve_aurora_connection() -> str:
    resource_id = os.environ["AURORA_RESOURCE_ID"]
    result = subprocess.run(
        ["wb", "resource", "resolve", "--id", resource_id, "--include-password"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _get_engine():
    global _engine
    if _engine is not None:
        return _engine

    resource_id = os.environ.get("AURORA_RESOURCE_ID", "")
    if resource_id:
        logger.info("Connecting to Aurora via wb resource resolve")
        _engine = create_engine(
            _resolve_aurora_connection(),
            pool_pre_ping=True,
            pool_recycle=600,
            pool_size=5,
        )
    else:
        db_path = Path(__file__).parent / "cohort_explorer.db"
        logger.info("No AURORA_RESOURCE_ID set, using SQLite at %s", db_path)
        _engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
        )

    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=_get_engine())
    return _SessionLocal


def get_db():
    factory = get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()
