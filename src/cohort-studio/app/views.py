from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone
import getpass
import hashlib
import json
import logging
import re
import subprocess
import weakref
import cloud_cli
import threading
import time

from sqlalchemy import (Column, DateTime, Engine, Integer, MetaData, Table,
                        Text, UniqueConstraint, delete, func, insert, select)
from sqlalchemy.exc import IntegrityError

import database as db

logger = logging.getLogger(__name__)

_SAFE_NAME = re.compile(r"^[A-Za-z0-9 ._-]{1,80}$")
VIEW_PREFIX = "_studio_views"
REVISION_PREFIX = "_revisions"
MAX_REVISION = 999_999

metadata = MetaData()
view_table = Table(
    "_studio_views", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", Text, nullable=False),
    Column("created_by", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("state", Text, nullable=False),
)
revision_table = Table(
    "_studio_view_revisions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("view_name", Text, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=False),
    Column("published_by", Text),
    Column("note", Text),
    Column("state_hash", Text, nullable=False),
    Column("state", Text, nullable=False),
    UniqueConstraint("view_name", "revision", name="_studio_view_revisions_name_revision"),
)
# Weak references, not id(): a disposed engine's id can be reused.
_prepared: weakref.WeakSet[Engine] = weakref.WeakSet()
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
        result = cloud_cli.run(["wb", "auth", "status", "--format", "json"],
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
    invalidate_listing(kind, resource_id)
    return {"name": name}

def list_views(kind: str, resource_id: str) -> list[dict]:
    if kind == "aurora":
        return _aurora_list(resource_id)
    if kind == "s3":
        items = _s3_list(resource_id)
        try:
            return _s3_with_publication(resource_id, items)
        except Exception:
            logger.warning("S3 view revisions could not be listed for %s", resource_id,
                           exc_info=True)
            return [{**item, **_publication_status([], None), "publication_unknown": True}
                    for item in items]
    raise ValueError(f"Views can be stored in Aurora or S3, not {kind}.")

_LIST_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="saved-view-list")
_LIST_LOCK = threading.RLock()
_LIST_CACHE = {}
_LIST_PENDING = {}
_LIST_EPOCH = {}
LIST_DEADLINE_SECONDS = 0.25
LIST_CACHE_SECONDS = 300
LIST_FAILURE_CACHE_SECONDS = 20


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


def invalidate_listing(kind, resource_id):
    with _LIST_LOCK:
        key = (kind, resource_id)
        _LIST_CACHE.pop(key, None)
        _LIST_EPOCH[key] = _LIST_EPOCH.get(key, 0) + 1


def list_all_views(stores: list[dict]) -> dict:
    result = {"views": [], "unavailable": [], "pending": []}
    keys = {(s["kind"], s["resource_id"]) for s in stores}
    with _LIST_LOCK:
        for key in list(_LIST_CACHE):
            if key not in keys:
                _LIST_CACHE.pop(key, None)
        for store in stores:
            key = (store["kind"], store["resource_id"])
            cached = _LIST_CACHE.get(key)
            ttl = LIST_FAILURE_CACHE_SECONDS if cached and cached[1]["unavailable"] else LIST_CACHE_SECONDS
            if key in _LIST_PENDING or (cached and time.monotonic() - cached[0] < ttl):
                continue
            if len(_LIST_PENDING) >= 64:
                continue
            future = _LIST_POOL.submit(_list_store, store)
            _LIST_PENDING[key] = future
            def complete(done, key=key, epoch=_LIST_EPOCH.get(key, 0)):
                with _LIST_LOCK:
                    if epoch == _LIST_EPOCH.get(key, 0):
                        _LIST_CACHE[key] = (time.monotonic(), done.result())
                    _LIST_PENDING.pop(key, None)
            future.add_done_callback(complete)
        pending = list(_LIST_PENDING.values())
    if pending:
        wait(pending, timeout=LIST_DEADLINE_SECONDS)
    with _LIST_LOCK:
        for store in stores:
            key = (store["kind"], store["resource_id"])
            cached = _LIST_CACHE.get(key)
            if cached:
                result["views"].extend(cached[1]["views"])
                result["unavailable"].extend(cached[1]["unavailable"])
            if key in _LIST_PENDING or not cached:
                result["pending"].append(store)
    result["views"].sort(key=lambda item: (item["name"].casefold(), item["store_label"].casefold()))
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
        _s3_delete_revisions(resource_id, name)
        _s3_delete(resource_id, name)
    invalidate_listing(kind, resource_id)

class ViewNotFound(LookupError):
    pass


class RevisionNotFound(LookupError):
    pass


class RevisionConflict(RuntimeError):
    pass


def state_hash(state: dict) -> str:
    body = {key: value for key, value in state.items() if key != "created_by"}
    datasets = body.get("datasets")
    if isinstance(datasets, list):
        body["datasets"] = [{key: value for key, value in item.items() if key != "snapshot"}
                            if isinstance(item, dict) else item for item in datasets]
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _draft_state(state: dict) -> dict:
    return {key: value for key, value in state.items() if key != "created_by"}


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value)


