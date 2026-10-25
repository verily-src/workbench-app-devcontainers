from __future__ import annotations

import internal_data
import pandas as pd
from sqlalchemy import Engine
from sqlglot import Dialect, exp, parse
from sqlglot.tokens import TokenType
from sqlglot.errors import ParseError, TokenError
from sqlglot.optimizer.scope import Scope, traverse_scope

import db
from sql_utils import statement as text

SQL_TIMEOUT_MS = 15_000
PREVIEW_LIMIT = 20
MAX_COLUMNS = 200
MAX_SQL_LENGTH = 20_000
_SAFE_FUNCTIONS = {
    "abs", "avg", "array_agg", "array_to_string", "btrim", "cast", "ceil", "ceiling",
    "coalesce", "concat", "concat_ws", "count", "current_date",
    "current_timestamp", "date_part", "date_trunc", "extract", "floor", "greatest",
    "json_agg", "json_build_object", "jsonb_agg", "jsonb_build_object", "left",
    "length", "least", "ln", "log", "lower", "ltrim", "max", "min", "mod",
    "nullif", "power", "regexp_like", "regexp_match", "regexp_replace", "replace", "right",
    "round", "rtrim", "sign", "split_part", "sqrt", "stddev", "stddev_pop",
    "stddev_samp", "string_agg", "sum", "to_char", "to_date", "to_number",
    "to_timestamp", "timestamp_trunc", "trim", "upper", "variance", "var_pop", "var_samp",
}
_BLOCKED_SCHEMAS = {"information_schema", "pg_catalog", "pg_toast", "pg_temp"}


def normalize(sql: str) -> str:
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("SQL query is required.")
    if len(sql) > MAX_SQL_LENGTH:
        raise ValueError(f"SQL query is limited to {MAX_SQL_LENGTH:,} characters.")
    try:
        tokens = Dialect.get_or_raise("postgres").tokenizer().tokenize(sql)
        depth = 0
        for token in tokens:
            if token.token_type == TokenType.L_PAREN:
                depth += 1
                if depth > 40:
                    raise ValueError("SQL nesting is limited to 40 levels.")
            elif token.token_type == TokenType.R_PAREN:
                depth -= 1
        if len(tokens) > 2000:
            raise ValueError("SQL source is too complex; simplify the query.")
        expressions = [item for item in parse(sql, read="postgres") if item is not None]
    except (ParseError, TokenError, RecursionError) as exc:
        raise ValueError("SQL query is not valid PostgreSQL SQL.") from exc
    if len(expressions) != 1:
        raise ValueError("Provide exactly one SELECT statement.")
    query = expressions[0]
    if not isinstance(query, exp.Query):
        raise ValueError("Only SELECT queries are allowed.")
    if sum(1 for _ in query.find_all(exp.Query)) > 100:
        raise ValueError("SQL source is too complex; simplify the query.")
    if query.find(exp.Into) is not None:
        raise ValueError("SELECT INTO is not allowed.")
    if query.find(exp.Lock) is not None:
        raise ValueError("Row-locking clauses are not allowed.")
    if any(node.args.get("kind") is not None or node.this == exp.DType.USERDEFINED
           for node in query.find_all(exp.DataType)):
        raise ValueError("User-defined SQL types are not allowed.")
    cte_table_ids = {
        id(table)
        for scope in traverse_scope(query)
        for table in scope.tables
        if not table.db and isinstance(scope.sources.get(table.alias_or_name), Scope)
    }

    for node in query.walk():
        if isinstance(node, exp.Operator) and "." in str(node.args.get("operator", "")):
            raise ValueError("Schema-qualified SQL operators are not allowed.")
        if node.__class__.__name__ in {"Placeholder", "Parameter"}:
            raise ValueError("SQL parameters are not supported in saved sources.")
        if isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Create,
                             exp.Drop, exp.Alter, exp.Command, exp.Merge)):
            raise ValueError("Only read-only SELECT queries are allowed.")
        if isinstance(node, exp.Table):
            if node.catalog:
                raise ValueError("Cross-database SQL references are not allowed.")
            if id(node) in cte_table_ids:
                continue
            internal_data.require_public_source(node.db, node.name)
            schema = (node.db or "").casefold()
            if not schema:
                raise ValueError("Use schema-qualified table names in SQL sources.")
            if (schema in _BLOCKED_SCHEMAS or schema.startswith("pg_temp_")
                    or schema.startswith("pg_toast")):
                raise ValueError("System schemas cannot be queried as SQL sources.")
        if isinstance(node, exp.Func):
            if isinstance(node, (exp.And, exp.Or, exp.Not, exp.Case, exp.If)):
                continue
            function = (node.name if isinstance(node, exp.Anonymous)
                        else node.sql_name()).casefold()
            if isinstance(node.parent, exp.Dot):
                raise ValueError("Schema-qualified SQL functions are not allowed.")
            if function not in _SAFE_FUNCTIONS:
                raise ValueError(f"SQL function {function!r} is not allowed.")
            child = node
            parent = node.parent
            while parent is not None and not isinstance(parent, (exp.Select, exp.From, exp.Join)):
                child = parent
                parent = parent.parent
            if isinstance(parent, exp.From) or (isinstance(parent, exp.Join) and parent.this is child):
                raise ValueError("Table-valued SQL functions are not allowed.")
    try:
        normalized = query.sql(dialect="postgres")
    except RecursionError as exc:
        raise ValueError("SQL source is too complex; simplify the query.") from exc
    if len(normalized) > MAX_SQL_LENGTH:
        raise ValueError(f"Normalized SQL is limited to {MAX_SQL_LENGTH:,} characters.")
    return normalized


