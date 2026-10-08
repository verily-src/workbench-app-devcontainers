"""Saved views: persist a dataset's filters + charts so they survive the
app closing or the VM being recreated.

A view records which table it came from plus the current filters and
charts. Two durable, shareable backends — you pick where to store it:

  • Aurora  — a `_studio_views` row in a workspace database (queryable SQL).
  • S3      — a `_studio_views/<name>.json` object in a workspace storage
              folder (no writable DB needed; works for any datasource).

Browser per-tab state is lost when the app closes; a saved view isn't.
"""

import getpass
import json
import logging
import re
import subprocess

from sqlalchemy import (Column, DateTime, Engine, Integer, MetaData, Table,
                        Text, delete, func, insert, select)

import db

logger = logging.getLogger(__name__)

_SAFE_NAME = re.compile(r"^[A-Za-z0-9 ._-]{1,80}$")
VIEW_PREFIX = "_studio_views"

metadata = MetaData()
view_table = Table(
    "_studio_views", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", Text, nullable=False),
    Column("created_by", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("state", Text, nullable=False),  # JSON: {source, filters, charts}
)
_prepared: set[int] = set()
_actor_cache: str | None = None


def _validate(name: str):
    if not _SAFE_NAME.match(name):
        raise ValueError(
            "View name may use letters, digits, spaces, dot, dash, "
            "underscore (max 80 chars).")


def _actor() -> str:
    global _actor_cache
    if _actor_cache:
        return _actor_cache
    try:
        result = subprocess.run(["wb", "auth", "status", "--format", "json"],
                                capture_output=True, text=True, check=True,
                                timeout=10)
        _actor_cache = json.loads(result.stdout).get("userEmail") \
            or getpass.getuser()
    except Exception:
        _actor_cache = getpass.getuser()
    return _actor_cache


# ----------------------------------------------------------------- dispatch

def save_view(kind: str, resource_id: str, name: str, state: dict) -> dict:
    _validate(name)
    if kind == "aurora":
        _aurora_save(resource_id, name, state)
    elif kind == "s3":
        _s3_save(resource_id, name, state)
    else:
        raise ValueError(f"Views can be stored in Aurora or S3, not {kind}.")
    return {"name": name}


def list_views(kind: str, resource_id: str) -> list[dict]:
    if kind == "aurora":
        return _aurora_list(resource_id)
    if kind == "s3":
        return _s3_list(resource_id)
    raise ValueError(f"Views can be stored in Aurora or S3, not {kind}.")


def get_view(kind: str, resource_id: str, name: str) -> dict | None:
    _validate(name)
    if kind == "aurora":
        return _aurora_get(resource_id, name)
    if kind == "s3":
        return _s3_get(resource_id, name)
    raise ValueError(f"Views can be stored in Aurora or S3, not {kind}.")


def delete_view(kind: str, resource_id: str, name: str):
    _validate(name)
    if kind == "aurora":
        _aurora_delete(resource_id, name)
    elif kind == "s3":
        _s3_delete(resource_id, name)


# ------------------------------------------------------------------- Aurora

def _engine(resource_id: str) -> Engine:
    engine = db.get_engine_for_resource(resource_id)
    if id(engine) not in _prepared:
        metadata.create_all(engine)
        _prepared.add(id(engine))
    return engine


def _aurora_save(resource_id: str, name: str, state: dict):
    engine = _engine(resource_id)
    with engine.connect() as conn:
        conn.execute(delete(view_table).where(view_table.c.name == name))
        conn.execute(insert(view_table).values(
            name=name, created_by=_actor(), state=json.dumps(state)))
        conn.commit()


def _aurora_list(resource_id: str) -> list[dict]:
    engine = _engine(resource_id)
    query = (select(view_table.c.name, view_table.c.created_by,
                    view_table.c.created_at)
             .order_by(view_table.c.id.desc()))
    with engine.connect() as conn:
        return [{"name": r[0], "created_by": r[1],
                 "created_at": str(r[2]) if r[2] is not None else None}
                for r in conn.execute(query).fetchall()]


def _aurora_get(resource_id: str, name: str) -> dict | None:
    engine = _engine(resource_id)
    query = select(view_table.c.state).where(view_table.c.name == name)
    with engine.connect() as conn:
        row = conn.execute(query).fetchone()
    return json.loads(row[0]) if row else None


def _aurora_delete(resource_id: str, name: str):
    engine = _engine(resource_id)
    with engine.connect() as conn:
        conn.execute(delete(view_table).where(view_table.c.name == name))
        conn.commit()


# ----------------------------------------------------------------------- S3

def _s3_key(resource_id: str, name: str) -> str:
    return f"{db.resolve_s3_uri(resource_id)}/{VIEW_PREFIX}/{name}.json"


def _s3_save(resource_id: str, name: str, state: dict):
    payload = json.dumps({**state, "created_by": _actor()})
    out = subprocess.run(
        ["aws", "s3", "cp", "-", _s3_key(resource_id, name),
         "--profile", resource_id, "--content-type", "application/json"],
        input=payload, capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(
            (out.stderr or out.stdout or "").strip().split("\n")[-1])


def _s3_list(resource_id: str) -> list[dict]:
    uri = f"{db.resolve_s3_uri(resource_id)}/{VIEW_PREFIX}/"
    out = subprocess.run(["aws", "s3", "ls", uri, "--profile", resource_id],
                         capture_output=True, text=True, timeout=120)
    if out.returncode != 0:  # folder may not exist yet → no views
        return []
    names = []
    for line in out.stdout.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4 and parts[3].endswith(".json"):
            names.append({"name": parts[3][:-len(".json")],
                          "created_by": None, "created_at": None})
    return names


def _s3_get(resource_id: str, name: str) -> dict | None:
    out = subprocess.run(
        ["aws", "s3", "cp", _s3_key(resource_id, name), "-",
         "--profile", resource_id],
        capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        return None
    return json.loads(out.stdout)


def _s3_delete(resource_id: str, name: str):
    subprocess.run(
        ["aws", "s3", "rm", _s3_key(resource_id, name),
         "--profile", resource_id],
        capture_output=True, text=True, timeout=120)
