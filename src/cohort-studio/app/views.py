from concurrent.futures import ThreadPoolExecutor
import getpass
import json
import logging
import re
import subprocess

from sqlalchemy import (Column, DateTime, Engine, Integer, MetaData, Table,
                        Text, delete, func, insert, select)

import database as db

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
    Column("state", Text, nullable=False),
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

def save_view(kind: str, resource_id: str, name: str, state: dict) -> dict:
    _validate(name)
    if kind == "aurora":
        _aurora_save(resource_id, name, state)
    elif kind == "s3":
        from saved_snapshots import portable_recipe_state
        _s3_save(resource_id, name, portable_recipe_state(state))
    else:
        raise ValueError(f"Views can be stored in Aurora or S3, not {kind}.")
    return {"name": name}

def list_views(kind: str, resource_id: str) -> list[dict]:
    if kind == "aurora":
        return _aurora_list(resource_id)
    if kind == "s3":
        return _s3_list(resource_id)
    raise ValueError(f"Views can be stored in Aurora or S3, not {kind}.")

_LIST_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="saved-view-list")


def _list_store(store):
    try:
        items = list_views(store["kind"], store["resource_id"])
        return {"views": [{**item, "kind": store["kind"],
                           "resource_id": store["resource_id"], "store_label": store["label"],
                           "materialized_sources": item.get("materialized_sources", 0),
                           "refreshed_at": item.get("refreshed_at")} for item in items],
                "unavailable": []}
    except Exception as exc:
        return {"views": [], "unavailable": [{**store,
                "error": str(exc).split("\n")[0][:300] or "Saved views could not be listed."}]}


def list_all_views(stores: list[dict]) -> dict:
    result = {"views": [], "unavailable": []}
    for offset in range(0, len(stores), 4):
        pending = [_LIST_POOL.submit(_list_store, store) for store in stores[offset:offset + 4]]
        for future in pending:
            value = future.result()
            result["views"].extend(value["views"])
            result["unavailable"].extend(value["unavailable"])
    result["views"].sort(key=lambda item: (item["name"].casefold(),
                                             item["store_label"].casefold()))
    return result


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

def _engine(resource_id: str) -> Engine:
    engine = db.get_engine_for_resource(resource_id)
    if id(engine) not in _prepared:
        metadata.create_all(engine)
        _prepared.add(id(engine))
    return engine

def _aurora_save(resource_id: str, name: str, state: dict):
    engine = _engine(resource_id)
    if engine.dialect.name != "postgresql":
        with engine.begin() as conn:
            conn.execute(delete(view_table).where(view_table.c.name == name))
            conn.execute(insert(view_table).values(
                name=name, created_by=_actor(), state=json.dumps(state)))
        return
    from saved_snapshots import replace_recipe
    replace_recipe(resource_id, name, state)

def _aurora_list(resource_id: str) -> list[dict]:
    engine = _engine(resource_id)
    query = (select(view_table.c.name, view_table.c.created_by,
                    view_table.c.created_at, view_table.c.state)
             .order_by(view_table.c.id.desc()))
    with engine.connect() as conn:
        output = []
        status_for = None
        if engine.dialect.name == "postgresql":
            from saved_snapshots import list_status
            status_for = list_status
        for row in conn.execute(query).fetchall():
            state = json.loads(row[3])
            status = status_for(conn, resource_id, state) if status_for else {}
            output.append({"name": row[0], "created_by": row[1],
                           "created_at": str(row[2]) if row[2] is not None else None,
                           **status})
        return output

def _aurora_get(resource_id: str, name: str) -> dict | None:
    engine = _engine(resource_id)
    query = select(view_table.c.state).where(view_table.c.name == name)
    with engine.connect() as conn:
        row = conn.execute(query).fetchone()
    return json.loads(row[0]) if row else None

def _aurora_delete(resource_id: str, name: str):
    engine = _engine(resource_id)
    if engine.dialect.name != "postgresql":
        with engine.begin() as conn:
            conn.execute(delete(view_table).where(view_table.c.name == name))
        return
    from saved_snapshots import delete_saved_view
    delete_saved_view(resource_id, name)