def _revision_meta(name: str, revision: int, published_at, published_by, note) -> dict:
    return {"name": name, "revision": int(revision), "published_at": _iso(published_at),
            "published_by": published_by, "note": note}


def _publication_status(revisions: list[dict], draft_hash: str | None) -> dict:
    if not revisions:
        return {"published_revision": None, "published_at": None, "draft_changed": None}
    latest = max(revisions, key=lambda item: item["revision"])
    return {"published_revision": latest["revision"],
            "published_at": latest["published_at"],
            "draft_changed": draft_hash is not None and draft_hash != latest["state_hash"]}


def publish_view(kind: str, resource_id: str, name: str, note: str | None) -> dict:
    _validate(name)
    if kind == "aurora":
        result = _aurora_publish(resource_id, name, note)
    elif kind == "s3":
        result = _s3_publish(resource_id, name, note)
    else:
        raise ValueError(f"Views can be stored in Aurora or S3, not {kind}.")
    invalidate_listing(kind, resource_id)
    return result


def list_revisions(kind: str, resource_id: str, name: str) -> list[dict]:
    _validate(name)
    if kind == "aurora":
        rows = _aurora_revisions(resource_id, name)
    elif kind == "s3":
        rows = _s3_revisions(resource_id, name)
    else:
        raise ValueError(f"Views can be stored in Aurora or S3, not {kind}.")
    return sorted(rows, key=lambda item: item["revision"], reverse=True)


def get_revision(kind: str, resource_id: str, name: str,
                 revision: int | None = None) -> dict:
    _validate(name)
    if kind == "aurora":
        found = _aurora_get_revision(resource_id, name, revision)
    elif kind == "s3":
        found = _s3_get_revision(resource_id, name, revision)
    else:
        raise ValueError(f"Views can be stored in Aurora or S3, not {kind}.")
    if found is None:
        if revision is None:
            raise RevisionNotFound(f"View {name!r} has no published revision.")
        raise RevisionNotFound(f"Revision {revision} of view {name!r} was not found.")
    return found


def rollback_view(kind: str, resource_id: str, name: str, revision: int) -> dict:
    found = get_revision(kind, resource_id, name, revision)
    if kind == "aurora":
        engine = _engine(resource_id)
        if engine.dialect.name == "postgresql":
            from saved_snapshots import restore_state
            restore_state(resource_id, name, found["state"])
        else:
            with engine.begin() as conn:
                conn.execute(delete(view_table).where(view_table.c.name == name))
                conn.execute(insert(view_table).values(
                    name=name, created_by=_actor(), state=json.dumps(found["state"])))
    else:
        _s3_save(resource_id, name, found["state"])
    invalidate_listing(kind, resource_id)
    return {"name": name, "revision": found["revision"]}


