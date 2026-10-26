from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime

from sqlalchemy.engine import Connection
from sqlalchemy import bindparam
from sqlglot import exp, parse
from sqlglot.optimizer.scope import Scope, traverse_scope

import sql_source
from sql_utils import statement as text
from source_models import source_dict

REGISTRY = "_studio_materialized_sources"
REGISTRY_TABLE = REGISTRY
TABLE_PREFIX = "_studio_mv_"
TIMEOUT_MS = 300_000
LOCK_TIMEOUT_MS = 3_000
operation_lock = threading.RLock()
_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_TABLE_PATTERN = re.compile(r"^_studio_mv_[0-9a-f]{32}$")
_COLUMN_PATTERN = re.compile(r"^_c[0-9]{1,3}$")
_ALLOWED_TYPES = {
    "bool", "char", "bpchar", "varchar", "text", "name", "int2", "int4",
    "int8", "numeric", "float4", "float8", "date", "time", "timetz",
    "timestamp", "timestamptz", "interval", "uuid", "bytea", "json", "jsonb",
}
_BLOCKED_SCHEMAS = {"information_schema", "pg_catalog", "pg_toast", "pg_temp"}


def _q(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _prepare(conn: Connection, create_registry: bool = False,
             require_write: bool = False) -> None:
    if conn.dialect.name != "postgresql":
        raise ValueError("Materialized sources require Aurora PostgreSQL.")
    is_read_only = str(conn.exec_driver_sql("SHOW transaction_read_only").scalar_one()).lower() \
        in {"on", "true", "1"}
    if require_write and is_read_only:
        raise ValueError("Materialized sources require a read-write transaction.")
    conn.exec_driver_sql("SET LOCAL search_path = pg_catalog")
    conn.exec_driver_sql(f"SET LOCAL lock_timeout = {LOCK_TIMEOUT_MS}")
    conn.exec_driver_sql(f"SET LOCAL statement_timeout = {TIMEOUT_MS}")
    if create_registry:
        conn.exec_driver_sql(
            f"CREATE TABLE IF NOT EXISTS public.{_q(REGISTRY)} ("
            "materialized_id text PRIMARY KEY, resource_id text NOT NULL, "
            "physical_name text NOT NULL UNIQUE, recipe jsonb NOT NULL, "
            "columns jsonb NOT NULL, row_count bigint NOT NULL, "
            "created_at timestamptz NOT NULL, refreshed_at timestamptz NOT NULL)")
    elif not conn.exec_driver_sql(
            "SELECT pg_catalog.to_regclass('public._studio_materialized_sources') "
            "IS NOT NULL").scalar_one():
        raise ValueError("Materialized source registry is not available.")


def _ref(resource_id: str, materialized_id: str) -> dict:
    return {"kind": "materialized", "resource_id": resource_id,
            "materialized_id": materialized_id}


def _identifier(resource_id: str, materialized_id: str) -> str:
    if not isinstance(resource_id, str) or not resource_id:
        raise ValueError("Aurora resource is required.")
    if not isinstance(materialized_id, str) or not _ID_PATTERN.fullmatch(materialized_id):
        raise ValueError("Materialized source ID is invalid.")
    return f"{TABLE_PREFIX}{materialized_id}"


def _collect_relations(recipe: dict, resource_id: str,
                       conn: Connection) -> set[tuple[str, str]]:
    validated = source_dict(recipe)
    relations: set[tuple[str, str]] = set()
    has_join = False

    def visit(node: dict) -> None:
        nonlocal has_join
        kind = node["kind"]
        if kind in {"aurora", "postgres"}:
            if node["resource_id"] != resource_id:
                raise ValueError("Materialized joins must use one Aurora resource.")
            schema = node.get("schema") or "public"
            table = node["table"]
            if schema.casefold() in _BLOCKED_SCHEMAS or schema.casefold().startswith(("pg_temp", "pg_toast")):
                raise ValueError("System schemas cannot be materialized.")
            if table.startswith("_studio_"):
                raise ValueError("Workbench storage tables cannot be materialized as inputs.")
            relations.add((schema, table))
        elif kind == "sql":
            if node["resource_id"] != resource_id:
                raise ValueError("Materialized joins must use one Aurora resource.")
            query = sql_source.normalize(node["sql"])
            expressions = [item for item in parse(query, read="postgres") if item is not None]
            if len(expressions) != 1:
                raise ValueError("SQL source recipe is invalid.")
            statement = expressions[0]
            cte_tables = {
                id(table)
                for scope in traverse_scope(statement)
                for table in scope.tables
                if not table.db and isinstance(scope.sources.get(table.alias_or_name), Scope)
            }
            for table in statement.find_all(exp.Table):
                if id(table) in cte_tables:
                    continue
                schema = table.db
                if (not schema or schema.casefold() in _BLOCKED_SCHEMAS
                        or schema.casefold().startswith(("pg_temp", "pg_toast"))):
                    raise ValueError("Materialized SQL sources need schema-qualified tables.")
                if table.name.startswith("_studio_"):
                    raise ValueError("Workbench storage tables cannot be materialized as inputs.")
                relations.add((schema, table.name))
        elif kind == "omop_cohort":
            if node["resource_id"] != resource_id:
                raise ValueError("Materialized joins must use one Aurora resource.")
            import omop
            info = omop.detect(conn.engine)
            if info is None:
                raise ValueError("OMOP source was not found.")
            compiled = omop._prepare(conn, info, node["spec"])
            query, _ = omop._cohort_select(info, compiled)
            statement = parse(query, read="postgres")[0]
            for table in statement.find_all(exp.Table):
                if table.db:
                    relations.add((table.db, table.name))
        elif kind == "join":
            has_join = True
            visit(node["base"])
            for step in node["steps"]:
                visit(step["source"])
        elif kind == "derived":
            visit(node["base"])
        elif kind == "materialized":
            if node["resource_id"] != resource_id:
                raise ValueError("Materialized joins must use one Aurora resource.")
            _identifier(resource_id, node["materialized_id"])
            row = _row(conn, resource_id, node["materialized_id"])
            if row is None or not _TABLE_PATTERN.fullmatch(row[0]):
                raise ValueError("Materialized source reference was not found.")
            relations.add(("public", row[0]))
        else:
            raise ValueError("Only PostgreSQL-backed joins can be materialized.")

    visit(validated)
    if not has_join:
        raise ValueError("Only joined Aurora sources can be materialized.")
    if not relations:
        raise ValueError("Materialized source has no Aurora tables.")
    return relations


def _catalog_row(conn: Connection, schema: str, table: str):
    query = text(
        "WITH RECURSIVE rel_tree(oid) AS ("
        " SELECT c.oid FROM pg_catalog.pg_class c "
        " JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        " WHERE n.nspname = :schema AND c.relname = :table "
        " UNION ALL SELECT i.inhrelid FROM pg_catalog.pg_inherits i "
        " JOIN rel_tree p ON p.oid = i.inhparent) "
        "SELECT c.relkind, c.relrowsecurity OR c.relforcerowsecurity, "
        "tn.nspname, t.typname "
        "FROM rel_tree r JOIN pg_catalog.pg_class c ON c.oid = r.oid "
        "JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid "
        " AND a.attnum > 0 AND NOT a.attisdropped "
        "JOIN pg_catalog.pg_type t ON t.oid = a.atttypid "
        "JOIN pg_catalog.pg_namespace tn ON tn.oid = t.typnamespace")
    return conn.execute(query, {"schema": schema, "table": table}).all()


def _preflight(conn: Connection, recipe: dict, resource_id: str) -> None:
    for schema, table in _collect_relations(recipe, resource_id, conn):
        rows = _catalog_row(conn, schema, table)
        if not rows:
            raise ValueError(f"Materialized source relation {schema}.{table} is missing or empty.")
        relkinds = {row[0] for row in rows}
        if not relkinds.issubset({"r", "p", "m"}):
            raise ValueError(f"Materialized source relation {schema}.{table} must be a table.")
        if any(row[1] for row in rows):
            raise ValueError(f"Materialized source relation {schema}.{table} uses row-level security.")
        if any(row[2] != "pg_catalog" or row[3] not in _ALLOWED_TYPES for row in rows):
            raise ValueError(f"Materialized source relation {schema}.{table} has an unsupported column type.")


def _compiled_query(conn: Connection, source_sql: str, params: dict, trusted=False) -> str:
    if not isinstance(source_sql, str) or not source_sql.strip() or not isinstance(params, dict):
        raise ValueError("Live source query is invalid.")
    statement = text(source_sql)
    if params:
        if any(not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
               for key in params):
            raise ValueError("Live source parameters are invalid.")
    try:
        if params:
            statement = statement.bindparams(*[
                bindparam(key, value=value, type_=sql_source._literal_type(value))
                for key, value in params.items()])
        compiled = statement.compile(
            dialect=conn.dialect, compile_kwargs={"literal_binds": True})
    except Exception as exc:
        raise ValueError("Live source parameters cannot be safely materialized.") from exc
    return str(compiled) if trusted else sql_source.normalize(str(compiled))


def _row(conn: Connection, resource_id: str, materialized_id: str):
    _identifier(resource_id, materialized_id)
    return conn.execute(text(
        f"SELECT physical_name, recipe::text, columns::text, row_count, "
        f"created_at, refreshed_at FROM public.{_q(REGISTRY)} "
        "WHERE resource_id = :resource_id AND materialized_id = :materialized_id"),
        {"resource_id": resource_id, "materialized_id": materialized_id}).one_or_none()


def _metadata(resource_id: str, materialized_id: str, row) -> dict:
    if row is None:
        raise ValueError("Materialized source was not found.")
    physical_name, recipe, columns, row_count, created_at, refreshed_at = row
    if not _TABLE_PATTERN.fullmatch(physical_name):
        raise ValueError("Materialized source registry entry is invalid.")
    column_map = json.loads(columns)
    if not isinstance(column_map, dict) or not column_map:
        raise ValueError("Materialized source column metadata is invalid.")
    if any(not isinstance(name, str) or not name or not isinstance(physical, str)
           or not _COLUMN_PATTERN.fullmatch(physical) for name, physical in column_map.items()):
        raise ValueError("Materialized source column metadata is invalid.")
    return {"source_ref": _ref(resource_id, materialized_id),
            "materialized_id": materialized_id, "rows": int(row_count),
            "columns": column_map, "created_at": created_at.isoformat(),
            "refreshed_at": refreshed_at.isoformat(),
            "recipe": json.loads(recipe), "physical_name": physical_name}


def _resolved(conn: Connection, resource_id: str, materialized_id: str,
              row) -> dict:
    metadata = _metadata(resource_id, materialized_id, row)
    physical_name = metadata["physical_name"]
    columns = metadata["columns"]
    live_source = {"resource_id": resource_id,
                   "sql": (f"SELECT {', '.join(_q(value) for value in columns.values())} "
                           f"FROM public.{_q(physical_name)}"),
                   "params": {}, "columns": columns}
    import disk_data
    live_source = disk_data._compiled_source_query(metadata["source_ref"], live_source)
    return {**metadata, "live_source": live_source}


def create(conn: Connection, resource_id: str, live_source: dict,
           recipe: dict) -> dict:
    if live_source.get("resource_id") != resource_id:
        raise ValueError("Live source belongs to a different Aurora resource.")
    source_columns = live_source.get("columns")
    if not isinstance(source_columns, dict) or not source_columns or len(source_columns) > 200:
        raise ValueError("Live source must have between 1 and 200 columns.")
    if any(not isinstance(logical, str) or not logical or not isinstance(physical, str) or not physical
           for logical, physical in source_columns.items()):
        raise ValueError("Live source columns are invalid.")
    normalized_recipe = source_dict(recipe)
    _prepare(conn, create_registry=True, require_write=True)
    _preflight(conn, normalized_recipe, resource_id)
    materialized_id = uuid.uuid4().hex
    physical_name = f"{TABLE_PREFIX}{materialized_id}"
    columns = {logical: f"_c{index}" for index, logical in enumerate(source_columns)}
    projection = ", ".join(
        f"src.{_q(source_columns[logical])} AS {_q(physical)}"
        for logical, physical in columns.items())
    import disk_data
    trusted = isinstance(live_source, disk_data.CompiledSourceQuery)
    if trusted and source_dict(live_source.source_ref) != normalized_recipe:
        raise ValueError("Compiled source recipe does not match the saved source.")
    source_sql = _compiled_query(conn, disk_data._validated_live_sql(live_source),
                                 live_source.get("params") or {}, trusted=trusted)
    ddl = (f"CREATE MATERIALIZED VIEW public.{_q(physical_name)} AS "
           f"SELECT {projection} FROM ({source_sql}) AS src WITH DATA")
    conn.exec_driver_sql(ddl)
    row_count = int(conn.execute(text(
        f"SELECT COUNT(*) FROM public.{_q(physical_name)}")).scalar_one())
    now = conn.execute(text("SELECT CURRENT_TIMESTAMP")).scalar_one()
    conn.execute(text(
        f"INSERT INTO public.{_q(REGISTRY)} "
        "(materialized_id, resource_id, physical_name, recipe, columns, "
        "row_count, created_at, refreshed_at) "
        "VALUES (:id, :resource_id, :physical_name, CAST(:recipe AS jsonb), "
        "CAST(:columns AS jsonb), :row_count, :created_at, :refreshed_at)"), {
            "id": materialized_id, "resource_id": resource_id,
            "physical_name": physical_name,
            "recipe": json.dumps(normalized_recipe), "columns": json.dumps(columns),
            "row_count": row_count, "created_at": now, "refreshed_at": now,
        })
    return _resolved(conn, resource_id, materialized_id,
                     _row(conn, resource_id, materialized_id))


def resolve(conn: Connection, resource_id: str, materialized_id: str) -> dict:
    _prepare(conn)
    return _resolved(conn, resource_id, materialized_id,
                     _row(conn, resource_id, materialized_id))


def refresh(conn: Connection, resource_id: str, materialized_id: str) -> dict:
    _prepare(conn, require_write=True)
    current = _metadata(resource_id, materialized_id,
                        _row(conn, resource_id, materialized_id))
    _preflight(conn, current["recipe"], resource_id)
    target = f"public.{_q(current['physical_name'])}"
    conn.exec_driver_sql(f"REFRESH MATERIALIZED VIEW {target}")
    row_count = int(conn.execute(text(f"SELECT COUNT(*) FROM {target}")).scalar_one())
    refreshed_at = conn.execute(text("SELECT CURRENT_TIMESTAMP")).scalar_one()
    conn.execute(text(
        f"UPDATE public.{_q(REGISTRY)} SET row_count = :row_count, "
        "refreshed_at = :refreshed_at WHERE materialized_id = :id "
        "AND resource_id = :resource_id"), {
            "row_count": row_count, "refreshed_at": refreshed_at,
            "id": materialized_id, "resource_id": resource_id,
        })
    return _resolved(conn, resource_id, materialized_id,
                     _row(conn, resource_id, materialized_id))


def drop(conn: Connection, resource_id: str, materialized_id: str) -> None:
    _prepare(conn, require_write=True)
    current = _row(conn, resource_id, materialized_id)
    if current is None:
        return
    physical_name = current[0]
    if not isinstance(physical_name, str) or not _TABLE_PATTERN.fullmatch(physical_name):
        raise ValueError("Materialized source registry entry is invalid.")
    conn.exec_driver_sql(
        f"DROP MATERIALIZED VIEW IF EXISTS public.{_q(physical_name)}")
    conn.execute(text(
        f"DELETE FROM public.{_q(REGISTRY)} "
        "WHERE materialized_id = :id AND resource_id = :resource_id"),
        {"id": materialized_id, "resource_id": resource_id})