def _s3_key(resource_id: str, name: str) -> str:
    return f"{db.resolve_s3_uri(resource_id)}/{VIEW_PREFIX}/{name}.json"

def _registered_s3_view_location(resource_id: str, name: str):
    import source_registry

    location = source_registry.s3_location(resource_id)
    if location is None:
        return None
    _, region, prefix = location
    registration = source_registry.get("s3", resource_id.removeprefix("s3:"))
    if registration is None:
        raise ValueError("Registered S3 datasource was not found.")
    key_prefix = f"{prefix.rstrip('/')}/{VIEW_PREFIX}/" if prefix else f"{VIEW_PREFIX}/"
    return registration["bucket"], f"{key_prefix}{name}.json", key_prefix, region

def _s3_save(resource_id: str, name: str, state: dict):
    payload = json.dumps({**state, "created_by": _actor()})
    registered = _registered_s3_view_location(resource_id, name)
    if registered is not None:
        import boto3
        bucket, key, _, region = registered
        boto3.Session(region_name=region).client("s3", region_name=region).put_object(
            Bucket=bucket, Key=key, Body=payload.encode("utf-8"),
            ContentType="application/json")
        return
    out = subprocess.run(
        ["aws", "s3", "cp", "-", _s3_key(resource_id, name),
         "--profile", resource_id, "--content-type", "application/json"],
        input=payload, capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(
            (out.stderr or out.stdout or "").strip().split("\n")[-1])

def _s3_list(resource_id: str) -> list[dict]:
    registered = _registered_s3_view_location(resource_id, "")
    if registered is not None:
        import boto3
        bucket, _, prefix, region = registered
        client = boto3.Session(region_name=region).client("s3", region_name=region)
        paginator = client.get_paginator("list_objects_v2")
        names = []
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for item in page.get("Contents", []):
                key = item.get("Key", "")
                filename = key.removeprefix(prefix)
                if filename.endswith(".json") and "/" not in filename:
                    names.append({"name": filename[:-5], "created_by": None,
                                  "created_at": (item.get("LastModified").isoformat()
                                                 if item.get("LastModified") else None)})
        return names
    uri = f"{db.resolve_s3_uri(resource_id)}/{VIEW_PREFIX}/"
    out = subprocess.run(["aws", "s3", "ls", uri, "--profile", resource_id],
                         capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        return []
    names = []
    for line in out.stdout.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4 and parts[3].endswith(".json"):
            names.append({"name": parts[3][:-len(".json")],
                          "created_by": None, "created_at": None})
    return names

def _s3_get(resource_id: str, name: str) -> dict | None:
    registered = _registered_s3_view_location(resource_id, name)
    if registered is not None:
        import boto3
        bucket, key, _, region = registered
        try:
            response = boto3.Session(region_name=region).client(
                "s3", region_name=region).get_object(Bucket=bucket, Key=key)
            return json.loads(response["Body"].read())
        except Exception as exc:
            code = getattr(exc, "response", {}).get("Error", {}).get("Code")
            if code in {"NoSuchKey", "NotFound", "404"}:
                return None
            raise RuntimeError("Registered S3 view could not be read.") from None
    out = subprocess.run(
        ["aws", "s3", "cp", _s3_key(resource_id, name), "-",
         "--profile", resource_id],
        capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        return None
    return json.loads(out.stdout)

def _s3_delete(resource_id: str, name: str):
    registered = _registered_s3_view_location(resource_id, name)
    if registered is not None:
        import boto3
        bucket, key, _, region = registered
        boto3.Session(region_name=region).client("s3", region_name=region).delete_object(
            Bucket=bucket, Key=key)
        return
    subprocess.run(
        ["aws", "s3", "rm", _s3_key(resource_id, name),
         "--profile", resource_id],
        capture_output=True, text=True, timeout=120)
