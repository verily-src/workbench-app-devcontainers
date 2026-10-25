from __future__ import annotations

import math
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

import duck
import db
from sql_utils import statement as text

MAX_OPERATION_BYTES = 1_000_000_000_000
LARGE_OPERATION_BYTES = 10_000_000_000
PAGE_SIZE_MAX = 1000
_BATCH_ROWS = 2048
_ROOT = Path(tempfile.gettempdir()) / "cohort-studio-disk"
_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
_LOCK = threading.RLock()


class OperationTooLarge(ValueError):
    pass


class SourceSizeUnknown(ValueError):
    pass


def _q(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _lit(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _new_path() -> str:
    fd, path = tempfile.mkstemp(prefix="dataset-", suffix=".duckdb", dir=_ROOT)
    os.close(fd)
    os.remove(path)
    return path


def _configure(con, temp_directory: str | Path | None = None):
    try:
        con.execute("SET memory_limit = '2GB'")
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
    if isinstance(path, str) and path.startswith(str(_ROOT) + os.sep):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


def _budget(estimated_bytes: int, materialized_bytes: int = 0):
    estimate = int(estimated_bytes) + int(materialized_bytes)
    if estimate > MAX_OPERATION_BYTES:
        raise OperationTooLarge(
            "This operation is estimated to scan or materialize more than 1 TB. "
            "Reduce the source or split the work before opening it.")
    return estimate


def _actual_budget(total: int):
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

    filename = _validate_relative_key(filename)
    uri = db.resolve_s3_uri(resource_id).rstrip("/") + "/" + filename
    parsed = urlsplit(uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError("S3 resource did not resolve to an S3 object.")
    region = duck.DEFAULT_REGION
    session = boto3.Session(profile_name=resource_id, region_name=region)
    return session.client("s3", region_name=region), parsed.netloc, parsed.path.lstrip("/"), uri, region


def _object_size(resource_id: str, filename: str) -> tuple[int, str, str, bool]:
    filename = _validate_relative_key(filename)
    client, bucket, key, uri, region = _s3_client(resource_id, filename)
    try:
        size = int(client.head_object(Bucket=bucket, Key=key)["ContentLength"])
    except Exception as exc:
        raise SourceSizeUnknown(
            "The S3 object size could not be checked, so Studio cannot safely load it.") from exc
    if size < 0:
        raise SourceSizeUnknown("The S3 object size is not available.")
    _budget(size, size)
    return size, uri, region


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
        return con.execute(f"SELECT * FROM {_q(table)} LIMIT {int(limit)}").df()
    finally:
        con.close()


def profile_columns(source: dict, profiles: list[dict]) -> list[dict]:
    con = _connect(source["path"], read_only=True)
    relation = _q(source.get("table", "data"))
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
        elif kind == "categorical":
            values_alias = f"_studio_values_{index}"
            expressions.append(
                f"APPROX_TOP_K(CAST({col} AS VARCHAR), 50) AS {_q(values_alias)}")
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
            elif entry.get("filter_kind") == "categorical":
                _, values_alias = result_slots[index]
                entry["values"] = [str(value) for value in
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
            if conn.dialect.name == "postgresql":
                conn.exec_driver_sql("SET TRANSACTION READ ONLY")
                conn.exec_driver_sql("SET LOCAL statement_timeout = 15000")
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
    return {**live_source, "estimated_bytes": estimate,
            "large_warning": estimate >= LARGE_OPERATION_BYTES}


def guard_live_query(live_source: dict, charts: list[dict],
                     entity_column: str | None = None) -> int:
    estimate = int(live_source.get("estimated_bytes") or
                   _estimate_live_bytes(live_source))
    scans = 3 + (2 if entity_column else 0)
    for chart in charts:
        scans += {"bar": 4, "histogram": 5, "scatter": 1,
                  "heatmap": 1}.get(chart.get("kind"), 1)
    return _budget(estimate * scans)


def guard_live_join(live_sources: list[dict], output_source: dict) -> dict:
    scan_bytes = sum(int(source.get("estimated_bytes") or
                         _estimate_live_bytes(source)) for source in live_sources)
    output_bytes = _estimate_live_bytes(output_source)
    total = _budget(scan_bytes, output_bytes)
    return {"estimated_bytes": total,
            "large_warning": total >= LARGE_OPERATION_BYTES,
            "complete_source": True}


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
            if conn.dialect.name == "postgresql":
                conn.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                conn.exec_driver_sql("SET LOCAL statement_timeout = 120000")
            conn = conn.execution_options(stream_results=True,
                                          yield_per=_BATCH_ROWS)
            result = conn.execute(sql, live_source.get("params", {}))
            physical_columns = list(result.keys())
            frame = dataset["df"].iloc[:0].copy()
            con.register("_studio_schema", frame)
            con.execute(f"CREATE TABLE {_q(table)} AS SELECT * FROM _studio_schema")
            con.unregister("_studio_schema")
            total_bytes, rows = 0, 0
            while records := result.fetchmany(_BATCH_ROWS):
                batch = pd.DataFrame.from_records(records, columns=physical_columns)
                batch = batch.rename(columns=physical_to_logical)
                batch = batch.reindex(columns=logical_columns)
                batch_bytes = int(batch.memory_usage(index=False, deep=True).sum())
                total_bytes += batch_bytes
                _actual_budget(budget_used + estimate + total_bytes)
                con.register("_studio_live_batch", batch)
                con.execute(f"INSERT INTO {_q(table)} SELECT * FROM _studio_live_batch")
                con.unregister("_studio_live_batch")
                rows += len(batch)
            transaction.commit()
            return rows, estimate + total_bytes
        except Exception:
            transaction.rollback()
            raise


def _frame_bytes(frame: pd.DataFrame) -> int:
    return max(1, int(frame.memory_usage(index=False, deep=True).sum()))


def _duckdb_estimate(con, sql: str, avg_width: int) -> int | None:
    plan = "\n".join(str(row[1]) for row in con.execute(f"EXPLAIN {sql}").fetchall())
    matches = re.findall(r"~([0-9,]+) rows", plan)
    if not matches:
        return None
    rows = max(int(value.replace(",", "")) for value in matches)
    return rows * max(1, avg_width)


def _stream_duck_query(reader_con, writer_con, sql: str, table: str,
                       budget_used: int) -> tuple[int, int]:
    reader = reader_con.execute(sql).to_arrow_reader(_BATCH_ROWS)
    temp_name = "_studio_arrow_batch"
    schema = reader.schema
    writer_con.register(temp_name, schema.empty_table())
    writer_con.execute(f"CREATE TABLE {_q(table)} AS SELECT * FROM {temp_name}")
    writer_con.unregister(temp_name)
    row_count, bytes_written = 0, 0
    for batch in reader:
        bytes_written += int(batch.nbytes)
        _actual_budget(budget_used + bytes_written)
        writer_con.register(temp_name, batch)
        writer_con.execute(f"INSERT INTO {_q(table)} SELECT * FROM {temp_name}")
        writer_con.unregister(temp_name)
        row_count += batch.num_rows
    return row_count, bytes_written


def run_join(plan: dict) -> dict:
    datasets = [plan["base"]] + [step["ds"] for step in plan["steps"]]
    source_estimates = []
    for dataset in datasets:
        disk = dataset.get("disk_source")
        live = dataset.get("live_source")
        if disk:
            estimate = max(1, int(disk.get("estimated_bytes") or 0),
                           int(disk.get("scan_bytes") or 0),
                           os.path.getsize(disk["path"]))
        elif live:
            estimate = _estimate_live_bytes(live)
        else:
            estimate = _frame_bytes(dataset["df"])
        source_estimates.append(estimate)
    _budget(sum(source_estimates), sum(source_estimates))

    path = _new_path()
    writer = _connect(path)
    reader = _connect(path)
    try:
        relations, row_counts = {}, {}
        attached = {}
        budget_used = sum(source_estimates)
        for index, dataset in enumerate(datasets):
            key = id(dataset)
            if key in relations:
                continue
            disk = dataset.get("disk_source")
            live = dataset.get("live_source")
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
                rows, consumed = stage_live(writer, live, dataset, table, budget_used)
                budget_used += max(0, consumed - source_estimates[index])
                relation = _q(table)
            else:
                table = f"source_{index}"
                writer.register("_studio_frame", dataset["df"])
                writer.execute(f"CREATE TABLE {_q(table)} AS SELECT * FROM _studio_frame")
                writer.unregister("_studio_frame")
                relation, rows = _q(table), len(dataset["df"])
            relations[key], row_counts[key] = relation, rows

        current = relations[id(plan["base"])]
        before = row_counts[id(plan["base"])]
        step_stats, notes = [], []
        for step in plan["steps"]:
            right = relations[id(step["ds"])]
            sql = _join_step_sql(step, current, right)
            width = max(1, int(sum(_frame_bytes(ds["df"]) / max(1, len(ds["df"]))
                                   for ds in [plan["base"], step["ds"]])))
            estimate = _duckdb_estimate(reader, sql, width)
            if estimate is not None:
                _budget(budget_used, estimate)
            name = f"step_{step['no']}"
            rows, materialized = _stream_duck_query(
                reader, writer, sql, name, budget_used)
            budget_used += materialized
            growth = round(rows / before, 2) if before else None
            step_stats.append({"right_rows": row_counts[id(step["ds"])],
                               "rows": rows, "truncated": False,
                               "rows_before": before, "growth": growth,
                               "fanout": growth is not None and growth > 2.0})
            notes.extend(f"step {step['no']}: {note}" for note in step["notes"])
            current, before = _q(name), rows
        preview = reader.execute(
            f"SELECT * FROM {current} LIMIT 100000").df()
        stats = {"engine": "duckdb", "base_rows": row_counts[id(plan["base"])],
                 "steps": step_stats, "notes": notes, "capped_inputs": [],
                 "rows": before, "total_rows": before, "truncated": False,
                 "estimated_bytes": budget_used,
                 "large_warning": budget_used >= LARGE_OPERATION_BYTES,
                 "complete_source": True,
                 "materialized_bytes": budget_used - sum(source_estimates)}
        return {"df": preview, "stats": stats,
                "disk_source": {"path": path, "table": current.strip('"'),
                                "columns": list(preview.columns), "rows": before,
                                "estimated_bytes": budget_used,
                                "scan_bytes": os.path.getsize(path),
                                "large_warning": budget_used >= LARGE_OPERATION_BYTES}}
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


def derive(source: dict, spec: dict) -> tuple[pd.DataFrame, dict]:
    from source_models import DerivedSpec

    spec = DerivedSpec.model_validate(spec).model_dump(exclude_none=True)
    name = spec["name"].strip()
    columns = list(source["columns"])
    if spec["op"] == "bin":
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
    select = [f"l.{_q(name)}" for name in step["left"]]
    select.extend(f"r.{_q(source)} AS {_q(target)}" for source, target in step["cols"])
    condition = " AND ".join(on)
    if step["how"] in ("semi", "anti"):
        negative = "NOT " if step["how"] == "anti" else ""
        return (f"SELECT {', '.join(select)} FROM {left} AS l WHERE {negative}EXISTS "
                f"(SELECT 1 FROM {right} AS r WHERE {condition})")
    join = {"inner": "INNER", "left": "LEFT", "right": "RIGHT", "full": "FULL OUTER"}[step["how"]]
    return (f"SELECT {', '.join(select)} FROM {left} AS l {join} JOIN "
            f"{right} AS r ON {condition}")


def open_s3(ref: dict) -> tuple[pd.DataFrame, dict]:
    resource_id, filename = ref["resource_id"], ref["table"]
    size, uri, region = _object_size(resource_id, filename)
    path = _new_path()
    source_con = _configure(duck._connect(resource_id, region=region))
    try:
        sql = duck._reader_sql(uri, hive=_has_hive_path(uri))
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


def _where(filters: list[dict], columns: list[str]):
    clauses, params = [], []
    for item in filters:
        name = item.get("column")
        if name not in columns:
            raise ValueError(f"Unknown filter column: {name!r}.")
        col = f"src.{_q(name)}"
        if item.get("kind") == "categorical" and item.get("values"):
            vals = [str(value) for value in item["values"]]
            clauses.append(f"CAST({col} AS VARCHAR) IN ({', '.join('?' for _ in vals)})")
            params.extend(vals)
        elif item.get("kind") == "range" and item.get("min") is not None and item.get("max") is not None:
            low, high = float(item["min"]), float(item["max"])
            if not math.isfinite(low) or not math.isfinite(high):
                raise ValueError("Range filter values must be finite.")
            clauses.append(f"TRY_CAST({col} AS DOUBLE) BETWEEN ? AND ?")
            params.extend([low, high])
    return " AND ".join(clauses) if clauses else "TRUE", params


def _aggregate(con, relation: str, where: str, params: list,
               charts: list[dict], columns: list[str]):
    out = []
    for chart in charts:
        kind, x, y = chart.get("kind"), chart.get("x"), chart.get("y")
        if x not in columns or (y and y not in columns):
            raise ValueError("Unknown chart column.")
        qx = f"src.{_q(x)}"
        if kind == "bar":
            counts = con.execute(
                f"SELECT CAST({qx} AS VARCHAR), COUNT(*) FROM {relation} AS src "
                f"WHERE {qx} IS NOT NULL GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 12").fetchall()
            selected = {}
            if counts:
                values = [str(row[0]) for row in counts]
                selected = dict(con.execute(
                    f"SELECT CAST({qx} AS VARCHAR), COUNT(*) FROM {relation} AS src "
                    f"WHERE ({where}) AND CAST({qx} AS VARCHAR) IN "
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
                f"SELECT CAST({qx} AS VARCHAR), CAST({qy} AS VARCHAR), COUNT(*) "
                f"FROM {relation} AS src WHERE ({where}) AND {qx} IS NOT NULL "
                f"AND {qy} IS NOT NULL GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 400", params).fetchall()
            out.append({"kind": kind, "x": x, "y": y, "data": rows,
                        "sampled": len(rows) == 400})
        else:
            out.append({"kind": kind, "x": x, "data": []})
    return out


def query(source: dict, filters: list[dict], charts: list[dict], page: int,
          page_size: int, entity_column: str | None = None) -> dict:
    if not isinstance(page, int) or page < 0:
        raise ValueError("Page must be a non-negative integer.")
    if not isinstance(page_size, int) or not 1 <= page_size <= PAGE_SIZE_MAX:
        raise ValueError(f"Page size must be from 1 to {PAGE_SIZE_MAX:,}.")
    columns = source["columns"]
    if entity_column is not None and entity_column not in columns:
        raise ValueError(f"Unknown entity column: {entity_column!r}.")
    scans = 3 + (2 if entity_column else 0)
    for chart in charts:
        scans += {"bar": 4, "histogram": 5, "scatter": 1,
                  "heatmap": 1}.get(chart.get("kind"), 1)
    _budget(int(source.get("scan_bytes") or os.path.getsize(source["path"])) * scans)
    where, params = _where(filters, columns)
    relation = f"{_q(source.get('table', 'data'))}"
    con = _connect(source["path"], read_only=True)
    try:
        total = int(con.execute(f"SELECT COUNT(*) FROM {relation}").fetchone()[0])
        filtered = int(con.execute(
            f"SELECT COUNT(*) FROM {relation} AS src WHERE {where}", params).fetchone()[0])
        charts_out = _aggregate(con, relation, where, params, charts, columns)
        frame = con.execute(
            f"SELECT * FROM {relation} AS src WHERE {where} LIMIT ? OFFSET ?",
            [*params, page_size, page * page_size]).df()
        result = {"total": total, "filtered": filtered, "charts": charts_out,
                  "rows": {"page": page, "page_size": page_size,
                           "columns": columns,
                           "data": frame.astype(object).where(frame.notna(), None).values.tolist()},
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
    where, params = _where(filters, columns)
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
            filters_b: list[dict], b_is_rest: bool = False) -> dict:
    import compare as compare_module
    from scipy import stats

    columns = source["columns"]
    a_where, a_params = _where(filters_a, columns)
    if b_is_rest:
        b_where, b_params = f"NOT COALESCE(({a_where}), FALSE)", a_params
    else:
        b_where, b_params = _where(filters_b, columns)
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


def count_by_group(source: dict, group_by: str, filters: list[dict],
                   engine, output_table: str) -> dict:
    if group_by not in source["columns"]:
        raise ValueError(f"Unknown column: {group_by}")
    scan_bytes = int(source.get("scan_bytes") or os.path.getsize(source["path"]))
    _budget(scan_bytes, scan_bytes)
    where, params = _where(filters, source["columns"])
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
    where, params = _where(filters, source["columns"])
    relation = _q(source.get("table", "data"))
    con = _connect(source["path"], read_only=True)
    try:
        frame = con.execute(
            f"SELECT * FROM {relation} AS src WHERE {where} LIMIT ?",
            [*params, max_rows]).df()
        return frame
    finally:
        con.close()


def export_tsv(source: dict, filters: list[dict], max_rows: int) -> str:
    _budget(int(source.get("scan_bytes") or os.path.getsize(source["path"])))
    where, params = _where(filters, source["columns"])
    relation = _q(source.get("table", "data"))
    fd, path = tempfile.mkstemp(prefix="export-", suffix=".tsv", dir=_ROOT)
    os.close(fd)
    con = _connect(source["path"], read_only=True)
    try:
        con.execute(
            f"COPY (SELECT * FROM {relation} AS src WHERE {where} LIMIT {int(max_rows)}) "
            f"TO {_lit(path)} (FORMAT CSV, HEADER, DELIMITER '\t')", params)
        return path
    except Exception:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        raise
    finally:
        con.close()
