from __future__ import annotations

import math
import query_cancellation
from decimal import Decimal
from functools import wraps
import os
import json
import re
import shutil
import tempfile
import threading
import uuid
import urllib.request
import fnmatch
import glob
from pathlib import Path
from urllib.parse import urlsplit

import duckdb
import pandas as pd
import sqlglot
from sqlglot import exp

import category_text
import duck
import database as db
import filter_rules
from sql_utils import statement as text

MAX_OPERATION_BYTES = 1_000_000_000_000
LARGE_OPERATION_BYTES = 10_000_000_000
PAGE_SIZE_MAX = 1000
_BATCH_ROWS = 2048
_ROOT = Path(tempfile.gettempdir()) / "cohort-studio-disk"
_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
_LOCK = threading.RLock()
_MATERIALIZATIONS = threading.BoundedSemaphore(2)
_MIN_FREE_BYTES = 1_000_000_000


class OperationTooLarge(ValueError):
    pass


class SourceSizeUnknown(ValueError):
    pass


_COMPILED_SOURCE_TOKEN = object()


class CompiledSourceQuery(dict):
    __slots__ = ("source_ref",)

    def __init__(self, values: dict, source_ref: dict, token=None):
        if token is not _COMPILED_SOURCE_TOKEN:
            raise TypeError("Compiled source queries are created by source compilers.")
        self.source_ref = source_ref
        super().__init__(values)

    def with_metadata(self, **metadata):
        return CompiledSourceQuery({**self, **metadata}, self.source_ref,
                                   _COMPILED_SOURCE_TOKEN)


def _contains_omop_cohort(ref: dict) -> bool:
    if ref["kind"] == "omop_cohort":
        return True
    if ref["kind"] == "join":
        return (_contains_omop_cohort(ref["base"])
                or any(_contains_omop_cohort(step["source"])
                       for step in ref["steps"]))
    if ref["kind"] in {"derived", "group_summary"}:
        return _contains_omop_cohort(ref["base"])
    return False


def _requires_compiler_trust(ref: dict) -> bool:
    if ref["kind"] == "materialized":
        return True
    if ref["kind"] == "join":
        return (_requires_compiler_trust(ref["base"])
                or any(_requires_compiler_trust(step["source"]) for step in ref["steps"]))
    if ref["kind"] == "derived":
        return True
    return _contains_omop_cohort(ref)


def _compiled_source_query(source_ref: dict, live_source: dict) -> CompiledSourceQuery:
    from source_models import source_dict

    ref = source_dict(source_ref)
    if not _requires_compiler_trust(ref):
        raise ValueError("Only private source compiler output can use this query type.")
    resources = set()

    def collect(node):
        if "resource_id" in node:
            resources.add(node["resource_id"])
        if node["kind"] == "join":
            collect(node["base"])
            for step in node["steps"]:
                collect(step["source"])
        elif node["kind"] in {"derived", "group_summary"}:
            collect(node["base"])

    collect(ref)
    if resources != {live_source.get("resource_id")}:
        raise ValueError("OMOP cohort compiled queries must use one matching resource.")
    if not isinstance(live_source.get("sql"), str) or not isinstance(
            live_source.get("columns"), dict):
        raise ValueError("Compiled source query is incomplete.")
    if len(live_source["sql"]) > 100_000:
        raise ValueError("Calculated source query is too complex.")
    return CompiledSourceQuery(live_source, ref, _COMPILED_SOURCE_TOKEN)


def _compiled_omop_query(source_ref: dict, live_source: dict) -> CompiledSourceQuery:
    if not _contains_omop_cohort(source_ref):
        raise ValueError("Only OMOP cohort compiler output can use this query type.")
    return _compiled_source_query(source_ref, live_source)