def _engine(resource_id: str) -> Engine:
    engine = db.get_engine_for_resource(resource_id)
    if engine.dialect.name != "postgresql":
        raise ValueError("SQL sources require an Aurora PostgreSQL datasource.")
    return engine


class SQLTimeout(RuntimeError):
    pass


def fetch(resource_id: str, sql: str, limit: int,
          timeout_ms: int | None = None) -> tuple[pd.DataFrame, str, bool]:
    timeout_ms = SQL_TIMEOUT_MS if timeout_ms is None else int(timeout_ms)
    normalized = normalize(sql)
    engine = _engine(resource_id)
    query = f"SELECT * FROM ({normalized}) AS studio_sql_source LIMIT {int(limit) + 1}"
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            conn.exec_driver_sql("SET LOCAL search_path = pg_catalog")
            conn.exec_driver_sql(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
            result = conn.execute(text(query))
            columns = list(result.keys())
            if not columns or len(columns) > MAX_COLUMNS:
                raise ValueError(f"SQL source must return between 1 and {MAX_COLUMNS} columns.")
            if any(not name for name in columns) or len(set(columns)) != len(columns):
                raise ValueError("SQL source columns must have unique, nonblank names.")
            rows = result.fetchmany(int(limit) + 1)
    except ValueError:
        raise
    except Exception as exc:
        original = getattr(exc, "orig", None) or exc
        if getattr(original, "sqlstate", None) == "57014":
            raise SQLTimeout(f"SQL query exceeded the {timeout_ms // 1000} second timeout.") from exc
        raise ValueError("Aurora rejected the SQL source query: "
                         + str(original).split("\n")[0][:250]) from exc
    truncated = len(rows) > limit
    frame = pd.DataFrame.from_records(rows[:limit], columns=columns)
    return frame, normalized, truncated


def preview(resource_id: str, sql: str, name: str | None = None) -> dict:
    frame, normalized, truncated = fetch(resource_id, sql, PREVIEW_LIMIT)
    source_ref = {"kind": "sql", "resource_id": resource_id, "sql": normalized}
    if name is not None:
        source_ref["name"] = name.strip()
    return {"source_ref": source_ref, "columns": list(frame.columns),
            "sample": frame.astype(object).where(frame.notna(), None).values.tolist(),
            "rows": len(frame), "truncated": truncated}
