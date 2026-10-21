import logging
import os
import posixpath
import re
import subprocess
import tempfile
import threading
import time

import duckdb
import pandas as pd

import db
import duck
from cache import ttl_cache

logger = logging.getLogger(__name__)

ALIAS = "cat"
CATALOG_PREFIX = "_catalog"

SKIP_PREFIXES = (CATALOG_PREFIX + "/", "_studio_views/")
DISCOVERY_WAIT_S = 2.0
DISCOVERY_TTL = 300

_VIEW_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_CATALOG_NAME = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
_HIVE_SEGMENT = re.compile(r"^[^=/]+=[^/]*$")
_URL = re.compile(r"(?:s3|gs|https?)://[^\s'\"]+")
_QUOTED_PATH = re.compile(r"'([^']*/[^']*)'")

class UnknownView(ValueError):
    pass

def _first_line(e: Exception) -> str:
    return str(e).split("\n")[0][:300]

def configured_urls() -> list[str]:
    raw = os.environ.get("STUDIO_CATALOG_URLS", "")
    return [u.strip() for u in raw.split(",")
            if u.strip().startswith("https://")]

def resolve(catalog_id: str) -> tuple[str, str | None]:

    if catalog_id.startswith("https://"):
        if catalog_id not in configured_urls():
            raise ValueError("Catalog URL is not listed in STUDIO_CATALOG_URLS.")
        return catalog_id, None
    resource_id, _, path = catalog_id.partition("/")
    if not resource_id or not path.lower().endswith(duck.CATALOG_SUFFIX):
        raise ValueError(f"Not a catalog id: {catalog_id!r}")
    return f"{db.resolve_s3_uri(resource_id)}/{path}", resource_id

def _check_uri(uri: str):
    if not duck._SAFE_KEY.match(re.sub(r"^(s3|https?)://", "", uri)):
        raise ValueError(f"Unsupported characters in path: {uri!r}")

def _quote(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'

def _attach(uri: str, profile: str | None) -> duckdb.DuckDBPyConnection:
    _check_uri(uri)
    con = duck._connect(profile)
    try:
        if profile is None and "://" in uri:
            con.execute("INSTALL httpfs; LOAD httpfs;")
        con.execute(f"ATTACH '{uri}' AS {ALIAS} (READ_ONLY)")
    except Exception:
        con.close()
        raise
    return con

def _objects(con) -> list[dict]:
    rows = con.execute(
        "SELECT schema_name, view_name, 'view', sql FROM duckdb_views() "
        "WHERE database_name = ? AND NOT internal "
        "UNION ALL "
        "SELECT schema_name, table_name, 'table', NULL FROM duckdb_tables() "
        "WHERE database_name = ? ORDER BY 1, 2", [ALIAS, ALIAS]).fetchall()
    return [{"name": name if schema == "main" else f"{schema}.{name}",
             "schema": schema, "object": name, "kind": kind, "sql": sql}
            for schema, name, kind, sql in rows]

def _source_error(view: str, sql: str, err: Exception) -> RuntimeError:

    hit = _URL.search(str(err))
    if hit:
        source = hit.group(0)
    else:
        source = ", ".join(sorted(set(_QUOTED_PATH.findall(sql)))) or "unknown"
    return RuntimeError(f"Catalog view {view!r} could not read {source} — "
                        f"{_first_line(err)}")

def list_objects(uri: str, profile: str | None = None) -> list[dict]:

    con = _attach(uri, profile)
    try:
        return _objects(con)
    finally:
        con.close()

def fetch_view(uri: str, view: str, cap: int,
               profile: str | None = None) -> pd.DataFrame:
    con = _attach(uri, profile)
    try:
        obj = next((o for o in _objects(con) if o["name"] == view), None)
        if obj is None:
            raise UnknownView(f"{view!r} is not a view in this catalog.")
        ref = f"{ALIAS}.{_quote(obj['schema'])}.{_quote(obj['object'])}"
        try:
            return con.execute(f"SELECT * FROM {ref} LIMIT {int(cap)}").df()
        except duckdb.Error as e:
            raise _source_error(view, obj["sql"] or "", e) from e
    finally:
        con.close()

@ttl_cache(ttl=300)
def list_catalog(catalog_id: str) -> list[dict]:
    uri, profile = resolve(catalog_id)
    return list_objects(uri, profile)

@ttl_cache(ttl=600, maxsize=4)
def fetch_catalog_view(catalog_id: str, view: str, cap: int) -> pd.DataFrame:

    uri, profile = resolve(catalog_id)
    return fetch_view(uri, view, cap, profile)

_found: dict[str, tuple[float, list[str]]] = {}
_inflight: dict[str, threading.Thread] = {}
_lock = threading.Lock()

def _discover_one(resource_id: str):
    try:
        paths = duck.list_s3_catalogs(resource_id)
    except Exception as e:
        logger.warning("Catalog discovery failed for %s: %s", resource_id, e)
        paths = []
    with _lock:
        _found[resource_id] = (time.monotonic() + DISCOVERY_TTL, paths)
        _inflight.pop(resource_id, None)

def discover(folder_ids: list[str],
             wait: float | None = None) -> tuple[list[dict], bool]:

    wait = DISCOVERY_WAIT_S if wait is None else wait
    now = time.monotonic()
    threads = []
    with _lock:
        for rid in folder_ids:
            hit = _found.get(rid)
            if hit and hit[0] > now:
                continue
            thread = _inflight.get(rid)
            if thread is None:
                thread = threading.Thread(target=_discover_one, args=(rid,),
                                          daemon=True)
                _inflight[rid] = thread
                thread.start()
            if hit is None:
                threads.append(thread)
    deadline = now + wait
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))
    sources, pending = [], False
    with _lock:
        for rid in folder_ids:
            hit = _found.get(rid)
            if hit is None:
                pending = True
                continue
            for path in hit[1]:
                cid = f"{rid}/{path}"
                sources.append({"kind": "catalog", "id": cid,
                                "label": f"{cid} · Catalog"})
    for url in configured_urls():
        sources.append({"kind": "catalog", "id": url,
                        "label": f"{posixpath.basename(url)} · Catalog"})
    return sources, pending

