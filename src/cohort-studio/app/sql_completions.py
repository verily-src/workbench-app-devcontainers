"""Schema metadata for SQL editor autocomplete.

Names and types only (schemas, tables, columns) from information_schema,
read in a read-only transaction with a statement timeout, bounded and cached
per resource. Never reads table data.
"""
from __future__ import annotations

import logging

from sqlalchemy import Engine

import database as db
import internal_data
import omop
import queries
import sql_source
from cache import ttl_cache
from sql_utils import statement as text

logger = logging.getLogger(__name__)

CACHE_TTL = 300
TIMEOUT_MS = 5_000
MAX_TABLES = 1_000
MAX_COLUMNS = 2_000


class CompletionsTimeout(RuntimeError):
    pass


class UnknownResource(LookupError):
    pass


def _system_schema(schema: str) -> bool:
    name = schema.casefold()
    return (name in sql_source._BLOCKED_SCHEMAS or name.startswith("pg_")
            or name.startswith("_studio_"))


# Exclusions repeated in SQL so the LIMIT bounds what callers can use.
_WHERE = """
    WHERE {s} <> 'information_schema' AND left({s}, 3) <> 'pg_'
      AND left({s}, 8) <> '_studio_'
      AND left({t}, 11) <> '_studio_mv_'
      AND NOT ({t} = ANY(:internal))
"""

_TABLES_SQL = """
    SELECT table_schema, table_name, table_type
    FROM information_schema.tables""" + _WHERE.format(s="table_schema", t="table_name") + """
    ORDER BY (table_schema = ANY(:priority)) DESC, table_schema, table_name
    LIMIT :limit
"""

_COLUMNS_SQL = """
    SELECT table_schema, table_name, column_name, data_type, udt_name
    FROM information_schema.columns""" + _WHERE.format(s="table_schema", t="table_name") + """
    ORDER BY (table_schema = ANY(:priority)) DESC, table_schema, table_name, ordinal_position
    LIMIT :limit
"""


def _type(data_type: str | None, udt_name: str | None) -> str:
    if data_type == "ARRAY" and udt_name:
        return udt_name.lstrip("_") + "[]"
    if data_type == "USER-DEFINED" and udt_name:
        return udt_name
    return data_type or udt_name or ""


def _omop_schemas(resource_id: str | None) -> dict[str, dict]:
    """{schema: marker} for detected OMOP CDM and vocabulary schemas."""
    if resource_id is None:
        return {}
    try:
        info = omop.detect_resource(resource_id)
    except Exception as exc:
        logger.info("OMOP detection unavailable for completions on %s: %s",
                    resource_id, str(exc).splitlines()[0][:200] if str(exc) else exc)
        return {}
    marks: dict[str, dict] = {}
    for item in omop.schema_summary(info):
        marks[item["cdm_schema"]] = {"role": "cdm", "vocab_schema": item.get("vocab_schema"),
                                     "default": bool(item.get("default"))}
    for item in omop.schema_summary(info):
        vocab = item.get("vocab_schema")
        if vocab and vocab not in marks:
            marks[vocab] = {"role": "vocabulary"}
    return marks


def load(engine: Engine, resource_id: str | None = None, *,
         max_tables: int = MAX_TABLES, max_columns: int = MAX_COLUMNS,
         timeout_ms: int = TIMEOUT_MS) -> dict:
    """Uncached metadata read; ``completions`` is the cached entry point."""
    marks = _omop_schemas(resource_id)
    params = {"internal": sorted(internal_data.INTERNAL_TABLES),
              "priority": sorted(marks)}
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            conn.exec_driver_sql("SET LOCAL search_path = pg_catalog")
            conn.exec_driver_sql(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
            table_rows = conn.execute(text(_TABLES_SQL),
                                      {**params, "limit": int(max_tables) + 1}).fetchall()
            column_rows = conn.execute(text(_COLUMNS_SQL),
                                       {**params, "limit": int(max_columns) + 1}).fetchall()
    except Exception as exc:
        original = getattr(exc, "orig", None) or exc
        if getattr(original, "sqlstate", None) == "57014":
            raise CompletionsTimeout("Reading table metadata exceeded the "
                                     f"{timeout_ms / 1000:g} second timeout.") from exc
        raise
    truncated = len(table_rows) > max_tables or len(column_rows) > max_columns
    tables: dict[tuple[str, str], dict] = {}
    for schema, name, ttype in table_rows[:max_tables]:
        if _system_schema(schema) or internal_data.is_internal(schema, name):
            continue
        tables[(schema, name)] = {"schema": schema, "name": name,
                                  "kind": queries.TABLE_TYPE_LABELS.get(ttype, "table"),
                                  "columns": []}
    column_count = 0
    for schema, table, column, data_type, udt_name in column_rows[:max_columns]:
        entry = tables.get((schema, table))
        if entry is None:
            continue
        entry["columns"].append({"name": column, "type": _type(data_type, udt_name)})
        column_count += 1
    schema_names = sorted({schema for schema, _ in tables}
                          | {s for s in marks if not _system_schema(s)},
                          key=lambda s: (s not in marks, s))
    schemas = []
    for name in schema_names:
        item = {"name": name}
        if name in marks:
            item["omop"] = marks[name]
        schemas.append(item)
    for entry in tables.values():
        if entry["schema"] in marks:
            entry["omop"] = True
    return {"schemas": schemas, "tables": list(tables.values()),
            "column_count": column_count, "truncated": truncated,
            "limits": {"tables": max_tables, "columns": max_columns}}


@ttl_cache(ttl=CACHE_TTL, maxsize=32)
def completions(resource_id: str) -> dict:
    known = {r["id"] for r in db.list_aurora_resources()}
    if resource_id not in known:
        raise UnknownResource(f"Unknown Aurora resource: {resource_id}")
    engine = sql_source._engine(resource_id)
    return {"resource_id": resource_id, **load(engine, resource_id)}


def invalidate():
    completions.invalidate()
