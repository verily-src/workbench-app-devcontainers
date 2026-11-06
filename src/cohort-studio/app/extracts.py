"""Extracts: an opened dataset (usually a join) saved as a table in a writable
Aurora/PostgreSQL database, with its source recipe so it can be refreshed.

Every row is written; there is no row cap. A result that already lives in the
target database (a same-database live join) is written with CREATE TABLE AS
inside the database. Anything else (DuckDB-backed joins, other databases,
in-memory frames) is streamed in batches. Rows go into a temporary table that
replaces the extract in one transaction, so a failed refresh keeps the old one.

Each extract is recorded in ``public._studio_extracts`` (table name, title,
recipe, rows, timestamps). A plain "Save to Aurora" over the same name removes
the record, because that table no longer matches the recipe.
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Callable, Iterable, Iterator

import pandas as pd
import sqlalchemy as sa

import database as db
import query_cancellation
from source_models import source_dict
from sql_utils import statement as text

REGISTRY = "_studio_extracts"
TMP_PREFIX = "_studio_x_"
TIMEOUT_MS = 3_600_000
BATCH_ROWS = 50_000
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


class ExtractExists(ValueError):
    """The name belongs to a table that is not an extract."""


class NotRefreshable(ValueError):
    pass


def _q(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def validate_name(table: str) -> str:
    if not isinstance(table, str) or not _NAME.match(table) or table.startswith("_studio_"):
        raise ValueError(f"Invalid table name {table!r}: use letters, digits and underscores "
                         "(up to 63, not starting with _studio_).")
    return table


def _registry_exists(conn) -> bool:
    return conn.execute(text("SELECT to_regclass(:name) IS NOT NULL"),
                        {"name": f"public.{REGISTRY}"}).scalar_one()


def _ensure_registry(conn) -> None:
    conn.exec_driver_sql(
        f"CREATE TABLE IF NOT EXISTS public.{_q(REGISTRY)} ("
        "table_name text PRIMARY KEY, title text NOT NULL, recipe jsonb, "
        "row_count bigint NOT NULL, created_at timestamptz NOT NULL, "
        "refreshed_at timestamptz NOT NULL)")


def _entry(conn, table: str) -> dict | None:
    if not _registry_exists(conn):
        return None
    row = conn.execute(text(
        f"SELECT title, recipe::text, row_count, created_at, refreshed_at "
        f"FROM public.{_q(REGISTRY)} WHERE table_name = :table"), {"table": table}).one_or_none()
    if row is None:
        return None
    title, recipe, rows, created, refreshed = row
    return {"table": table, "title": title, "recipe": json.loads(recipe) if recipe else None,
            "rows": int(rows), "created_at": created.isoformat(),
            "refreshed_at": refreshed.isoformat()}


def public_info(entry: dict | None) -> dict | None:
    if entry is None:
        return None
    return {k: v for k, v in entry.items() if k != "recipe"} | {
        "refreshable": entry.get("recipe") is not None}


def info(resource_id: str, table: str) -> dict | None:
    with db.get_engine_for_resource(resource_id).connect() as conn:
        return public_info(_entry(conn, table))


def forget(resource_id: str, table: str) -> None:
    """Drop the extract record after something else overwrote the table."""
    with db.get_engine_for_resource(resource_id).begin() as conn:
        if _registry_exists(conn):
            conn.execute(text(f"DELETE FROM public.{_q(REGISTRY)} WHERE table_name = :table"),
                         {"table": table})


def _table_exists(conn, table: str) -> bool:
    return conn.execute(text("SELECT to_regclass(:name) IS NOT NULL"),
                        {"name": f"public.{_q(table)}"}).scalar_one()


# ---- Writing rows -----------------------------------------------------------

def _write_in_database(engine, live: dict, tmp: str) -> int:
    import disk_data
    import materialized_sources

    columns = live.get("columns")
    if not isinstance(columns, dict) or not columns:
        raise ValueError("The joined result has no columns.")
    with engine.begin() as conn, query_cancellation.postgres_connection(conn):
        conn.exec_driver_sql(f"SET LOCAL statement_timeout = {TIMEOUT_MS}")
        trusted = isinstance(live, disk_data.CompiledSourceQuery)
        sql = materialized_sources._compiled_query(
            conn, disk_data._validated_live_sql(live), live.get("params") or {}, trusted=trusted)
        projection = ", ".join(f"live.{_q(pg)} AS {_q(logical)}" for logical, pg in columns.items())
        conn.exec_driver_sql(
            f"CREATE TABLE public.{_q(tmp)} AS SELECT {projection} FROM ({sql}) AS live")
        return int(conn.execute(text(f"SELECT count(*) FROM public.{_q(tmp)}")).scalar_one())


# Column types come from the source, not from pandas inference, so nullable
# integers stay exact (no float64) and every batch keeps the same types.
_PG_TYPES = {16: sa.Boolean(), 20: sa.BigInteger(), 21: sa.SmallInteger(), 23: sa.Integer(),
             700: sa.REAL(), 701: sa.Float(53), 1700: sa.Numeric(), 1082: sa.Date(),
             1114: sa.DateTime(), 1184: sa.DateTime(timezone=True), 1083: sa.Time(),
             2950: sa.Uuid(as_uuid=False)}


def _arrow_sql_type(t):
    import pyarrow as pa
    import pyarrow.types as pt
    if pt.is_boolean(t):
        return sa.Boolean()
    if pt.is_integer(t):
        return sa.SmallInteger() if t.bit_width <= 8 else sa.Integer() if t.bit_width <= 16 \
            else sa.BigInteger() if t.bit_width <= 32 or pt.is_signed_integer(t) else sa.Numeric(20, 0)
    if pt.is_floating(t):
        return sa.REAL() if t.bit_width <= 32 else sa.Float(53)
    if pt.is_decimal(t):
        return sa.Numeric(t.precision, t.scale)
    if pt.is_date(t):
        return sa.Date()
    if pt.is_timestamp(t):
        return sa.DateTime(timezone=t.tz is not None)
    if pt.is_time(t):
        return sa.Time()
    return sa.Text()


def _nullable_pandas(t):
    """Arrow → pandas dtypes that keep NULLs without turning ints into floats."""
    import pyarrow as pa
    return {pa.int8(): pd.Int8Dtype(), pa.int16(): pd.Int16Dtype(), pa.int32(): pd.Int32Dtype(),
            pa.int64(): pd.Int64Dtype(), pa.uint8(): pd.UInt8Dtype(), pa.uint16(): pd.UInt16Dtype(),
            pa.uint32(): pd.UInt32Dtype(), pa.uint64(): pd.UInt64Dtype(),
            pa.bool_(): pd.BooleanDtype()}.get(t)


def _typed(frame: pd.DataFrame, sql_types: dict) -> pd.DataFrame:
    frame.attrs["sql_types"] = sql_types
    return frame


def _live_frames(live: dict, batch: int) -> Iterator[pd.DataFrame]:
    """Stream a live query from its own database (server-side cursor)."""
    columns = live["columns"]
    select = ", ".join(f"live.{_q(pg)} AS {_q(logical)}" for logical, pg in columns.items())
    engine = db.get_engine_for_resource(live["resource_id"])
    with engine.connect() as conn, query_cancellation.postgres_connection(conn):
        with conn.begin():
            conn.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            conn.exec_driver_sql("SET LOCAL search_path = pg_catalog")
            conn.exec_driver_sql(f"SET LOCAL statement_timeout = {TIMEOUT_MS}")
            result = conn.execution_options(stream_results=True, yield_per=batch).execute(
                text(f"SELECT {select} FROM ({live['sql']}) AS live"), dict(live.get("params") or {}))
            description = result.cursor.description or []
            sql_types = {name: _PG_TYPES.get(getattr(col, "type_code", None), sa.Text())
                         for name, col in zip(columns, description)}
            yielded = False
            for part in result.partitions(batch):
                yielded = True
                # object dtype: values reach the database exactly as read.
                yield _typed(pd.DataFrame([tuple(r) for r in part], columns=list(columns),
                                          dtype=object), sql_types)
            if not yielded:
                yield _typed(pd.DataFrame(columns=list(columns), dtype=object), sql_types)


def _disk_frames(source: dict, batch: int) -> Iterator[pd.DataFrame]:
    import os
    import disk_data

    disk_data._budget(int(source.get("scan_bytes") or os.path.getsize(source["path"])))
    con = disk_data._connect(source["path"], read_only=True)
    try:
        with query_cancellation.duckdb_connection(con):
            reader = con.execute(
                f"SELECT * FROM {disk_data._q(source.get('table', 'data'))}").to_arrow_reader(batch)
            sql_types = {f.name: _arrow_sql_type(f.type) for f in reader.schema}
            yielded = False
            for record_batch in reader:
                yielded = True
                yield _typed(record_batch.to_pandas(types_mapper=_nullable_pandas), sql_types)
            if not yielded:
                yield _typed(reader.schema.empty_table().to_pandas(types_mapper=_nullable_pandas),
                             sql_types)
    finally:
        con.close()


def _frame_batches(df: pd.DataFrame, batch: int) -> Iterator[pd.DataFrame]:
    if df.empty:
        yield df
        return
    for start in range(0, len(df), batch):
        yield df.iloc[start:start + batch]


def frames(ds: dict, batch: int = BATCH_ROWS) -> Iterator[pd.DataFrame]:
    """Every row of an opened dataset, in batches, ignoring its tab filters."""
    if ds.get("disk_source"):
        return _disk_frames(ds["disk_source"], batch)
    if ds.get("live_source"):
        return _live_frames(ds["live_source"], batch)
    return _frame_batches(ds["df"], batch)


def _write_batches(engine, parts: Iterable[pd.DataFrame], tmp: str,
                   progress: Callable[[int], None] | None = None) -> int:
    total = 0
    first = True
    for part in parts:
        query_cancellation.check()
        ncols = max(1, len(part.columns))
        with engine.begin() as conn, query_cancellation.postgres_connection(conn):
            part.to_sql(tmp, conn, schema="public", if_exists="fail" if first else "append",
                        index=False, chunksize=max(1, min(5000, 60000 // ncols)), method="multi",
                        dtype=part.attrs.get("sql_types") or None)
        first = False
        total += len(part)
        if progress:
            progress(total)
    return total


def _drop_quietly(engine, tmp: str) -> None:
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(f"DROP TABLE IF EXISTS public.{_q(tmp)}")
    except Exception:
        pass


def write(ds: dict, resource_id: str, table: str, title: str, recipe: dict | None,
          replace: bool = False, progress: Callable[[int], None] | None = None) -> dict:
    """Write every row of ``ds`` to ``public.<table>`` and record the extract.

    An existing table with this name is replaced only when it is already an
    extract or ``replace`` is set; otherwise ``ExtractExists`` is raised.
    """
    validate_name(table)
    recipe = source_dict(recipe) if recipe else None
    engine = db.get_engine_for_resource(resource_id)
    with engine.connect() as conn:
        existing = _entry(conn, table)
        if existing is None and not replace and _table_exists(conn, table):
            raise ExtractExists(
                f"A table named {table} already exists in {resource_id}. Choose another name.")
    tmp = f"{TMP_PREFIX}{uuid.uuid4().hex[:24]}"
    live = ds.get("live_source")
    try:
        if live and live.get("resource_id") == resource_id:
            rows = _write_in_database(engine, live, tmp)
        else:
            rows = _write_batches(engine, frames(ds), tmp, progress)
        query_cancellation.check()  # a cancelled job must not replace the extract
        with engine.begin() as conn:
            _ensure_registry(conn)
            conn.exec_driver_sql(f"DROP TABLE IF EXISTS public.{_q(table)}")
            conn.exec_driver_sql(f"ALTER TABLE public.{_q(tmp)} RENAME TO {_q(table)}")
            now = conn.execute(text("SELECT CURRENT_TIMESTAMP")).scalar_one()
            conn.execute(text(
                f"INSERT INTO public.{_q(REGISTRY)} "
                "(table_name, title, recipe, row_count, created_at, refreshed_at) "
                "VALUES (:table, :title, CAST(:recipe AS jsonb), :rows, :now, :now) "
                "ON CONFLICT (table_name) DO UPDATE SET title = EXCLUDED.title, "
                "recipe = EXCLUDED.recipe, row_count = EXCLUDED.row_count, "
                "refreshed_at = EXCLUDED.refreshed_at"), {
                    "table": table, "title": (title or table)[:128],
                    "recipe": json.dumps(recipe) if recipe else None,
                    "rows": rows, "now": now})
            entry = _entry(conn, table)
    except Exception:
        _drop_quietly(engine, tmp)
        raise
    return public_info(entry)


def refresh(resource_id: str, table: str, open_recipe: Callable[[dict], dict],
            get_dataset: Callable[[str], dict], close_dataset: Callable[[str], None],
            progress: Callable[[int], None] | None = None) -> dict:
    """Rerun an extract's recipe and replace its rows."""
    validate_name(table)
    with db.get_engine_for_resource(resource_id).connect() as conn:
        entry = _entry(conn, table)
    if entry is None:
        raise LookupError(f"{table} is not an extract in {resource_id}.")
    if not entry.get("recipe"):
        raise NotRefreshable(f"{table} can't be refreshed: its inputs (for example an "
                             "uploaded file) can't be reopened.")
    opened = open_recipe(entry["recipe"])
    try:
        return write(get_dataset(opened["dataset_id"]), resource_id, table, entry["title"],
                     entry["recipe"], replace=True, progress=progress)
    finally:
        close_dataset(opened["dataset_id"])