def invalidate(resource_id: str | None = None):
    duck._s3_ls.invalidate()
    duck.list_s3_files.invalidate()
    list_catalog.invalidate()
    fetch_catalog_view.invalidate()
    with _lock:
        if resource_id is None:
            _found.clear()
        else:
            _found.pop(resource_id, None)

def _sanitize(stem: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]+", "_", stem).strip("_").lower()
    if not name or name[0].isdigit():
        name = f"v_{name}"
    return name[:63]

def _unique(name: str, used: set[str]) -> str:
    candidate, n = name, 2
    while candidate in used:
        suffix = f"_{n}"
        candidate = name[:63 - len(suffix)] + suffix
        n += 1
    used.add(candidate)
    return candidate

def plan_views(files: list[str], base: str,
               reserved: set[str] = frozenset()) -> tuple[list, list]:

    groups: set[tuple[str, int, str]] = set()
    for f in files:
        if f.startswith(SKIP_PREFIXES):
            continue
        dirs = f.split("/")[:-1]
        depth = 0
        while dirs and _HIVE_SEGMENT.match(dirs[-1]):
            dirs.pop()
            depth += 1
        ext = posixpath.splitext(f)[1].lower()
        groups.add(("/".join(dirs), depth, ext) if depth else (f, 0, ext))

    used, views, skipped = set(reserved), [], []
    for root, depth, ext in sorted(groups):
        if depth:
            pattern = "/".join(
                [p for p in [root] if p] + ["*=*"] * depth + [f"*{ext}"])
            uri, stem = f"{base}/{pattern}", root or "partitioned"
        else:
            uri, stem = f"{base}/{root}", posixpath.splitext(root)[0]
        try:
            reader = duck._reader_sql(uri, hive=bool(depth))
        except ValueError as e:
            skipped.append({"name": root, "error": str(e)})
            continue
        views.append((_unique(_sanitize(stem), used),
                      f"SELECT * FROM {reader}"))
    return views, skipped