def _q(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _lit(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _check_disk_space():
    if shutil.disk_usage(_ROOT).free < _MIN_FREE_BYTES:
        raise OperationTooLarge(
            "Local storage has less than 1 GB free. Remove unused datasets and retry.")


def _bounded_materialization(operation):
    @wraps(operation)
    def run(*args, **kwargs):
        if not _MATERIALIZATIONS.acquire(blocking=False):
            raise OperationTooLarge(
                "Two data operations are already writing local storage. Wait and retry.")
        try:
            _check_disk_space()
            return operation(*args, **kwargs)
        finally:
            _MATERIALIZATIONS.release()
    return run


def _new_path() -> str:
    _check_disk_space()
    fd, path = tempfile.mkstemp(prefix="dataset-", suffix=".duckdb", dir=_ROOT)
    os.close(fd)
    os.remove(path)
    return path


def _configure(con, temp_directory: str | Path | None = None):
    try:
        con.execute("SET memory_limit = '2GB'")
        con.execute("SET TimeZone = 'UTC'")
        con.execute(f"SET temp_directory = {_lit(str(temp_directory or _ROOT))}")
        con.execute(f"SET max_temp_directory_size = '{MAX_OPERATION_BYTES}B'")
        return con
    except Exception:
        con.close()
        raise


def _connect(path: str, read_only: bool = False):
    return _configure(duckdb.connect(path, read_only=read_only), path + ".tmp")


def remove(source: dict | None):
    if not source:
        return
    path = source.get("path")
    if isinstance(path, str) and path.startswith(str(_ROOT) + os.sep):
        for suffix in ("", ".wal"):
            try:
                os.remove(path + suffix)
            except FileNotFoundError:
                pass
        shutil.rmtree(path + ".tmp", ignore_errors=True)


def remove_file(path: str):
    remove({"path": path})


def _budget(estimated_bytes: int, materialized_bytes: int = 0):
    estimate = int(estimated_bytes) + int(materialized_bytes)
    if estimate > MAX_OPERATION_BYTES:
        raise OperationTooLarge(
            "This operation is estimated to scan or materialize more than 1 TB. "
            "Reduce the source or split the work before opening it.")
    return estimate


def _actual_budget(total: int):
    _check_disk_space()
    if total > MAX_OPERATION_BYTES:
        raise OperationTooLarge(
            "This operation reached the 1 TB scan or materialization limit and was stopped.")


def _validate_relative_key(filename: str) -> str:
    if (not isinstance(filename, str) or not filename or filename.startswith("/")
            or "\\" in filename or ":" in filename):
        raise ValueError("S3 file path must be relative to its configured folder.")
    parts = filename.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("S3 file path cannot contain empty or parent path segments.")
    if not filename.lower().endswith(duck.DATA_SUFFIXES) or not duck._SAFE_KEY.match(filename):
        raise ValueError("S3 path must name a supported data file.")
    return filename


def _has_hive_path(uri: str) -> bool:
    path = urlsplit(uri).path.rstrip("/")
    return any("=" in part for part in path.split("/")[:-1])


def _s3_client(resource_id: str, filename: str):
    import boto3
    import source_registry

    location = source_registry.s3_location(resource_id)
    if location is not None:
        base, region, _ = location
        source = source_registry.get("s3", resource_id.removeprefix("s3:"))
        if source is None:
            raise ValueError("Registered S3 datasource was not found.")
        bucket = source["bucket"]
        key = "/".join(part for part in (source.get("prefix", ""), filename) if part)
        session = boto3.Session(region_name=region)
        return session.client("s3", region_name=region), bucket, key, base.rstrip("/") + "/" + filename, region, True
    uri = db.resolve_s3_uri(resource_id).rstrip("/") + "/" + filename
    parsed = urlsplit(uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError("S3 resource did not resolve to an S3 object.")
    key = parsed.path.lstrip("/")
    session = boto3.Session(profile_name=resource_id, region_name=duck.DEFAULT_REGION)
    return session.client("s3"), parsed.netloc, key, uri, duck.DEFAULT_REGION, False


def _object_size(resource_id: str, filename: str) -> tuple[int, str, str, bool]:
    filename = duck._validate_relative_key(filename)
    client, bucket, key, uri, region, app_credentials = _s3_client(resource_id, filename)
    try:
        size = int(client.head_object(Bucket=bucket, Key=key)["ContentLength"])
    except Exception as exc:
        raise SourceSizeUnknown(
            "The S3 object size could not be checked, so Studio cannot safely load it.") from exc
    if size < 0:
        raise SourceSizeUnknown("The S3 object size is not available.")
    _budget(size, size)
    return size, uri, region, app_credentials


MAX_FOLDER_PARTS = 20_000


def _folder_size(resource_id: str, folder: str) -> tuple[int, str, str, bool]:
    """Total bytes of the Parquet parts below an S3 folder, checked against the load budget."""
    folder = duck._validate_relative_key(folder)
    client, bucket, key, uri, region, app_credentials = _s3_client(resource_id, folder)
    total = parts = 0
    token = None
    try:
        while True:
            request = {"Bucket": bucket, "Prefix": key, "MaxKeys": 1000}
            if token:
                request["ContinuationToken"] = token
            response = client.list_objects_v2(**request)
            for item in response.get("Contents", []):
                if duck.is_parquet_part(item.get("Key", "")):
                    parts += 1
                    total += int(item.get("Size") or 0)
            if parts > MAX_FOLDER_PARTS:
                raise OperationTooLarge(
                    f"This folder has more than {MAX_FOLDER_PARTS:,} Parquet parts; "
                    "open a narrower subfolder.")
            token = response.get("NextContinuationToken")
            if not token:
                break
    except OperationTooLarge:
        raise
    except Exception as exc:
        raise SourceSizeUnknown(
            "The S3 folder could not be listed, so Studio cannot safely load it.") from exc
    if parts == 0:
        raise ValueError(f"No Parquet files were found in {folder}.")
    _budget(total, total)
    return total, uri, region, app_credentials


def _url_size(uri: str, profile: str | None) -> int:
    parsed = urlsplit(uri)
    if parsed.scheme == "s3":
        import boto3

        session = boto3.Session(profile_name=profile) if profile else boto3.Session()
        client = session.client("s3")
        key = parsed.path.lstrip("/")
        if any(char in key for char in "*?["):
            pattern = key
            prefix = re.split(r"[*?\[]", key, maxsplit=1)[0]
            prefix = prefix.rpartition("/")[0]
            total = 0
            token = None
            while True:
                request = {"Bucket": parsed.netloc, "Prefix": prefix}
                if token:
                    request["ContinuationToken"] = token
                response = client.list_objects_v2(**request)
                for item in response.get("Contents", []):
                    if fnmatch.fnmatchcase(item.get("Key", ""), pattern):
                        total += int(item.get("Size", 0))
                token = response.get("NextContinuationToken")
                if not token:
                    break
            if total <= 0:
                raise SourceSizeUnknown("A catalog view source path did not match any S3 objects.")
            return total
        try:
            return int(client.head_object(Bucket=parsed.netloc, Key=key)["ContentLength"])
        except Exception as exc:
            raise SourceSizeUnknown(
                "The catalog file size could not be checked, so Studio cannot safely load it.") from exc
    elif parsed.scheme == "https":
        if any(char in uri for char in "*?["):
            raise SourceSizeUnknown("A wildcard HTTPS source cannot be sized safely.")
        try:
            request = urllib.request.Request(uri, method="HEAD")
            with urllib.request.urlopen(request, timeout=10) as response:
                return int(response.headers.get("Content-Length", ""))
        except Exception as exc:
            raise SourceSizeUnknown(
                "The catalog file size could not be checked, so Studio cannot safely load it.") from exc
    else:
        raise SourceSizeUnknown("The catalog file size cannot be estimated safely.")


def _catalog_size(uri: str, profile: str | None, view_sql: str | None = None) -> int:
    parsed = urlsplit(uri)
    if parsed.scheme:
        size = _url_size(uri, profile)
    else:
        try:
            size = Path(uri).stat().st_size
        except OSError as exc:
            raise SourceSizeUnknown("The local catalog file size could not be checked.") from exc
    if view_sql:
        refs = re.findall(r"read_[\w]+\s*\(\s*['\"]([^'\"]+)", view_sql, re.I)
        for source_uri in refs:
            source_scheme = urlsplit(source_uri).scheme
            if source_scheme in {"s3", "https"}:
                size += _url_size(source_uri, profile)
            elif source_uri.startswith("/"):
                paths = glob.glob(source_uri)
                if not paths:
                    raise SourceSizeUnknown(
                        f"A catalog view file could not be sized: {Path(source_uri).name}.")
                size += sum(Path(path).stat().st_size for path in paths)
            else:
                raise SourceSizeUnknown("A catalog view source path cannot be sized safely.")
    _budget(size, size)
    return size


def _stream_result(reader, path: str, estimated_bytes: int,
                   table: str = "data") -> tuple[list[str], int, int]:
    columns = list(reader.schema.names)
    # DuckDB would rename a case-folded duplicate (age -> age_1), so the stored
    # columns would no longer match the source's column list.
    dbcon = _connect(path)
    conname = "_studio_batch"
    total_bytes = 0
    rows = 0
    created = False
    try:
        empty = reader.schema.empty_table()
        dbcon.register(conname, empty)
        dbcon.execute(f"CREATE TABLE {_q(table)} AS SELECT * FROM {conname}")
        dbcon.unregister(conname)
        stored = [row[0] for row in dbcon.execute(f"DESCRIBE {_q(table)}").fetchall()]
        if stored != columns:
            raise ValueError("Stored columns differ from the source columns; rename duplicate columns.")
        created = True
        for batch in reader:
            batch_bytes = int(batch.nbytes)
            total_bytes += batch_bytes
            _actual_budget(estimated_bytes + total_bytes)
            dbcon.register(conname, batch)
            dbcon.execute(f"INSERT INTO {_q(table)} SELECT * FROM {conname}")
            dbcon.unregister(conname)
            rows += batch.num_rows
    finally:
        try:
            dbcon.unregister(conname)
        except Exception:
            pass
        dbcon.close()
    if not created:
        raise RuntimeError("Could not create the disk-backed source table.")
    return columns, rows, total_bytes


def _preview(path: str, table: str = "data", limit: int = 100_000) -> pd.DataFrame:
    con = _connect(path, read_only=True)
    try:
        return con.execute(f"SELECT * FROM {_q(table)} LIMIT {int(limit)}").to_arrow_table().to_pandas(types_mapper=pd.ArrowDtype)
    finally:
        con.close()


def profile_columns(source: dict, profiles: list[dict]) -> list[dict]:
    con = _connect(source["path"], read_only=True)
    relation = _q(source.get("table", "data"))
    try:
        types = {row[0]: row[1] for row in con.execute(f"DESCRIBE {relation}").fetchall()}
    except Exception:
        con.close()
        raise
    result, expressions, expression_aliases, result_slots = [], [], [], {}
    for index, profile in enumerate(profiles):
        name, kind = profile["name"], profile.get("filter_kind")
        col = f"src.{_q(name)}"
        if kind == "range":
            low_alias, high_alias = f"_studio_min_{index}", f"_studio_max_{index}"
            expressions.extend([
                f"MIN(TRY_CAST({col} AS DOUBLE)) AS {_q(low_alias)}",
                f"MAX(TRY_CAST({col} AS DOUBLE)) AS {_q(high_alias)}",
            ])
            expression_aliases.extend([low_alias, high_alias])
            result_slots[index] = ("range", low_alias, high_alias)
        elif kind == "date":
            low_alias, high_alias = f"_studio_min_{index}", f"_studio_max_{index}"
            day = f"TRY_CAST(TRY_CAST({col} AS TIMESTAMPTZ) AS DATE)"
            expressions.extend([
                f"MIN({day}) AS {_q(low_alias)}",
                f"MAX({day}) AS {_q(high_alias)}",
            ])
            expression_aliases.extend([low_alias, high_alias])
            result_slots[index] = ("date", low_alias, high_alias)
        elif kind == "categorical":
            values_alias = f"_studio_values_{index}"
            expressions.append(
                f"APPROX_TOP_K({category_text.duck_text(col, types.get(name))}, 50) "
                f"AS {_q(values_alias)}")
            expression_aliases.append(values_alias)
            result_slots[index] = ("categorical", values_alias)
    try:
        if expressions:
            scan_bytes = int(source.get("scan_bytes") or os.path.getsize(source["path"]))
            _budget(scan_bytes)
            names = ", ".join(expressions)
            metrics = con.execute(
                f"SELECT {names} FROM {relation} AS src").fetchone()
            by_name = dict(zip(expression_aliases, metrics))
        for index, profile in enumerate(profiles):
            entry = dict(profile)
            if entry.get("filter_kind") == "range":
                _, low_alias, high_alias = result_slots[index]
                low, high = by_name[low_alias], by_name[high_alias]
                if low is not None and high is not None:
                    entry["min"], entry["max"] = float(low), float(high)
            elif entry.get("filter_kind") == "date":
                _, low_alias, high_alias = result_slots[index]
                low, high = by_name[low_alias], by_name[high_alias]
                if low is not None and high is not None:
                    entry["min_date"], entry["max_date"] = low.isoformat(), high.isoformat()
            elif entry.get("filter_kind") == "categorical":
                _, values_alias = result_slots[index]
                entry["values"] = [category_text.normalize_label(str(value), types.get(entry["name"])) for value in
                                   (by_name.get(values_alias) or [])]
            result.append(entry)
    finally:
        con.close()
    return result


def _walk_plan(node: dict):
    yield node
    for child in node.get("Plans", []) or []:
        yield from _walk_plan(child)


def _validated_live_sql(live_source: dict) -> str:
    if isinstance(live_source, CompiledSourceQuery):
        from source_models import source_dict

        if source_dict(live_source.source_ref) != live_source.source_ref:
            raise ValueError("Compiled source query reference is invalid.")
        return live_source["sql"]
    import sql_source

    expression = sqlglot.parse_one(live_source.get("sql"), read="postgres")
    for node in list(expression.walk()):
        if node.__class__.__name__ in {"Placeholder", "Parameter"}:
            node.replace(exp.Null())
    sql_source.normalize(expression.sql(dialect="postgres"))
    return live_source["sql"]


def _estimate_live_bytes(live_source: dict) -> int:
    normalized = _validated_live_sql(live_source)
    engine = db.get_engine_for_resource(live_source["resource_id"])
    sql = f"EXPLAIN (FORMAT JSON) SELECT * FROM ({normalized}) AS studio_input"
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            with query_cancellation.postgres_connection(conn):
                if conn.dialect.name == "postgresql":
                    conn.exec_driver_sql("SET TRANSACTION READ ONLY")
                    scope = query_cancellation.current.get()
                    timeout = scope.timeout_ms if scope is not None and scope.timeout_ms is not None else 15000
                    query_cancellation.check()
                    conn.exec_driver_sql(f"SET LOCAL statement_timeout = {timeout}")
                query_cancellation.check()
                raw = conn.execute(text(sql), live_source.get("params", {})).scalar()
                plan = json.loads(raw)[0]["Plan"] if isinstance(raw, str) else raw[0]["Plan"]
                estimated = 0
                relations = set()
                for item in _walk_plan(plan):
                    rows = item.get("Plan Rows")
                    width = item.get("Plan Width")
                    if isinstance(rows, int) and isinstance(width, int):
                        estimated = max(estimated, rows * width)
                    relation, schema = item.get("Relation Name"), item.get("Schema")
                    if relation and schema:
                        relations.add(f'{schema}.{relation}')
                storage = 0
                if relations:
                    for name in sorted(relations):
                        schema, relation = name.split(".", 1)
                        regclass = f"{_q(schema)}.{_q(relation)}"
                        storage += int(conn.execute(
                            text("SELECT COALESCE(pg_total_relation_size(to_regclass(:name)), 0)"),
                            {"name": regclass}).scalar() or 0)
                estimate = max(estimated, storage)
                if estimate <= 0:
                    raise SourceSizeUnknown(
                        "PostgreSQL did not return a source-size estimate; Studio cannot safely stage it.")
                _budget(estimate, estimate)
                return estimate
        finally:
            transaction.rollback()


def estimate_live_source(live_source: dict) -> dict:
    estimate = _estimate_live_bytes(live_source)
    _budget(estimate)
    metadata = {"estimated_bytes": estimate,
                "large_warning": estimate >= LARGE_OPERATION_BYTES}
    if isinstance(live_source, CompiledSourceQuery):
        return live_source.with_metadata(**metadata)
    return {**live_source, **metadata}


def guard_live_query(live_source: dict, charts: list[dict],
                     entity_column: str | None = None) -> int:
    estimate = int(live_source.get("estimated_bytes") or
                   _estimate_live_bytes(live_source))
    scans = 3 + (2 if entity_column else 0)
    for chart in charts:
        scans += {"bar": 4, "histogram": 5, "scatter": 1, "map": 1,
                  "heatmap": 1, "box": 3}.get(chart.get("kind"), 1)
    return _budget(estimate * scans)


def guard_live_join(live_sources: list[dict], output_source: dict) -> dict:
    scan_bytes = sum(int(source.get("estimated_bytes") or
                         _estimate_live_bytes(source)) for source in live_sources)
    output_bytes = _estimate_live_bytes(output_source)
    total = _budget(scan_bytes, output_bytes)
    return {"estimated_bytes": total,
            "large_warning": total >= LARGE_OPERATION_BYTES,
            "complete_source": True}


def _stage_storage_type(description) -> str:
    oid = getattr(description, "type_code", None)
    if oid == 1700:
        precision = getattr(description, "precision", None)
        scale = getattr(description, "scale", None)
        if isinstance(precision, int) and isinstance(scale, int) and 0 <= scale <= precision <= 38:
            return f"DECIMAL({precision},{scale})"
        return "VARCHAR"
    return {16: "BOOLEAN", 17: "BLOB", 20: "BIGINT", 21: "SMALLINT", 23: "INTEGER",
            700: "FLOAT", 701: "DOUBLE", 1082: "DATE", 1083: "TIME",
            1114: "TIMESTAMP", 1184: "TIMESTAMPTZ", 2950: "UUID"}.get(oid, "VARCHAR")


def stage_live(con, live_source: dict, dataset: dict, table: str,
               budget_used: int) -> tuple[int, int]:
    normalized = _validated_live_sql(live_source)
    estimate = _estimate_live_bytes(live_source)
    _budget(budget_used, estimate)
    engine = db.get_engine_for_resource(live_source["resource_id"])
    sql = text(normalized)
    mapping = live_source.get("columns", {})
    logical_columns = list(dataset["df"].columns)
    physical_to_logical = {physical: logical
                           for logical, physical in mapping.items()}
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            with query_cancellation.postgres_connection(conn):
                result = _stage_live_rows(con, conn, sql, live_source, logical_columns, physical_to_logical, table, budget_used, estimate)
            transaction.commit()
            return result
        except Exception:
            transaction.rollback()
            raise


def _stage_live_rows(con, conn, sql, live_source, logical_columns, physical_to_logical, table, budget_used, estimate):
    if conn.dialect.name == "postgresql":
        conn.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        scope = query_cancellation.current.get()
        timeout = scope.timeout_ms if scope is not None and scope.timeout_ms is not None else 120000
        query_cancellation.check()
        conn.exec_driver_sql(f"SET LOCAL statement_timeout = {int(timeout)}")
    conn = conn.execution_options(stream_results=True,
                                  yield_per=_BATCH_ROWS)
    query_cancellation.check()
    result = conn.execute(sql, live_source.get("params", {}))
    physical_columns = list(result.keys())
    descriptions = result.cursor.description
    storage = {physical_to_logical.get(name, name): _stage_storage_type(description)
               for name, description in zip(physical_columns, descriptions)}
    if set(logical_columns) != set(storage):
        raise ValueError("Source columns changed before staging; reload the source.")
    definitions = ", ".join(f"{_q(name)} {storage[name]}" for name in logical_columns)
    con.execute(f"CREATE TABLE {_q(table)} ({definitions})")
    total_bytes, rows = 0, 0
    while records := result.fetchmany(_BATCH_ROWS):
        query_cancellation.check()
        batch = pd.DataFrame(records, columns=physical_columns, dtype=object)
        batch = batch.rename(columns=physical_to_logical)
        batch = batch.reindex(columns=logical_columns)
        for name, kind in storage.items():
            if kind == "VARCHAR":
                batch[name] = batch[name].map(lambda value: json.dumps(value, default=str)
                    if isinstance(value, (dict, list)) else str(value) if value is not None else None)
        batch_bytes = int(batch.memory_usage(index=False, deep=True).sum())
        total_bytes += batch_bytes
        _actual_budget(budget_used + estimate + total_bytes)
        con.register("_studio_live_batch", batch)
        con.execute(f"INSERT INTO {_q(table)} SELECT * FROM _studio_live_batch")
        con.unregister("_studio_live_batch")
        rows += len(batch)
    query_cancellation.check()
    return rows, estimate + total_bytes


def _frame_bytes(frame: pd.DataFrame) -> int:
    return max(1, int(frame.memory_usage(index=False, deep=True).sum()))


def _duckdb_estimate(con, sql: str, avg_width: int, params: dict | None = None) -> int | None:
    plan = "\n".join(str(row[1]) for row in con.execute(f"EXPLAIN {sql}", params or None).fetchall())
    matches = re.findall(r"~([0-9,]+) rows", plan)
    if not matches:
        return None
    rows = max(int(value.replace(",", "")) for value in matches)
    return rows * max(1, avg_width)


def _stream_duck_query(reader_con, writer_con, sql: str, table: str,
                       budget_used: int, params: list | dict | None = None) -> tuple[int, int]:
    query_cancellation.check()
    reader = reader_con.execute(sql, params or []).to_arrow_reader(_BATCH_ROWS)
    temp_name = "_studio_arrow_batch"
    schema = reader.schema
    writer_con.register(temp_name, schema.empty_table())
    writer_con.execute(f"CREATE TABLE {_q(table)} AS SELECT * FROM {temp_name}")
    writer_con.unregister(temp_name)
    row_count, bytes_written = 0, 0
    for batch in reader:
        query_cancellation.check()
        bytes_written += int(batch.nbytes)
        _actual_budget(budget_used + bytes_written)
        writer_con.register(temp_name, batch)
        writer_con.execute(f"INSERT INTO {_q(table)} SELECT * FROM {temp_name}")
        writer_con.unregister(temp_name)
        row_count += batch.num_rows
    query_cancellation.check()
    return row_count, bytes_written


@_bounded_materialization
def run_join(plan: dict, full_readers: bool = True) -> dict:
    """Run a cross-source join in a DuckDB staging file.

    Live (PostgreSQL) and disk inputs are read in full. Capped in-memory
    inputs that have a full-source reader are read in full too: frames
    loaded straight from an Aurora table (`origin`) through the live path,
    and BigQuery tables through the Storage Read API (only when
    `full_readers`; previews use the loaded BigQuery rows and say so).
    """
    import joins

    datasets = [plan["base"]] + [step["ds"] for step in plan["steps"]]
    readers, fallbacks = _full_readers(plan, datasets, full_readers)
    pushdown = _pushdown_filters(plan, readers)
    source_estimates = []
    for index, dataset in enumerate(datasets):
        query_cancellation.check()
        disk = dataset.get("disk_source")
        live = dataset.get("live_source") or (readers.get(index) or {}).get("live")
        if live and index in pushdown:
            live = joins.filtered_live(live, pushdown[index], joins._filter_prefix(index, plan))
        if disk:
            estimate = max(1, int(disk.get("estimated_bytes") or 0),
                           int(disk.get("scan_bytes") or 0),
                           os.path.getsize(disk["path"]))
        elif live:
            estimate = _estimate_live_bytes(live)
        elif index in readers:
            estimate = readers[index]["estimate"]
        else:
            estimate = _frame_bytes(dataset["df"])
        source_estimates.append(estimate)
    _budget(sum(source_estimates), sum(source_estimates))

    path = _new_path()
    writer = _connect(path)
    reader = _connect(path)
    try:
        with query_cancellation.duckdb_connection(writer), query_cancellation.duckdb_connection(reader):
            return _run_join_materialization(plan, datasets, source_estimates, path, writer, reader,
                                             pushdown, readers, fallbacks)
    except Exception:
        try:
            reader.close()
        except Exception:
            pass
        try:
            writer.close()
        except Exception:
            pass
        remove({"path": path})
        raise
    finally:
        try:
            reader.close()
        except Exception:
            pass
        try:
            writer.close()
        except Exception:
            pass


def _needed_columns(plan: dict, dataset: dict) -> list[str] | None:
    """Columns of `dataset` the join reads, or None for all of them."""
    needed = set()
    if plan["base"] is dataset:
        return None                     # every base column is in the output
    for step in plan["steps"]:
        if step["ds"] is not dataset:
            continue
        needed.update(cond["right"] for cond in step["conds"])
        needed.update(source for source, _ in step.get("cols") or [])
        needed.update(f["column"] for f in step.get("filters") or [])
    columns = [name for name in dataset["df"].columns if name in needed]
    return columns if len(columns) < len(dataset["df"].columns) else None


def _full_readers(plan: dict, datasets: list[dict], bigquery: bool = True
                  ) -> tuple[dict[int, dict], dict[int, str]]:
    """Input index -> full-source reader for capped in-memory inputs, and
    input index -> why a capped input keeps its loaded rows."""
    import joins

    readers, fallbacks, seen = {}, {}, {}
    for index, dataset in enumerate(datasets):
        if id(dataset) in seen:
            continue
        seen[id(dataset)] = index
        kind = joins.full_reader_kind(dataset)
        if kind == "aurora":
            origin = dataset["origin"]
            columns = list(dataset["df"].columns)
            readers[index] = {"kind": "aurora", "live": {
                "resource_id": origin["resource_id"], "params": {},
                "sql": (f"SELECT * FROM {_q(origin.get('schema') or 'public')}."
                        f"{_q(origin['table'])}"),
                "columns": {name: name for name in columns}}}
        elif kind == "bq" and not bigquery:
            fallbacks[index] = "preview"
        elif kind == "bq":
            import bq
            spec = bq.full_source(dataset)
            query_cancellation.check()
            meta = bq.table_meta(spec)
            if meta["table_type"] not in bq.STREAMABLE_TABLE_TYPES:
                fallbacks[index] = (f"BigQuery {meta['table_type'].lower() or 'object'}s cannot be "
                                    "read in full (only tables can)")
                continue
            if meta["num_bytes"] is None:
                raise SourceSizeUnknown(
                    "BigQuery did not report the table size, so Studio cannot safely read it in full.")
            _budget(meta["num_bytes"], meta["num_bytes"])
            readers[index] = {"kind": "bq", "spec": spec, "meta": meta,
                              "estimate": max(1, meta["num_bytes"]),
                              "columns": _needed_columns(plan, dataset)}
    return readers, fallbacks


def stage_bigquery(con, source: dict, dataset: dict, table: str, budget_used: int,
                   filters: list[dict] | None = None) -> tuple[int, int, list[dict]]:
    """Stream a BigQuery table into `table` in Arrow batches.

    Pushes the filters BigQuery evaluates exactly into the read and returns
    (rows, bytes consumed, residual filters to apply in DuckDB).
    """
    import bq
    import data_jobs
    from contextlib import nullcontext

    spec, meta, estimate = source["spec"], source["meta"], source["estimate"]
    _budget(budget_used, estimate)
    restriction, residual = bq.row_restriction(filters or [], meta["types"],
                                           meta.get("modes"))
    columns = source.get("columns")
    if columns is not None:
        columns = list(dict.fromkeys(columns + [f["column"] for f in residual]))
    label = f"{spec['project']}.{spec['dataset']}.{spec['table']}"
    total = meta.get("num_rows")
    data_jobs.report(f"Reading BigQuery table {spec['table']} in full",
                     resource=spec["resource_id"], table=label, rows=0)
    stream = {}

    def cancel():
        if "stream" in stream:
            stream["stream"].cancel()

    scope = query_cancellation.current.get()
    rows, total_bytes, created = 0, 0, False
    temp_name = "_studio_bq_batch"
    try:
        with scope.bind(cancel) if scope is not None else nullcontext():
            query_cancellation.check()
            for batch in bq.read_batches(spec, columns, restriction,
                                         on_stream=lambda s: stream.__setitem__("stream", s)):
                query_cancellation.check()
                total_bytes += int(batch.nbytes)
                _actual_budget(budget_used + estimate + total_bytes)
                con.register(temp_name, batch)
                if not created:
                    con.execute(f"CREATE TABLE {_q(table)} AS SELECT * FROM {temp_name}")
                    created = True
                else:
                    con.execute(f"INSERT INTO {_q(table)} BY NAME SELECT * FROM {temp_name}")
                con.unregister(temp_name)
                rows += batch.num_rows
                done = f"{rows:,} of {total:,}" if total else f"{rows:,}"
                data_jobs.report(f"Reading BigQuery table {spec['table']} in full: {done} rows",
                                 rows=rows)
    except Exception:
        query_cancellation.check()
        raise
    finally:
        cancel()                        # release the read stream on any exit (no-op when done)
    query_cancellation.check()
    if not created:
        # No rows matched: an empty table with the loaded columns.
        empty = dataset["df"].head(0)
        if columns is not None:
            empty = empty[columns]
        con.register(temp_name, empty)
        con.execute(f"CREATE TABLE {_q(table)} AS SELECT * FROM {temp_name}")
        con.unregister(temp_name)
    return rows, estimate + total_bytes, residual


def _pushdown_filters(plan: dict, readers: dict[int, dict] | None = None) -> dict[int, list[dict]]:
    """Input index -> filters to apply while staging a live or full-read source.

    Filtering in the source reduces the rows read and staged. Only for
    inputs used once: a dataset joined twice may carry different filters.
    BigQuery inputs push down what BigQuery evaluates exactly; the rest runs
    in DuckDB after staging (see `stage_bigquery`).
    """
    readers = readers or {}
    datasets = [plan["base"]] + [step["ds"] for step in plan["steps"]]
    filters = [plan.get("base_filters") or []] + [step.get("filters") or []
                                                  for step in plan["steps"]]
    uses = {}
    for dataset in datasets:
        uses[id(dataset)] = uses.get(id(dataset), 0) + 1
    return {index: filters[index] for index, dataset in enumerate(datasets)
            if filters[index] and (dataset.get("live_source") or index in readers)
            and not dataset.get("disk_source") and uses[id(dataset)] == 1}


def _run_join_materialization(plan, datasets, source_estimates, path, writer, reader,
                              pushdown=None, readers=None, fallbacks=None):
    import joins

    pushdown, readers, fallbacks = pushdown or {}, readers or {}, fallbacks or {}
    residual = {}                       # input index -> filters BigQuery could not apply
    relations, row_counts = {}, {}
    attached = {}
    budget_used = sum(source_estimates)
    for index, dataset in enumerate(datasets):
        query_cancellation.check()
        key = id(dataset)
        if key in relations:
            continue
        disk = dataset.get("disk_source")
        full = readers.get(index)
        live = dataset.get("live_source") or (full or {}).get("live")
        if disk:
            alias = f"input_{index}"
            if disk["path"] not in attached:
                reader.execute(f"ATTACH {_lit(disk['path'])} AS {_q(alias)} (READ_ONLY)")
                attached[disk["path"]] = alias
            else:
                alias = attached[disk["path"]]
            table = disk.get("table", "data")
            relation = f"{_q(alias)}.{_q(table)}"
            rows = int(disk.get("rows", 0))
            if not rows:
                rows = int(reader.execute(f"SELECT COUNT(*) FROM {relation}").fetchone()[0])
        elif live:
            table = f"source_{index}"
            if index in pushdown:
                live = joins.filtered_live(live, pushdown[index], joins._filter_prefix(index, plan))
            rows, consumed = stage_live(writer, live, dataset, table, budget_used)
            budget_used += max(0, consumed - source_estimates[index])
            relation = _q(table)
        elif full and full["kind"] == "bq":
            table = f"source_{index}"
            rows, consumed, left_over = stage_bigquery(
                writer, full, dataset, table, budget_used, pushdown.get(index))
            if left_over:
                residual[index] = left_over
            budget_used += max(0, consumed - source_estimates[index])
            relation = _q(table)
        else:
            table = f"source_{index}"
            writer.register("_studio_frame", dataset["df"])
            writer.execute(f"CREATE TABLE {_q(table)} AS SELECT * FROM _studio_frame")
            writer.unregister("_studio_frame")
            relation, rows = _q(table), len(dataset["df"])
        relations[key], row_counts[key] = relation, rows

    def filtered(index, relation, filters):
        # Pushed-down filters were applied while staging; others run here.
        if index in pushdown:
            filters = residual.get(index) or []
        if not filters:
            return relation, {}, None
        rel, params = joins._filtered_rel(relation, filters, joins._filter_prefix(index, plan), pg=False)
        query_cancellation.check()
        count = int(reader.execute(f"SELECT COUNT(*) FROM {rel} AS counted", params).fetchone()[0])
        return rel, params, count

    current, params, count = filtered(0, relations[id(plan["base"])], plan.get("base_filters") or [])
    base_rows = before = row_counts[id(plan["base"])] if count is None else count
    step_stats, notes = [], []
    for step in plan["steps"]:
        query_cancellation.check()
        right, right_params, right_count = filtered(
            step["no"], relations[id(step["ds"])], step.get("filters") or [])
        params = {**params, **right_params}
        sql = _join_step_sql(step, current, right)
        width = max(1, int(sum(_frame_bytes(ds["df"]) / max(1, len(ds["df"]))
                               for ds in [plan["base"], step["ds"]])))
        estimate = _duckdb_estimate(reader, sql, width, params)
        if estimate is not None:
            _budget(budget_used, estimate)
        name = f"step_{step['no']}"
        rows, materialized = _stream_duck_query(
            reader, writer, sql, name, budget_used, params)
        params = {}
        budget_used += materialized
        growth = round(rows / before, 2) if before else None
        step_stats.append({"right_rows": row_counts[id(step["ds"])] if right_count is None else right_count,
                           "rows": rows, "truncated": False,
                           "rows_before": before, "growth": growth,
                           "fanout": growth is not None and growth > 2.0})
        notes.extend(f"step {step['no']}: {note}" for note in step["notes"])
        current, before = _q(name), rows
    query_cancellation.check()
    preview = reader.execute(
        f"SELECT * FROM {current} LIMIT 100000").df()
    query_cancellation.check()
    # Capped in-memory inputs without a full-source reader are staged from
    # their loaded rows, so the result is not complete even though every
    # other input was read in full.
    full_ids = {id(datasets[index]) for index in readers}
    capped_inputs = joins.capped_inputs(datasets, full_ids)
    previewed = [datasets[i]["source"] for i, why in fallbacks.items() if why == "preview"]
    if previewed:
        notes.append(f"Preview used the loaded (capped) rows of {', '.join(previewed)}; "
                     "running the join reads every row.")
    for index, why in fallbacks.items():
        if why != "preview":
            notes.append(f"Used only the loaded (capped) rows of {datasets[index]['source']}: {why}.")
    unexplained = [source for source in capped_inputs if source not in previewed and source not in
                   {datasets[i]["source"] for i in fallbacks}]
    if unexplained:
        notes.append(f"Used only the loaded (capped) rows of {', '.join(unexplained)} "
                     "— results may be incomplete.")
    full_sources = [datasets[i]["source"] for i, r in readers.items() if r["kind"] == "bq"]
    if full_sources:
        notes.append(f"Read every row of {', '.join(full_sources)} from BigQuery.")
    stats = {"engine": "duckdb", "base_rows": base_rows,
             "steps": step_stats, "notes": notes, "capped_inputs": capped_inputs,
             "rows": before, "total_rows": before, "truncated": False,
             "estimated_bytes": budget_used,
             "large_warning": budget_used >= LARGE_OPERATION_BYTES,
             "complete_source": not capped_inputs,
             "materialized_bytes": budget_used - sum(source_estimates)}
    return {"df": preview, "stats": stats,
            "disk_source": {"path": path, "table": current.strip('"'),
                            "columns": list(preview.columns), "rows": before,
                            "estimated_bytes": budget_used,
                            "scan_bytes": os.path.getsize(path),
                            "large_warning": budget_used >= LARGE_OPERATION_BYTES}}

@_bounded_materialization
def derive(source: dict, spec: dict, frame: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict]:
    from source_models import DerivedSpec

    spec = DerivedSpec.model_validate(spec).model_dump(exclude_none=True)
    name = spec["name"].strip()
    columns = list(source["columns"])
    if spec["op"] in {"group_count", "group_sum", "group_mean", "group_min", "group_max"}:
        groups = spec.get("group_by") or [spec["column"]]
        for col in groups:
            if col not in columns: raise ValueError(f"Unknown column: {col}")
        groups = [_q(col) for col in groups]
        if spec["op"] == "group_count":
            aggregate = "COUNT(*)"
        else:
            measure = spec["measure"]
            if measure not in columns:
                raise ValueError(f"Unknown column: {measure}")
            number = f"TRY_CAST({_q(measure)} AS DOUBLE)"
            safe_number = f"CASE WHEN ISFINITE({number}) THEN {number} ELSE NULL END"
            function = {"group_sum": "SUM", "group_mean": "AVG", "group_min": "MIN", "group_max": "MAX"}[spec["op"]]
            aggregate = f"{function}({safe_number})"
        missing = " OR ".join(f"{group} IS NULL" for group in groups)
        expression = f"CASE WHEN {missing} THEN NULL ELSE {aggregate} OVER (PARTITION BY {', '.join(groups)}) END"
    elif spec["op"] == "expression":
        import calculations
        types = calculations.column_types(frame) if frame is not None else {}
        calc = calculations.parse(spec["expression"], columns, types, spec.get("parameters") or [])
        expression = calculations.sql(calc, "duckdb", _q)
    elif spec["op"] == "bin":
        col = spec["column"]
        if col not in columns:
            raise ValueError(f"Unknown column: {col}")
        breaks = [float(value) for value in spec["breaks"]]
        labels = spec.get("labels") or [
            f"({breaks[i]}, {breaks[i + 1]}]" for i in range(len(breaks) - 1)]
        numeric = f"TRY_CAST({_q(col)} AS DOUBLE)"
        clauses = []
        for i, label in enumerate(labels):
            lower = ">=" if i == 0 else ">"
            clauses.append(
                f"WHEN {numeric} {lower} {breaks[i]} AND {numeric} <= {breaks[i + 1]} "
                f"THEN {_lit(str(label))}")
        expression = "CASE " + " ".join(clauses) + " ELSE NULL END"
    elif spec["op"] == "formula":
        left = spec["left"]
        if left not in columns:
            raise ValueError(f"Unknown column: {left}")
        lvalue = f"TRY_CAST({_q(left)} AS DOUBLE)"
        right = spec["right"]
        try:
            number = float(right)
            if not math.isfinite(number):
                raise ValueError
            rvalue = str(number)
        except (TypeError, ValueError):
            if right not in columns:
                raise ValueError(f"Unknown column: {right}")
            rvalue = f"TRY_CAST({_q(right)} AS DOUBLE)"
        operator = spec["operator"]
        if operator == "/":
            rvalue = f"NULLIF({rvalue}, 0)"
        expression = f"({lvalue} {operator} {rvalue})"
    else:
        column = spec["column"]
        if column not in columns:
            raise ValueError(f"Unknown column: {column}")
        expression = "CASE CAST(" + _q(column) + " AS VARCHAR) "
        for key, value in (spec.get("mapping") or {}).items():
            expression += f"WHEN {_lit(str(key))} THEN {_lit(str(value))} "
        default = spec.get("default")
        fallback = _lit(str(default)) if default not in (None, "") else f"CAST({_q(column)} AS VARCHAR)"
        expression += f"ELSE {fallback} END"
    select = [f"src.{_q(column)}" for column in columns if column != name]
    select.append(f"{expression} AS {_q(name)}")
    sql = f"SELECT {', '.join(select)} FROM {_q('input')}.{_q(source.get('table', 'data'))} AS src"
    scan_bytes = int(source.get("scan_bytes") or os.path.getsize(source["path"]))
    _budget(scan_bytes, scan_bytes)
    path = _new_path()
    writer, reader = _connect(path), _connect(path)
    reader.execute(f"ATTACH {_lit(source['path'])} AS {_q('input')} (READ_ONLY)")
    try:
        average_width = max(1, scan_bytes // max(1, int(source.get("rows", 1))))
        estimate = _duckdb_estimate(reader, sql, average_width)
        if estimate is not None:
            _budget(scan_bytes, estimate)
        rows, materialized = _stream_duck_query(reader, writer, sql, "data", scan_bytes)
        frame = reader.execute("SELECT * FROM \"data\" LIMIT 100000").df()
        metadata = {"path": path, "table": "data", "columns": list(frame.columns),
                    "rows": rows, "estimated_bytes": scan_bytes + materialized,
                    "scan_bytes": os.path.getsize(path),
                    "large_warning": scan_bytes + materialized >= LARGE_OPERATION_BYTES}
        return frame, metadata
    except Exception:
        try:
            reader.close()
        except Exception:
            pass
        try:
            writer.close()
        except Exception:
            pass
        remove({"path": path})
        raise
    finally:
        try:
            reader.close()
        except Exception:
            pass
        try:
            writer.close()
        except Exception:
            pass
def _join_step_sql(step: dict, left: str, right: str) -> str:
    on = []
    for cond in step["conds"]:
        lref, rref = f"l.{_q(cond['left'])}", f"r.{_q(cond['right'])}"
        if cond["cast"]:
            lref, rref = f"CAST({lref} AS VARCHAR)", f"CAST({rref} AS VARCHAR)"
        on.append(f"{lref} {cond['op']} {rref}")
    import joins
    filled = joins._merged_keys(step)
    select = [(f"COALESCE(l.{_q(name)}, r.{_q(filled[name])}) AS {_q(name)}"
               if name in filled else f"l.{_q(name)}") for name in step["left"]]
    select.extend(f"r.{_q(source)} AS {_q(target)}" for source, target in step["cols"])
    condition = " AND ".join(on)
    if step["how"] in ("semi", "anti"):
        negative = "NOT " if step["how"] == "anti" else ""
        return (f"SELECT {', '.join(select)} FROM {left} AS l WHERE {negative}EXISTS "
                f"(SELECT 1 FROM {right} AS r WHERE {condition})")
    join = {"inner": "INNER", "left": "LEFT", "right": "RIGHT", "full": "FULL OUTER"}[step["how"]]
    return (f"SELECT {', '.join(select)} FROM {left} AS l {join} JOIN "
            f"{right} AS r ON {condition}")


@_bounded_materialization
def open_s3(ref: dict) -> tuple[pd.DataFrame, dict]:
    resource_id, filename = ref["resource_id"], ref["table"]
    if filename.lower().endswith((".vcf", ".vcf.gz")):
        import vcf_sources
        return vcf_sources.open_s3(resource_id, filename)
    sizer = _folder_size if duck.is_parquet_folder(filename) else _object_size
    size, uri, region, app_credentials = sizer(resource_id, filename)
    path = _new_path()
    source_con = _configure(duck._connect(
        None if app_credentials else resource_id,
        region=region, app_credentials=app_credentials))
    try:
        sql = duck._reader_sql(uri, hive=duck._has_hive_path(uri))
        reader = source_con.execute(f"SELECT * FROM {sql}").to_arrow_reader(_BATCH_ROWS)
        columns, rows, materialized = _stream_result(reader, path, size)
    except Exception:
        remove({"path": path})
        raise
    finally:
        source_con.close()
    return _preview(path), {"path": path, "table": "data", "columns": columns,
                            "rows": rows, "estimated_bytes": size,
                            "scan_bytes": os.path.getsize(path),
                            "large_warning": size >= LARGE_OPERATION_BYTES,
                            "materialized_bytes": materialized}


@_bounded_materialization
def open_catalog(ref: dict) -> tuple[pd.DataFrame, dict]:
    import catalog

    uri, profile = catalog.resolve(ref["resource_id"])
    path = _new_path()
    source_con = _configure(catalog._attach(uri, profile))
    try:
        view = ref["table"]
        obj = next((item for item in catalog._objects(source_con)
                    if item["name"] == view), None)
        if obj is None:
            raise catalog.UnknownView(f"{view!r} is not in this catalog.")
        size = _catalog_size(uri, profile, obj["sql"])
        source = f"cat.{catalog._quote(obj['schema'])}.{catalog._quote(obj['object'])}"
        reader = source_con.execute(f"SELECT * FROM {source}").to_arrow_reader(_BATCH_ROWS)
        columns, rows, materialized = _stream_result(reader, path, size)
    except Exception as exc:
        remove({"path": path})
        if isinstance(exc, (catalog.UnknownView, OperationTooLarge, SourceSizeUnknown)):
            raise
        raise catalog._source_error(ref["table"], "", exc) from exc
    finally:
        source_con.close()
    return _preview(path), {"path": path, "table": "data", "columns": columns,
                            "rows": rows, "estimated_bytes": size,
                            "scan_bytes": os.path.getsize(path),
                            "large_warning": size >= LARGE_OPERATION_BYTES,
                            "materialized_bytes": materialized}


def column_types(source: dict) -> dict[str, str]:
    """Stored DuckDB type of each column (cached on the source)."""
    types = source.get("types")
    if not isinstance(types, dict) or set(types) != set(source["columns"]):
        con = _connect(source["path"], read_only=True)
        try:
            described = {row[0]: row[1] for row in con.execute(
                f"DESCRIBE {_q(source.get('table', 'data'))}").fetchall()}
        finally:
            con.close()
        types = {name: described.get(name) for name in source["columns"]}
        source["types"] = types
    return types


def _where(filters: list[dict], columns):
    """WHERE clause for Explore filters, including AND/OR criteria groups.

    ``columns`` maps names to stored types (``column_types``); a plain list of
    names still works, without type-aware category text."""
    import agg_duck
    return filter_rules.combine(filters, lambda flat: agg_duck.where_flat(flat, columns, "src."))


def _duck_dialect(con, relation: str, where: str, params: list, types: dict | None = None):
    import chart_measures
    types = types or {}
    return chart_measures.Dialect(
        rel=f"{relation} AS src", col=lambda name: f"src.{_q(name)}",
        number=lambda name: chart_measures.duck_number(f"src.{_q(name)}"),
        text_type="VARCHAR", named=False, where=where, where_params=params,
        run=lambda sql, values: con.execute(sql, values).fetchall(), postgres=False,
        text=lambda name: category_text.duck_text(f"src.{_q(name)}", types.get(name)))


def _aggregate(con, relation: str, where: str, params: list,
               charts: list[dict], columns, types: dict | None = None):
    import chart_measures
    types = types or {}
    out = []
    for chart in charts:
        kind, x, y = chart.get("kind"), chart.get("x"), chart.get("y")
        if x not in columns or (y and y not in columns):
            raise ValueError("Unknown chart column.")
        qx = f"src.{_q(x)}"
        tx = category_text.duck_text(qx, types.get(x))
        if chart_measures.is_measured(chart):
            out.append(chart_measures.sql_bar(_duck_dialect(con, relation, where, params, types), chart))
        elif kind == "box":
            out.append(chart_measures.sql_box(_duck_dialect(con, relation, where, params, types), chart))
        elif kind == "bar":
            counts = con.execute(
                f"SELECT {tx}, COUNT(*) FROM {relation} AS src "
                f"WHERE {qx} IS NOT NULL GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 12").fetchall()
            selected = {}
            if counts:
                values = [str(row[0]) for row in counts]
                selected = dict(con.execute(
                    f"SELECT {tx}, COUNT(*) FROM {relation} AS src "
                    f"WHERE ({where}) AND {tx} IN "
                    f"({', '.join('?' for _ in values)}) GROUP BY 1",
                    [*params, *values]).fetchall())
            total = int(con.execute(
                f"SELECT COUNT(*) FROM {relation} AS src WHERE {qx} IS NOT NULL").fetchone()[0])
            chosen = sum(int(row[1]) for row in counts)
            filtered = int(con.execute(
                f"SELECT COUNT(*) FROM {relation} AS src "
                f"WHERE ({where}) AND {qx} IS NOT NULL", params).fetchone()[0])
            selected_chosen = sum(int(selected.get(str(row[0]), 0)) for row in counts)
            data = [{"category": str(value), "all": int(count),
                     "selected": int(selected.get(str(value), 0))}
                    for value, count in counts]
            if total > chosen:
                data.append({"category": "Other", "all": total - chosen,
                             "selected": filtered - selected_chosen})
            out.append({"kind": kind, "x": x, "data": data})
        elif kind == "histogram":
            numeric = f"TRY_CAST({qx} AS DOUBLE)"
            low, high = con.execute(
                f"SELECT MIN({numeric}), MAX({numeric}) FROM {relation} AS src").fetchone()
            if low is None:
                out.append({"kind": kind, "x": x, "data": []})
                continue
            low, high = float(low), float(high)
            if low == high:
                delta = abs(low) * 0.05 or 0.5
                low, high = low - delta, high + delta
            width = (high - low) / 24
            bucket = f"LEAST(23, GREATEST(0, FLOOR(({numeric} - {low}) / {width})::INTEGER))"
            full = dict(con.execute(
                f"SELECT {bucket}, COUNT(*) FROM {relation} AS src "
                f"WHERE {numeric} IS NOT NULL GROUP BY 1").fetchall())
            filt = dict(con.execute(
                f"SELECT {bucket}, COUNT(*) FROM {relation} AS src "
                f"WHERE ({where}) AND {numeric} IS NOT NULL GROUP BY 1", params).fetchall())
            out.append({"kind": kind, "x": x, "data": [
                {"lo": low + i * width, "hi": low + (i + 1) * width,
                 "all": int(full.get(i, 0)), "selected": int(filt.get(i, 0))}
                for i in range(24)]})
        elif kind == "map" and y:
            qy = f"src.{_q(y)}"
            nx, ny = f"TRY_CAST({qx} AS DOUBLE)", f"TRY_CAST({qy} AS DOUBLE)"
            rows = con.execute(
                f"SELECT {nx}, {ny} FROM {relation} AS src WHERE ({where}) "
                f"AND {nx} BETWEEN -180 AND 180 AND {ny} BETWEEN -90 AND 90 "
                "ORDER BY random() LIMIT 2000", params).fetchall()
            out.append({"kind": kind, "x": x, "y": y,
                        "data": [[float(a), float(b)] for a, b in rows], "sampled": True})
        elif kind == "scatter" and y:
            qy = f"src.{_q(y)}"
            rows = con.execute(
                f"SELECT TRY_CAST({qx} AS DOUBLE), TRY_CAST({qy} AS DOUBLE) "
                f"FROM {relation} AS src WHERE ({where}) AND {qx} IS NOT NULL "
                f"AND {qy} IS NOT NULL ORDER BY random() LIMIT 2000", params).fetchall()
            out.append({"kind": kind, "x": x, "y": y,
                        "data": [[float(a), float(b)] for a, b in rows], "sampled": True})
        elif kind == "heatmap" and y:
            qy = f"src.{_q(y)}"
            rows = con.execute(
                f"SELECT {tx}, {category_text.duck_text(qy, types.get(y))}, COUNT(*) "
                f"FROM {relation} AS src WHERE ({where}) AND {qx} IS NOT NULL "
                f"AND {qy} IS NOT NULL GROUP BY 1, 2 ORDER BY 3 DESC, 1, 2 LIMIT 401", params).fetchall()
            out.append({"kind": kind, "x": x, "y": y,
                        "data": [[a, b, int(n)] for a, b, n in rows[:400]],
                        "sampled": len(rows) > 400})
        else:
            out.append({"kind": kind, "x": x, "data": []})
    return out


def _row_key(columns) -> str:
    """Stable tiebreak for sorted pages: the table's rowid, else every column."""
    if any(str(name).casefold() == "rowid" for name in columns):
        return ", ".join(f"src.{_q(name)} NULLS LAST" for name in columns)
    return "src.rowid"


def query(source: dict, filters: list[dict], charts: list[dict], page: int,
          page_size: int, entity_column: str | None = None, sort: dict | None = None) -> dict:
    if not isinstance(page, int) or page < 0:
        raise ValueError("Page must be a non-negative integer.")
    if not isinstance(page_size, int) or not 1 <= page_size <= PAGE_SIZE_MAX:
        raise ValueError(f"Page size must be from 1 to {PAGE_SIZE_MAX:,}.")
    columns = source["columns"]
    if entity_column is not None and entity_column not in columns:
        raise ValueError(f"Unknown entity column: {entity_column!r}.")
    if sort and (sort.get("column") not in columns or sort.get("direction") not in ("asc", "desc")):
        raise ValueError("Invalid sort column or direction.")
    scans = 3 + (2 if entity_column else 0)
    for chart in charts:
        scans += {"bar": 4, "histogram": 5, "scatter": 1, "map": 1,
                  "heatmap": 1, "box": 3}.get(chart.get("kind"), 1)
    _budget(int(source.get("scan_bytes") or os.path.getsize(source["path"])) * scans)
    types = column_types(source)
    where, params = _where(filters, types)
    relation = f"{_q(source.get('table', 'data'))}"
    con = _connect(source["path"], read_only=True)
    try:
        total = int(con.execute(f"SELECT COUNT(*) FROM {relation}").fetchone()[0])
        filtered = int(con.execute(
            f"SELECT COUNT(*) FROM {relation} AS src WHERE {where}", params).fetchone()[0])
        charts_out = [category_text.normalize_chart(chart, types) for chart in
                      _aggregate(con, relation, where, params, charts, columns, types)]
        ordering = (f" ORDER BY src.{_q(sort['column'])} {sort['direction'].upper()} NULLS LAST, "
                    f"{_row_key(columns)}") if sort else ""
        frame = con.execute(
            f"SELECT * FROM {relation} AS src WHERE {where}{ordering} LIMIT ? OFFSET ?",
            [*params, page_size, page * page_size]).to_arrow_table().to_pandas(types_mapper=pd.ArrowDtype)
        result = {"total": total, "filtered": filtered, "charts": charts_out,
                  "rows": {"page": page, "page_size": page_size,
                           "columns": columns,
                           "data": [[str(value) if isinstance(value, Decimal) else value for value in row]
                                    for row in frame.astype(object).where(frame.notna(), None).values.tolist()]},
                  "scope": "loaded", "sampled": False}
        if entity_column is not None:
            qentity = _q(entity_column)
            entity_total = int(con.execute(
                f"SELECT COUNT(DISTINCT {qentity}) FROM {relation}").fetchone()[0])
            entity_filtered = int(con.execute(
                f"SELECT COUNT(DISTINCT src.{qentity}) FROM {relation} AS src "
                f"WHERE {where}", params).fetchone()[0])
            result["entity"] = {"column": entity_column,
                                "total": entity_total,
                                "filtered": entity_filtered}
        return result
    finally:
        con.close()


def aggregate(source: dict, agg: str, column: str, group_by: str,
              filters: list[dict]) -> dict:
    supported = {"count", "mean", "median", "min", "max", "sum", "nunique"}
    if agg not in supported:
        raise ValueError(f"agg must be one of {tuple(sorted(supported))}")
    if agg != "count" and not column:
        raise ValueError("A column is required for this aggregate.")
    columns = source["columns"]
    for name in (column, group_by):
        if name and name not in columns:
            raise ValueError(f"Unknown column: {name}")
    _budget(int(source.get("scan_bytes") or os.path.getsize(source["path"])))
    where, params = _where(filters, column_types(source))
    relation = _q(source.get("table", "data"))
    con = _connect(source["path"], read_only=True)
    try:
        matched = int(con.execute(
            f"SELECT COUNT(*) FROM {relation} AS src WHERE {where}", params).fetchone()[0])
        if group_by:
            key = f"COALESCE(CAST(src.{_q(group_by)} AS VARCHAR), 'nan')"
            if agg == "count":
                value = "COUNT(*)"
            else:
                target = f"TRY_CAST(src.{_q(column)} AS DOUBLE)"
                function = {"mean": "AVG", "median": "MEDIAN", "min": "MIN",
                            "max": "MAX", "sum": "SUM", "nunique": "COUNT(DISTINCT"}[agg]
                value = (f"COUNT(DISTINCT {target})" if agg == "nunique"
                         else f"{function}({target})")
            rows = con.execute(
                f"SELECT {key}, {value} FROM {relation} AS src WHERE ({where}) "
                f"GROUP BY 1 ORDER BY 2 DESC LIMIT 25", params).fetchall()
            result = {str(key): (round(float(value), 4) if value is not None else None)
                      for key, value in rows}
        elif agg == "count":
            result = matched
        else:
            target = f"TRY_CAST(src.{_q(column)} AS DOUBLE)"
            function = {"mean": "AVG", "median": "MEDIAN", "min": "MIN",
                        "max": "MAX", "sum": "SUM", "nunique": "COUNT(DISTINCT"}[agg]
            expression = (f"COUNT(DISTINCT {target})" if agg == "nunique"
                          else f"{function}({target})")
            value = con.execute(
                f"SELECT {expression} FROM {relation} AS src WHERE {where}", params).fetchone()[0]
            result = round(float(value), 4) if value is not None else None
        return {"agg": agg, "column": column or None,
                "group_by": group_by or None, "rows_considered": matched,
                "result": result}
    finally:
        con.close()


def compare(source: dict, profiles: list[dict], filters_a: list[dict],
            filters_b: list[dict], b_is_rest: bool = False, scope=()) -> dict:
    import compare as compare_module
    from scipy import stats

    columns = source["columns"]
    a_where, a_params = _where(filters_a, column_types(source))
    if b_is_rest:
        s_where, s_params = _where(list(scope), column_types(source))
        b_where, b_params = f"({s_where}) AND NOT COALESCE(({a_where}), FALSE)", [*s_params, *a_params]
    else:
        b_where, b_params = _where(filters_b, column_types(source))
    compare_scan_count = 2 + 4 * len(profiles)
    _budget(int(source.get("scan_bytes") or os.path.getsize(source["path"]))
            * compare_scan_count)
    relation = _q(source.get("table", "data"))
    con = _connect(source["path"], read_only=True)
    try:
        a_n = int(con.execute(
            f"SELECT COUNT(*) FROM {relation} AS src WHERE {a_where}", a_params).fetchone()[0])
        b_n = int(con.execute(
            f"SELECT COUNT(*) FROM {relation} AS src WHERE {b_where}", b_params).fetchone()[0])
        overlap = 0 if b_is_rest else int(con.execute(
            f"SELECT COUNT(*) FROM {relation} AS src "
            f"WHERE ({a_where}) AND ({b_where})", [*a_params, *b_params]).fetchone()[0])
        results = []
        for profile in profiles:
            kind, name = profile.get("filter_kind"), profile["name"]
            col = f"src.{_q(name)}"
            if kind == "range":
                numeric = f"TRY_CAST({col} AS DOUBLE)"
                rows = con.execute(
                    f"SELECT COUNT({numeric}), MEDIAN({numeric}), AVG({numeric}) "
                    f"FROM {relation} AS src WHERE ({a_where})",
                    a_params).fetchone()
                a_count, a_median, a_mean = rows
                rows = con.execute(
                    f"SELECT COUNT({numeric}), MEDIAN({numeric}), AVG({numeric}) "
                    f"FROM {relation} AS src WHERE ({b_where})",
                    b_params).fetchone()
                b_count, b_median, b_mean = rows
                tie = con.execute(
                    f"WITH grouped AS (SELECT {numeric} AS v, "
                    f"SUM(CASE WHEN ({a_where}) THEN 1 ELSE 0 END) AS a_n, "
                    f"SUM(CASE WHEN ({b_where}) THEN 1 ELSE 0 END) AS b_n "
                    f"FROM {relation} AS src WHERE {numeric} IS NOT NULL "
                    f"AND (({a_where}) OR ({b_where})) GROUP BY 1), ranked AS ("
                    "SELECT *, a_n + b_n AS n, "
                    "SUM(a_n + b_n) OVER (ORDER BY v ROWS BETWEEN UNBOUNDED PRECEDING "
                    "AND CURRENT ROW) AS through_n FROM grouped) "
                    "SELECT SUM(a_n), SUM(b_n), "
                    "SUM(a_n * (through_n - n + (n + 1) / 2.0)), "
                    "SUM(n), SUM(n * n * n - n) FROM ranked",
                    [*a_params, *b_params, *a_params, *b_params]).fetchone()
                na, nb, rank_a, n, tie_term = tie
                summary = {"a": {"n": int(a_count), "median": _finite(a_median),
                                  "mean": _finite(a_mean)},
                           "b": {"n": int(b_count), "median": _finite(b_median),
                                  "mean": _finite(b_mean)}}
                if int(a_count) < compare_module.MIN_GROUP_N or int(b_count) < compare_module.MIN_GROUP_N:
                    result = {**summary, "p": None,
                              "note": f"group too small (n<{compare_module.MIN_GROUP_N})"}
                elif na and nb and n > 1:
                    u = float(rank_a) - float(na) * (float(na) + 1) / 2
                    variance = (float(na) * float(nb) / 12 *
                                (float(n) + 1 - float(tie_term or 0) /
                                 (float(n) * (float(n) - 1))))
                    if variance > 0:
                        z = (abs(u - float(na) * float(nb) / 2) - 0.5) / math.sqrt(variance)
                        p = float(2 * stats.norm.sf(max(0.0, z)))
                        result = {**summary, "p": compare_module._p(p),
                                  "test": "mann-whitney"}
                    else:
                        result = {**summary, "p": None, "note": "constant in both groups"}
                else:
                    result = {**summary, "p": None, "note": "not enough numeric values"}
            elif kind == "categorical":
                rows = con.execute(
                    f"SELECT CAST({col} AS VARCHAR), "
                    f"SUM(CASE WHEN ({a_where}) THEN 1 ELSE 0 END), "
                    f"SUM(CASE WHEN ({b_where}) THEN 1 ELSE 0 END) "
                    f"FROM {relation} AS src WHERE {col} IS NOT NULL "
                    f"AND (({a_where}) OR ({b_where})) GROUP BY 1 "
                    f"ORDER BY SUM(CASE WHEN ({a_where}) THEN 1 ELSE 0 END) + "
                    f"SUM(CASE WHEN ({b_where}) THEN 1 ELSE 0 END) DESC, 1 LIMIT "
                    f"{compare_module.CAT_TOP_N}",
                    [*a_params, *b_params, *a_params, *b_params,
                     *a_params, *b_params]).fetchall()
                top = [str(row[0]) for row in rows]
                a_row = {str(value): int(count_a or 0) for value, count_a, _ in rows}
                b_row = {str(value): int(count_b or 0) for value, _, count_b in rows}
                a_other = max(0, int(a_count := con.execute(
                    f"SELECT COUNT({col}) FROM {relation} AS src WHERE ({a_where})",
                    a_params).fetchone()[0]) - sum(a_row.values()))
                b_other = max(0, int(b_count := con.execute(
                    f"SELECT COUNT({col}) FROM {relation} AS src WHERE ({b_where})",
                    b_params).fetchone()[0]) - sum(b_row.values()))
                counts_a = [a_row[key] for key in top] + [a_other]
                counts_b = [b_row[key] for key in top] + [b_other]
                other_key = object()
                row_a = {**a_row, other_key: a_other}
                row_b = {**b_row, other_key: b_other}
                categories = [key for key in top + [other_key]
                              if row_a.get(key, 0) + row_b.get(key, 0) > 0]
                summary = {
                    "a": {"n": int(a_count), "top": compare_module._top_share(
                        row_a, int(a_count), other_key)},
                    "b": {"n": int(b_count), "top": compare_module._top_share(
                        row_b, int(b_count), other_key)},
                }
                if a_count < compare_module.MIN_GROUP_N or b_count < compare_module.MIN_GROUP_N:
                    result = {**summary, "p": None,
                              "note": f"group too small (n<{compare_module.MIN_GROUP_N})"}
                else:
                    table = [[row_a[key] for key in categories],
                             [row_b[key] for key in categories]]
                    if len(categories) < 2 or not any(map(sum, zip(*table))):
                        result = {**summary, "p": None, "note": "not enough categories"}
                    else:
                        chi = stats.chi2_contingency(table)
                        note = (f"low expected counts (<{compare_module.EXPECTED_MIN}) "
                                "— chi-square approx."
                                if (chi.expected_freq < compare_module.EXPECTED_MIN).any()
                                else None)
                        result = {**summary, "p": compare_module._p(chi.pvalue),
                                  "test": "chi-square", "note": note}
            else:
                continue
            results.append({"column": name, "kind": kind, **result})
        qvals = compare_module._benjamini_hochberg([item.get("p") for item in results])
        for result, q in zip(results, qvals):
            result["q"] = q
        results.sort(key=lambda item: (item.get("p") is None,
                                      item["p"] if item.get("p") is not None else 1.0))
        return {"a_n": a_n, "b_n": b_n, "n_overlap": overlap,
                "results": results}
    finally:
        con.close()


@_bounded_materialization
def count_by_group(source: dict, group_by: str, filters: list[dict],
                   engine, output_table: str) -> dict:
    if group_by not in source["columns"]:
        raise ValueError(f"Unknown column: {group_by}")
    scan_bytes = int(source.get("scan_bytes") or os.path.getsize(source["path"]))
    _budget(scan_bytes, scan_bytes)
    where, params = _where(filters, column_types(source))
    relation, col = _q(source.get("table", "data")), f"src.{_q(group_by)}"
    con = _connect(source["path"], read_only=True)
    try:
        total = int(con.execute(
            f"SELECT COUNT(*) FROM {relation} AS src WHERE {where}", params).fetchone()[0])
        sql = (f"SELECT CAST({col} AS VARCHAR) AS group_value, COUNT(*) AS row_count, "
               f"FALSE AS is_missing FROM {relation} AS src WHERE ({where}) "
               f"AND {col} IS NOT NULL GROUP BY 1 "
               "UNION ALL SELECT NULL, COUNT(*), TRUE FROM "
               f"{relation} AS src WHERE ({where}) AND {col} IS NULL HAVING COUNT(*) > 0")
        reader = con.execute(sql, [*params, *params]).to_arrow_reader(_BATCH_ROWS)
        rows_written, output_bytes = 0, 0
        from sql_utils import statement as sql_text
        schema = "public" if engine.dialect.name == "postgresql" else None
        target = f"{_q(schema)}.{_q(output_table)}" if schema else _q(output_table)
        with engine.begin() as connection:
            connection.exec_driver_sql(
                f"CREATE TABLE {target} (group_value text, is_missing boolean, "
                "row_count bigint, percent double precision)")
            insert = sql_text(f"INSERT INTO {target} "
                              "(group_value, is_missing, row_count, percent) "
                              "VALUES (:group_value, :is_missing, :row_count, :percent)")
            for batch in reader:
                output_bytes += int(batch.nbytes)
                _actual_budget(scan_bytes + output_bytes)
                items = []
                for row in batch.to_pylist():
                    group_value = row["group_value"]
                    row_count = row["row_count"]
                    is_missing = row["is_missing"]
                    count = int(row_count)
                    items.append({"group_value": group_value,
                                  "is_missing": bool(is_missing),
                                  "row_count": count,
                                  "percent": (count / total * 100) if total else 0.0})
                if items:
                    connection.execute(insert, items)
                    rows_written += len(items)
        return {"input_rows": total, "rows": rows_written,
                "output_table": output_table}
    finally:
        con.close()


def _finite(value):
    if value is None:
        return None
    converted = float(value)
    return round(converted, 6) if math.isfinite(converted) else None


def export_frame(source: dict, filters: list[dict], max_rows: int) -> pd.DataFrame:
    _budget(int(source.get("scan_bytes") or os.path.getsize(source["path"])))
    where, params = _where(filters, column_types(source))
    relation = _q(source.get("table", "data"))
    con = _connect(source["path"], read_only=True)
    try:
        frame = con.execute(
            f"SELECT * FROM {relation} AS src WHERE {where} LIMIT ?",
            [*params, max_rows]).df()
        return frame
    finally:
        con.close()


_EXPORT_OPTIONS = {
    "tsv": "FORMAT CSV, HEADER, DELIMITER '\t'",
    "tsv.gz": "FORMAT CSV, HEADER, DELIMITER '\t', COMPRESSION 'gzip'",
    "json": "FORMAT JSON, ARRAY true",
    "parquet": "FORMAT PARQUET",
    "duckdb": "DUCKDB",
}


@_bounded_materialization
def export_tsv(source: dict, filters: list[dict], max_rows: int, format: str = "tsv") -> str:
    if format not in _EXPORT_OPTIONS:
        raise ValueError("Unsupported export format.")
    _budget(int(source.get("scan_bytes") or os.path.getsize(source["path"])))
    where, params = _where(filters, column_types(source))
    relation = _q(source.get("table", "data"))
    fd, path = tempfile.mkstemp(prefix="export-", suffix="." + format, dir=_ROOT)
    os.close(fd)
    con = None
    try:
        if format == "duckdb":
            os.unlink(path)
            con = _configure(duckdb.connect(path), path + ".tmp")
            con.execute(f"ATTACH {_lit(source['path'])} AS input_db (READ_ONLY)")
            relation = f"input_db.main.{relation}"
        else:
            con = _connect(source["path"], read_only=True)
        count = con.execute(
            f"SELECT count(*) FROM (SELECT 1 FROM {relation} AS src WHERE {where} LIMIT {int(max_rows) + 1})", params).fetchone()[0]
        if count > max_rows:
            raise OperationTooLarge(
                f"This export matches more than {max_rows:,} rows. Narrow the filters before downloading.")
        if format == "duckdb":
            con.execute(f"CREATE TABLE data AS SELECT * FROM {relation} AS src WHERE {where}", params)
        else:
            con.execute(
                f"COPY (SELECT * FROM {relation} AS src WHERE {where}) "
                f"TO {_lit(path)} ({_EXPORT_OPTIONS[format]})", params)
        con.close()
        con = None
        return path
    except BaseException:
        try:
            if con is not None:
                con.close()
        finally:
            remove_file(path)
        raise


@_bounded_materialization
def export_dataframe(frame: pd.DataFrame, format: str) -> str:
    if format not in _EXPORT_OPTIONS:
        raise ValueError("Unsupported export format.")
    if len({str(name).casefold() for name in frame.columns}) != len(frame.columns):
        raise ValueError("Export requires column names that are unique ignoring case.")
    fd, path = tempfile.mkstemp(prefix="export-", suffix="." + format, dir=_ROOT)
    os.close(fd)
    con = None
    try:
        if format == "duckdb":
            os.unlink(path)
            con = _configure(duckdb.connect(path), path + ".tmp")
        else:
            con = _configure(duckdb.connect(), path + ".tmp")
        con.register("_studio_export", frame)
        if format == "duckdb":
            con.execute("CREATE TABLE data AS SELECT * FROM _studio_export")
        else:
            con.execute(f"COPY _studio_export TO {_lit(path)} ({_EXPORT_OPTIONS[format]})")
        con.close()
        con = None
        return path
    except BaseException:
        try:
            if con is not None:
                con.close()
        finally:
            remove_file(path)
        raise
