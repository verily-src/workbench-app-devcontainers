"""Save the people matching the current filters into an existing OMOP cohort table.

The app only ever INSERTs here. It never creates or alters a table, and it refuses ``public`` and
the system schemas so the OMOP data stays read-only for it. The cohort table is created by the
data owner; this module checks it has the expected columns and that the cohort id is unused.
"""
import re

import database as db
import filter_rules
import live_query
import query_cancellation
from sql_utils import statement as text

SCHEMA_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
# OMOP data lives in ``public`` on this kind of database; saving there would write beside it.
BLOCKED_SCHEMAS = {"public", "information_schema"}
COHORT_COLUMNS = ("cohort_definition_id", "subject_id", "cohort_start_date",
                  "cohort_end_date", "cohort_name")


class CohortSaveError(ValueError):
    """A problem the user can fix: bad target, missing table, id already used."""


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def validate_target(schema: str, table: str) -> tuple[str, str]:
    for value, what in ((schema, "schema"), (table, "table")):
        if not isinstance(value, str) or not SCHEMA_PATTERN.fullmatch(value):
            raise CohortSaveError(
                f"The {what} name must be letters, digits and underscores, starting with a letter or underscore.")
    lowered = schema.casefold()
    if lowered in BLOCKED_SCHEMAS or lowered.startswith("pg_"):
        raise CohortSaveError(
            f"Cohorts can't be saved to the {schema!r} schema. The app keeps the OMOP data read-only; "
            "use a separate results schema.")
    return schema, table


def build_insert(live_source: dict, filters: list[dict], entity_column: str,
                 schema: str, table: str, date_column: str | None = None,
                 numeric_types: dict[str, int] | None = None) -> tuple[str, dict]:
    """INSERT ... SELECT of one row per distinct entity matching ``filters``. No database access."""
    columns = live_source["columns"]
    if entity_column not in columns:
        raise CohortSaveError(f"Unknown person column: {entity_column!r}.")
    if date_column is not None and date_column not in columns:
        raise CohortSaveError(f"Unknown date column: {date_column!r}.")
    where, params = live_query._where(filters, columns, numeric_types or {})
    entity = f"live.{_q(columns[entity_column])}"
    if date_column is None:
        start = end = "CAST(NULL AS date)"
    else:
        dates = f"CAST(live.{_q(columns[date_column])} AS date)"
        start, end = f"MIN({dates})", f"MAX({dates})"
    sql = (
        f"INSERT INTO {_q(schema)}.{_q(table)} ({', '.join(COHORT_COLUMNS)}) "
        f"SELECT CAST(:cohort_id AS integer), {entity}, {start}, {end}, "
        f"CAST(:cohort_name AS varchar(256)) "
        f"FROM ({live_source['sql']}) AS live "
        f"WHERE ({where}) AND {entity} IS NOT NULL GROUP BY {entity}")
    return sql, params


# Tables the user can pick as a destination: real tables outside the protected schemas that have
# the five cohort columns. can_insert says whether the app's database user may write to it.
_TARGETS_SQL = (
    "SELECT t.table_schema, t.table_name, "
    "has_table_privilege(quote_ident(t.table_schema) || '.' || quote_ident(t.table_name), 'INSERT') "
    "AS can_insert "
    "FROM information_schema.tables t "
    "WHERE t.table_type = 'BASE TABLE' "
    "AND t.table_schema <> ALL(:blocked) AND left(t.table_schema, 3) <> 'pg_' "
    "AND (SELECT count(DISTINCT c.column_name) FROM information_schema.columns c "
    "WHERE c.table_schema = t.table_schema AND c.table_name = t.table_name "
    "AND c.column_name = ANY(:columns)) = :n "
    "ORDER BY t.table_schema, t.table_name")


def list_targets(live_source: dict) -> list[dict]:
    engine = db.get_engine_for_resource(live_source["resource_id"])
    with engine.begin() as conn:
        conn.exec_driver_sql("SET LOCAL search_path = pg_catalog")
        conn.exec_driver_sql("SET LOCAL statement_timeout = 10000")
        rows = conn.execute(text(_TARGETS_SQL), {
            "blocked": sorted(BLOCKED_SCHEMAS), "columns": list(COHORT_COLUMNS),
            "n": len(COHORT_COLUMNS)}).all()
    return [{"schema": r[0], "table": r[1], "can_insert": bool(r[2])} for r in rows]


def _explain_db_error(exc: Exception, schema: str, table: str) -> Exception:
    original = getattr(exc, "orig", None)
    state = getattr(original, "sqlstate", None)
    if state == "42501":
        return CohortSaveError(
            f"The app's database user isn't allowed to write to {schema}.{table}. "
            "Ask the data owner to grant INSERT on it.")
    if state == "23505":
        constraint = getattr(getattr(original, "diag", None), "constraint_name", None) or "a unique constraint"
        return CohortSaveError(
            f"{schema}.{table} rejected the rows because of {constraint}. A cohort has one row per "
            "person, so its primary key must include subject_id (for example "
            "cohort_definition_id, subject_id, cohort_start_date).")
    if state == "23503":
        return CohortSaveError(
            f"A person in this cohort isn't in the table {schema}.{table} refers to (a foreign key failed).")
    return exc


def save(live_source: dict, filters: list[dict], entity_column: str, schema: str, table: str,
         cohort_definition_id: int, cohort_name: str, date_column: str | None = None) -> int:
    """Insert the matching people and return how many rows were written."""
    validate_target(schema, table)
    engine = db.get_engine_for_resource(live_source["resource_id"])
    try:
        with engine.begin() as conn, query_cancellation.postgres_connection(conn):
            conn.exec_driver_sql("SET LOCAL search_path = pg_catalog")
            conn.exec_driver_sql("SET LOCAL TimeZone = 'UTC'")
            conn.exec_driver_sql(f"SET LOCAL statement_timeout = {live_query.LARGE_TIMEOUT_MS}")
            present = {row[0] for row in conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = :schema AND table_name = :table"),
                {"schema": schema, "table": table})}
            if not present:
                raise CohortSaveError(
                    f"{schema}.{table} doesn't exist or isn't visible to the app. The app doesn't create "
                    "cohort tables; ask the data owner to create it.")
            missing = [c for c in COHORT_COLUMNS if c not in present]
            if missing:
                raise CohortSaveError(f"{schema}.{table} is missing column(s): {', '.join(missing)}.")
            used = conn.execute(text(
                f"SELECT 1 FROM {_q(schema)}.{_q(table)} WHERE cohort_definition_id = :id LIMIT 1"),
                {"id": cohort_definition_id}).first()
            if used:
                raise CohortSaveError(
                    f"Cohort id {cohort_definition_id} already has rows in {schema}.{table}. "
                    "Choose a different id.")
            numeric_types = live_query._numeric_columns(
                conn, live_source,
                [f["column"] for f in filter_rules.leaves(filters) if f.get("kind") in ("range", "categorical")])
            sql, params = build_insert(live_source, filters, entity_column, schema, table,
                                       date_column, numeric_types)
            result = live_query._query(conn, live_source, sql, {
                **params, "cohort_id": cohort_definition_id, "cohort_name": cohort_name})
            return int(result.rowcount)
    except CohortSaveError:
        raise
    except Exception as exc:
        explained = _explain_db_error(exc, schema, table)
        if explained is exc:
            raise
        raise explained from exc