def select_sql(sql: str) -> str:

    try:
        statements = duckdb.extract_statements(sql)
    except duckdb.Error as e:
        raise ValueError(f"Invalid SQL: {_first_line(e)}") from e
    if len(statements) != 1 \
            or statements[0].type != duckdb.StatementType.SELECT:
        raise ValueError("View SQL must be a single SELECT statement.")
    return statements[0].query.strip().rstrip(";").strip()

def verify_views_only(path: str) -> int:

    _check_uri(path)
    con = duckdb.connect()
    try:
        con.execute(f"ATTACH '{path}' AS {ALIAS} (READ_ONLY)")
        objects = _objects(con)
    finally:
        con.close()
    tables = [o["name"] for o in objects if o["kind"] == "table"]
    if tables:
        raise RuntimeError(f"Catalog must hold only views; found table(s) "
                           f"{', '.join(tables)}.")
    return len(objects)

def build_catalog_file(path: str, views: list[tuple[str, str]],
                       profile: str | None = None,
                       strict: set[str] = frozenset()) -> dict:

    _check_uri(path)
    con = duck._connect(profile)
    created, skipped = [], []
    try:
        con.execute(f"ATTACH '{path}' AS {ALIAS}")
        con.execute(f"USE {ALIAS}")
        for name, sql in views:
            try:
                con.execute(f"CREATE OR REPLACE VIEW {_quote(name)} AS {sql}")
                created.append(name)
            except duckdb.Error as e:
                if name in strict:
                    raise ValueError(
                        f"View {name!r}: {_first_line(e)}") from e
                skipped.append({"name": name, "error": _first_line(e)})
        con.execute("USE memory")
        con.execute(f"DETACH {ALIAS}")
    finally:
        con.close()
    if verify_views_only(path) != len(created):
        raise RuntimeError("Catalog view count does not match what was built.")
    return {"views": created, "skipped": skipped}

def _upload(local: str, target: str, profile: str):
    out = subprocess.run(
        ["aws", "s3", "cp", local, target, "--profile", profile,
         "--content-type", "application/octet-stream"],
        capture_output=True, text=True, timeout=300)
    if out.returncode != 0:
        detail = (out.stderr or out.stdout or "").strip().split("\n")[-1]
        raise RuntimeError(f"aws s3 cp failed: {detail or 'exit 1'}")

def publish(resource_id: str, name: str,
            extra_views: list[tuple[str, str]] = (),
            include_files: bool = True) -> dict:

    name = name.strip().removesuffix(duck.CATALOG_SUFFIX)
    if not _CATALOG_NAME.match(name):
        raise ValueError("Catalog name may use letters, digits, dot, dash, "
                         "underscore (max 80 chars).")
    user = []
    for view_name, sql in extra_views:
        if not _VIEW_NAME.match(view_name):
            raise ValueError(f"Invalid view name {view_name!r}: use letters, "
                             "digits, underscore; start with a letter.")
        if view_name in {n for n, _ in user}:
            raise ValueError(f"Duplicate view name {view_name!r}.")
        user.append((view_name, select_sql(sql)))

    base = db.resolve_s3_uri(resource_id)
    planned, skipped = [], []
    if include_files:
        invalidate(resource_id)
        planned, skipped = plan_views(duck.list_s3_files(resource_id), base,
                                      reserved={n for n, _ in user})
    if not planned and not user:
        raise ValueError("Nothing to publish: no data files in this folder "
                         "and no custom views.")

    key = f"{CATALOG_PREFIX}/{name}{duck.CATALOG_SUFFIX}"
    target = f"{base}/{key}"
    with tempfile.TemporaryDirectory() as tmp:
        local = os.path.join(tmp, f"{name}{duck.CATALOG_SUFFIX}")
        built = build_catalog_file(local, planned + user, profile=resource_id,
                                   strict={n for n, _ in user})
        if not built["views"]:
            first = (skipped + built["skipped"])[0]["error"]
            raise RuntimeError(f"No view could be created: {first}")
        size = os.path.getsize(local)
        _upload(local, target, resource_id)
    invalidate(resource_id)
    return {"catalog_id": f"{resource_id}/{key}", "uri": target,
            "views": built["views"], "skipped": skipped + built["skipped"],
            "bytes": size}