def _engine(resource_id: str) -> Engine:
    engine = db.get_engine_for_resource(resource_id)
    if engine not in _prepared:
        metadata.create_all(engine)
        _prepared.add(engine)
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
        published: dict[str, list[dict]] = {}
        for rev in conn.execute(select(
                revision_table.c.view_name, revision_table.c.revision,
                revision_table.c.published_at, revision_table.c.state_hash)).fetchall():
            published.setdefault(rev[0], []).append(
                {"revision": rev[1], "published_at": _iso(rev[2]), "state_hash": rev[3]})
        for row in conn.execute(query).fetchall():
            state = json.loads(row[3])
            status = status_for(conn, resource_id, state) if status_for else {}
            output.append({"name": row[0], "created_by": row[1],
                           "created_at": str(row[2]) if row[2] is not None else None,
                           **status,
                           **_publication_status(published.get(row[0], []), state_hash(state))})
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
            conn.execute(delete(revision_table).where(revision_table.c.view_name == name))
            conn.execute(delete(view_table).where(view_table.c.name == name))
        return
    from saved_snapshots import delete_saved_view
    delete_saved_view(resource_id, name)

def _aurora_publish(resource_id: str, name: str, note: str | None) -> dict:
    engine = _engine(resource_id)
    published_at = datetime.now(timezone.utc)
    actor = _actor()
    try:
        with engine.begin() as conn:
            if engine.dialect.name == "postgresql":
                from saved_snapshots import _public_path, _resource_lock
                _resource_lock(conn, resource_id)
                _public_path(conn)
            raw = conn.execute(select(view_table.c.state)
                               .where(view_table.c.name == name)).scalar_one_or_none()
            if raw is None:
                raise ViewNotFound(f"View {name!r} not found.")
            state = _draft_state(json.loads(raw))
            current = conn.execute(select(func.max(revision_table.c.revision))
                                   .where(revision_table.c.view_name == name)).scalar()
            revision = (current or 0) + 1
            if revision > MAX_REVISION:
                raise RevisionConflict("This view has reached the revision limit.")
            conn.execute(insert(revision_table).values(
                view_name=name, revision=revision, published_at=published_at,
                published_by=actor, note=note, state_hash=state_hash(state),
                state=json.dumps(state)))
    except IntegrityError:
        raise RevisionConflict(
            "Another publish of this view finished first. Reload and try again.") from None
    return _revision_meta(name, revision, published_at, actor, note)


def _revision_columns():
    return (revision_table.c.revision, revision_table.c.published_at,
            revision_table.c.published_by, revision_table.c.note)


def _aurora_revisions(resource_id: str, name: str) -> list[dict]:
    engine = _engine(resource_id)
    with engine.connect() as conn:
        rows = conn.execute(select(*_revision_columns())
                            .where(revision_table.c.view_name == name)).fetchall()
    return [_revision_meta(name, *row) for row in rows]


