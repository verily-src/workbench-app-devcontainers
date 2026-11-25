"""The outcome a forecast predicts, described as rows of one of the cohort's dataset tables.

An outcome is ``{"table": ..., "where": [{"column": ..., "op": ..., "value": ...}, ...]}``, with an
optional ``"time_column"``. An entity has the outcome from the date of its first row of that
table that meets every condition: a diagnosis (``condition_occurrence`` where
``condition_concept_id`` is in a list), a lab result past a threshold (``measurement`` where the
concept is one and ``value_as_number < 60``), a first prescription, an admission, a death (the
``death`` table, no conditions). Standard library only.

Nothing the agent writes is run as SQL: the table and columns must be in the dataset's schema
and are quoted from it, the operator is one of ``OPS``, and every value is a query parameter
typed by its column.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from . import schema

OPS = ("in", "=", "!=", "<", "<=", ">", ">=", "between")
MAX_CONDITIONS = 10
MAX_VALUES = 1000

_FLOAT_TYPES = {"FLOAT", "FLOAT64", "NUMERIC", "BIGNUMERIC"}
_BOOL_TYPES = {"BOOL", "BOOLEAN"}


class OutcomeError(ValueError):
    """An outcome this server cannot use, with what to change."""


@dataclass(frozen=True)
class Condition:
    column: str
    op: str
    value: object          # one value, a list for "in", two for "between", typed for the column
    param_type: str        # the BigQuery type of the query parameter


@dataclass(frozen=True)
class Outcome:
    table: str             # the name in read_schemas (a shared name is prefixed by its dataset)
    source: str            # project.dataset holding the table
    source_table: str      # the table's own name
    time_column: str
    conditions: tuple[Condition, ...]

    def describe(self, vocabulary: dict | None = None) -> str:
        """The outcome in words, codes named from the dataset's concept table where it has one."""
        parts = []
        for c in self.conditions:
            if c.op == "in":
                shown = ", ".join(_named(v, vocabulary) for v in c.value)
                parts.append(f"{c.column} in [{shown}]")
            elif c.op == "between":
                parts.append(f"{c.column} between {c.value[0]} and {c.value[1]}")
            else:
                parts.append(f"{c.column} {c.op} {_named(c.value, vocabulary)}")
        where = f" where {' and '.join(parts)}" if parts else ""
        return f"the first row of {self.table}{where}, dated by {self.time_column}"


def _named(value, vocabulary: dict | None) -> str:
    name = (vocabulary or {}).get(str(value))
    return f"{value} ({name})" if name else str(value)


def parse(spec, schemas: dict[str, dict], key: str) -> Outcome:
    """The outcome ``spec`` checked against the dataset's ``schemas`` (``tables.read_schemas``):
    a table with the entity ``key`` and a date column, and conditions on its columns."""
    if not isinstance(spec, dict):
        raise OutcomeError('outcome is an object: {"table": ..., "where": [{"column": ..., "op": ..., "value": ...}]}')
    unknown = set(spec) - {"table", "where", "time_column"}
    if unknown:
        raise OutcomeError(f"outcome has unknown fields {', '.join(sorted(unknown))}; "
                           "it takes table, where and time_column")
    table = spec.get("table")
    keyed = schema.tables_with_key(schemas, key)
    if table not in schemas:
        raise OutcomeError(f"the outcome's table {table!r} is not in the cohort's dataset; tables with "
                           f"{key}: {', '.join(keyed)}")
    if table not in keyed:
        raise OutcomeError(f"the outcome's table {table} has no {key} column to link it to the cohort; tables "
                           f"with it: {', '.join(keyed)}")
    columns = schemas[table]["columns"]
    types = dict(columns)
    time_column = schema.time_column(columns, spec.get("time_column"))
    if time_column is None:
        raise OutcomeError(f"the outcome's table {table} has no DATE, DATETIME or TIMESTAMP column to say when "
                           "the outcome starts")
    where = spec.get("where") or []
    if not isinstance(where, list):
        raise OutcomeError("outcome.where is a list of conditions")
    if len(where) > MAX_CONDITIONS:
        raise OutcomeError(f"outcome.where has {len(where)} conditions; at most {MAX_CONDITIONS}")
    conditions = []
    for i, cond in enumerate(where):
        if not isinstance(cond, dict) or set(cond) != {"column", "op", "value"}:
            raise OutcomeError(f"outcome.where[{i}] is {{\"column\": ..., \"op\": ..., \"value\": ...}}")
        column, op, value = cond["column"], cond["op"], cond["value"]
        if column not in types:
            raise OutcomeError(f"outcome.where[{i}]: {column!r} is not a column of {table} "
                               f"({', '.join(n for n, _ in columns)})")
        if op not in OPS:
            raise OutcomeError(f"outcome.where[{i}]: op {op!r} is not one of {', '.join(OPS)}")
        conditions.append(_condition(i, column, types[column], op, value))
    meta = schemas[table]
    return Outcome(table=table, source=meta.get("source", ""), source_table=meta.get("table", table),
                   time_column=time_column, conditions=tuple(conditions))