def _aurora_get_revision(resource_id: str, name: str, revision: int | None) -> dict | None:
    engine = _engine(resource_id)
    query = select(*_revision_columns(), revision_table.c.state).where(
        revision_table.c.view_name == name)
    if revision is None:
        query = query.order_by(revision_table.c.revision.desc()).limit(1)
    else:
        query = query.where(revision_table.c.revision == revision)
    with engine.connect() as conn:
        row = conn.execute(query).fetchone()
    if row is None:
        return None
    return {**_revision_meta(name, *row[:4]), "state": json.loads(row[4])}


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
    out = cloud_cli.run(
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
        from botocore.config import Config
        client = boto3.Session(region_name=region).client("s3", region_name=region,
            config=Config(connect_timeout=5, read_timeout=10, retries={"total_max_attempts": 1}))
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
    from urllib.parse import urlsplit
    uri = urlsplit(db.resolve_s3_uri(resource_id))
    if uri.scheme != "s3" or not uri.netloc:
        raise ValueError("Invalid S3 resource URI")
    prefix = "/".join(part for part in (uri.path.strip("/"), VIEW_PREFIX) if part) + "/"
    out = cloud_cli.run(["aws", "s3api", "list-objects-v2",
                          "--bucket", uri.netloc, "--prefix", prefix, "--delimiter", "/",
                          "--profile", resource_id, "--output", "json",
                          "--cli-connect-timeout", "5", "--cli-read-timeout", "10"],
                         capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError("S3 saved views could not be listed. Check access and retry.")
    names = []
    for item in json.loads(out.stdout).get("Contents", []):
        key = item.get("Key", "")
        filename = key.removeprefix(prefix)
        if key.startswith(prefix) and filename.endswith(".json") and "/" not in filename:
            names.append({"name": filename[:-5], "created_by": None,
                          "created_at": item.get("LastModified")})
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
    out = cloud_cli.run(
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
    cloud_cli.run(
        ["aws", "s3", "rm", _s3_key(resource_id, name),
         "--profile", resource_id],
        capture_output=True, text=True, timeout=120)


def _s3_revision_root(resource_id: str) -> dict:
    registered = _registered_s3_view_location(resource_id, "")
    if registered is not None:
        bucket, _, key_prefix, region = registered
        return {"bucket": bucket, "prefix": f"{key_prefix}{REVISION_PREFIX}/",
                "region": region, "profile": None}
    from urllib.parse import urlsplit
    uri = urlsplit(db.resolve_s3_uri(resource_id))
    if uri.scheme != "s3" or not uri.netloc:
        raise ValueError("Invalid S3 resource URI")
    prefix = "/".join(part for part in (uri.path.strip("/"), VIEW_PREFIX, REVISION_PREFIX)
                      if part) + "/"
    return {"bucket": uri.netloc, "prefix": prefix, "region": None, "profile": resource_id}


def _s3_client(root: dict):
    import boto3
    return boto3.Session(region_name=root["region"]).client(
        "s3", region_name=root["region"])


def _s3_list_keys(root: dict, prefix: str) -> list[str]:
    if root["profile"] is None:
        paginator = _s3_client(root).get_paginator("list_objects_v2")
        return [item.get("Key", "") for page in paginator.paginate(
            Bucket=root["bucket"], Prefix=prefix) for item in page.get("Contents", [])]
    out = cloud_cli.run(["aws", "s3api", "list-objects-v2", "--bucket", root["bucket"],
                         "--prefix", prefix, "--profile", root["profile"], "--output", "json",
                         "--cli-connect-timeout", "5", "--cli-read-timeout", "10"],
                        capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError("S3 view revisions could not be listed. Check access and retry.")
    return [item.get("Key", "") for item in json.loads(out.stdout or "{}").get("Contents") or []]


def _s3_revision_numbers(root: dict, name: str | None = None) -> dict[str, list[int]]:
    prefix = root["prefix"] + (f"{name}/" if name is not None else "")
    found: dict[str, list[int]] = {}
    for key in _s3_list_keys(root, prefix):
        if not key.startswith(prefix):
            continue
        parts = key[len(root["prefix"]):].split("/")
        if (len(parts) == 2 and len(parts[1]) == 11 and parts[1].endswith(".json")
                and parts[1][:6].isdigit()):
            found.setdefault(parts[0], []).append(int(parts[1][:6]))
    return found


def _s3_revision_key(root: dict, name: str, revision: int) -> str:
    return f"{root['prefix']}{name}/{revision:06d}.json"


def _s3_read_object(root: dict, key: str) -> dict | None:
    if root["profile"] is None:
        try:
            response = _s3_client(root).get_object(Bucket=root["bucket"], Key=key)
            return json.loads(response["Body"].read())
        except Exception as exc:
            code = getattr(exc, "response", {}).get("Error", {}).get("Code")
            if code in {"NoSuchKey", "NotFound", "404"}:
                return None
            raise RuntimeError("S3 view revision could not be read.") from None
    out = cloud_cli.run(["aws", "s3", "cp", f"s3://{root['bucket']}/{key}", "-",
                         "--profile", root["profile"]],
                        capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        return None
    return json.loads(out.stdout)


def _s3_create_object(root: dict, key: str, payload: str) -> None:
    conflict = RevisionConflict(
        "Another publish of this view finished first. Reload and try again.")
    if root["profile"] is None:
        try:
            _s3_client(root).put_object(
                Bucket=root["bucket"], Key=key, Body=payload.encode("utf-8"),
                ContentType="application/json", IfNoneMatch="*")
        except Exception as exc:
            code = getattr(exc, "response", {}).get("Error", {}).get("Code")
            if code in {"PreconditionFailed", "ConditionalRequestConflict", "412", "409"}:
                raise conflict from None
            raise RuntimeError("S3 view revision could not be written.") from None
        return
    import os
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        handle.write(payload)
        body = handle.name
    try:
        out = cloud_cli.run(["aws", "s3api", "put-object", "--bucket", root["bucket"],
                             "--key", key, "--body", body,
                             "--content-type", "application/json",
                             "--if-none-match", "*", "--profile", root["profile"]],
                            capture_output=True, text=True, timeout=120)
    finally:
        os.unlink(body)
    if out.returncode != 0:
        message = out.stderr or out.stdout or ""
        if "PreconditionFailed" in message or "ConditionalRequestConflict" in message:
            raise conflict
        raise RuntimeError("S3 view revision could not be written.")


def _s3_publish(resource_id: str, name: str, note: str | None) -> dict:
    draft = _s3_get(resource_id, name)
    if draft is None:
        raise ViewNotFound(f"View {name!r} not found.")
    state = _draft_state(draft)
    root = _s3_revision_root(resource_id)
    revision = max(_s3_revision_numbers(root, name).get(name, [0])) + 1
    if revision > MAX_REVISION:
        raise RevisionConflict("This view has reached the revision limit.")
    meta = _revision_meta(name, revision, datetime.now(timezone.utc), _actor(), note)
    _s3_create_object(root, _s3_revision_key(root, name, revision), json.dumps({
        **{key: meta[key] for key in ("revision", "published_at", "published_by", "note")},
        "state_hash": state_hash(state), "state": state}))
    return meta


def _s3_revision_meta(name: str, body: dict) -> dict:
    return _revision_meta(name, body["revision"], body.get("published_at"),
                          body.get("published_by"), body.get("note"))


def _s3_get_revision(resource_id: str, name: str, revision: int | None) -> dict | None:
    root = _s3_revision_root(resource_id)
    if revision is None:
        numbers = _s3_revision_numbers(root, name).get(name, [])
        if not numbers:
            return None
        revision = max(numbers)
    body = _s3_read_object(root, _s3_revision_key(root, name, revision))
    if body is None:
        return None
    return {**_s3_revision_meta(name, body), "state": body["state"]}


def _s3_revisions(resource_id: str, name: str) -> list[dict]:
    root = _s3_revision_root(resource_id)
    output = []
    for revision in _s3_revision_numbers(root, name).get(name, []):
        body = _s3_read_object(root, _s3_revision_key(root, name, revision))
        if body is not None:
            output.append(_s3_revision_meta(name, body))
    return output


def _s3_with_publication(resource_id: str, items: list[dict]) -> list[dict]:
    root = _s3_revision_root(resource_id)
    numbers = _s3_revision_numbers(root)
    for item in items:
        revisions = numbers.get(item["name"])
        latest = (_s3_read_object(root, _s3_revision_key(root, item["name"], max(revisions)))
                  if revisions else None)
        if latest is None:
            item.update(_publication_status([], None))
            continue
        draft = _s3_get(resource_id, item["name"])
        item.update(_publication_status(
            [{"revision": latest["revision"], "published_at": latest.get("published_at"),
              "state_hash": latest.get("state_hash")}],
            state_hash(draft) if draft is not None else None))
    return items


def _s3_delete_revisions(resource_id: str, name: str) -> None:
    root = _s3_revision_root(resource_id)
    keys = [_s3_revision_key(root, name, revision)
            for revision in _s3_revision_numbers(root, name).get(name, [])]
    if root["profile"] is None:
        client = _s3_client(root)
        for key in keys:
            client.delete_object(Bucket=root["bucket"], Key=key)
        return
    for key in keys:
        cloud_cli.run(["aws", "s3", "rm", f"s3://{root['bucket']}/{key}",
                       "--profile", root["profile"]],
                      capture_output=True, text=True, timeout=120)