def _condition(i: int, column: str, kind: str, op: str, value) -> Condition:
    where = f"outcome.where[{i}] ({column}, {kind})"
    if op == "in":
        if not isinstance(value, list) or not value:
            raise OutcomeError(f"{where}: op in takes a non-empty list of values")
        if len(value) > MAX_VALUES:
            raise OutcomeError(f"{where}: at most {MAX_VALUES} values")
        typed = [_typed(where, kind, v) for v in value]
    elif op == "between":
        if not isinstance(value, list) or len(value) != 2:
            raise OutcomeError(f"{where}: op between takes [low, high]")
        typed = [_typed(where, kind, v) for v in value]
    else:
        if isinstance(value, list):
            raise OutcomeError(f"{where}: op {op} takes one value; use in for a list")
        typed = _typed(where, kind, value)
    if kind in _BOOL_TYPES and op not in ("=", "!="):
        raise OutcomeError(f"{where}: a true/false column takes op = or !=")
    if kind == "STRING" and op not in ("in", "=", "!="):
        raise OutcomeError(f"{where}: a text column takes op in, = or !=")
    return Condition(column, op, typed, _param_type(kind))


def _param_type(kind: str) -> str:
    if kind in schema.INTEGER_TYPES:
        return "INT64"
    if kind in _FLOAT_TYPES:
        return "FLOAT64"
    if kind in _BOOL_TYPES:
        return "BOOL"
    if kind in schema.TIME_TYPES or kind == "STRING":
        return kind
    raise OutcomeError(f"columns of type {kind} cannot be used in an outcome condition")


def _typed(where: str, kind: str, v):
    if kind in schema.INTEGER_TYPES:
        if isinstance(v, bool) or not (isinstance(v, int) or (isinstance(v, str) and v.lstrip("-").isdigit())):
            raise OutcomeError(f"{where}: {v!r} is not a whole number")
        return int(v)
    if kind in _FLOAT_TYPES:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise OutcomeError(f"{where}: {v!r} is not a number")
        return float(v)
    if kind in _BOOL_TYPES:
        if not isinstance(v, bool):
            raise OutcomeError(f"{where}: {v!r} is not true or false")
        return v
    if kind == "STRING":
        if not isinstance(v, (str, int)) or isinstance(v, bool):
            raise OutcomeError(f"{where}: {v!r} is not text")
        return str(v)
    if kind in schema.TIME_TYPES:
        try:
            return date.fromisoformat(v) if kind == "DATE" else datetime.fromisoformat(v)
        except (TypeError, ValueError):
            raise OutcomeError(f"{where}: {v!r} is not an ISO date (YYYY-MM-DD)") from None
    _param_type(kind)
    raise OutcomeError(f"{where}: columns of type {kind} cannot be compared")


def query(o: Outcome, key: str) -> tuple[str, list[tuple[str, str, object, bool]]]:
    """The statement that gives each entity's first outcome date (columns ``key`` and
    ``outcome_date``), and its parameters as ``(name, type, value, is_array)``."""
    ref = f"`{o.source.replace('.', '`.`')}`.`{o.source_table}`"
    clauses, params = [f"`{key}` IS NOT NULL", f"`{o.time_column}` IS NOT NULL"], []
    for i, c in enumerate(o.conditions):
        col = f"`{c.column}`"
        if c.op == "in":
            clauses.append(f"{col} IN UNNEST(@v{i})")
            params.append((f"v{i}", c.param_type, list(c.value), True))
        elif c.op == "between":
            clauses.append(f"{col} BETWEEN @v{i}_lo AND @v{i}_hi")
            params += [(f"v{i}_lo", c.param_type, c.value[0], False), (f"v{i}_hi", c.param_type, c.value[1], False)]
        else:
            clauses.append(f"{col} {c.op} @v{i}")
            params.append((f"v{i}", c.param_type, c.value, False))
    sql = (f"SELECT `{key}` AS `{key}`, MIN(`{o.time_column}`) AS outcome_date FROM {ref} "
           f"WHERE {' AND '.join(clauses)} GROUP BY `{key}`")
    return sql, params
