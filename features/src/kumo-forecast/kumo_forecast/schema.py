"""Which tables a forecast reads and how, decided from schemas alone. Standard library only.

A schema here is ``{table: {"num_rows": int, "columns": [(name, type), ...]}}`` with BigQuery's type
names (``INTEGER``, ``STRING``, ``DATE``, ...), in the table's own column order. Everything in this
module is a pure function over such dicts, so the choices can be tested without BigQuery or the
model's packages. ``tables.py`` reads the schemas and the data; ``model.py`` builds the graph.
"""
from __future__ import annotations

import os
import re

from . import privacy

TIME_TYPES = {"DATE", "DATETIME", "TIMESTAMP"}
INTEGER_TYPES = {"INTEGER", "INT64"}
CODE_TYPES = INTEGER_TYPES | {"STRING"}
NUMBER_TYPES = {"FLOAT", "FLOAT64", "NUMERIC", "BIGNUMERIC", "INTEGER", "INT64"}
CODE_NAME = re.compile(r"(_concept_id|_code|code)$")
MAX_CODE_VALUES = 5000
MIN_CODE_SHARE = 0.005
MOST_CODES = 20
DEFAULT_MAX_ROWS = 50_000_000
SEP = "__"


class SchemaError(ValueError):
    """A dataset or choice this server cannot use, with what to do about it."""


def max_rows() -> int:
    try:
        return max(1, int(os.environ.get("KUMO_FORECAST_MAX_ROWS", DEFAULT_MAX_ROWS)))
    except ValueError:
        return DEFAULT_MAX_ROWS


def tables_with_key(schemas: dict[str, dict], key: str) -> list[str]:
    """The tables that have the entity key column, in the dataset's order."""
    return [t for t, s in schemas.items() if any(n == key for n, _ in s["columns"])]


def choose_tables(schemas: dict[str, dict], key: str, chosen: list[str] | None) -> list[str]:
    """The tables to read: ``chosen`` (each must be in the dataset and have the key column), else
    every table with the key."""
    keyed = tables_with_key(schemas, key)
    if chosen is None:
        return keyed
    names = list(dict.fromkeys(chosen))
    missing = [t for t in names if t not in schemas]
    if missing:
        raise SchemaError(f"tables {', '.join(missing)} are not in the dataset "
                          f"(its tables with {key}: {', '.join(keyed) or 'none'})")
    unkeyed = [t for t in names if t not in keyed]
    if unkeyed:
        raise SchemaError(f"tables {', '.join(unkeyed)} have no {key} column to link the cohort's "
                          f"members by (tables with it: {', '.join(keyed) or 'none'})")
    return names


def time_column(columns: list[tuple[str, str]], override: str | None = None) -> str | None:
    """The column that dates a table's rows, else None (a static table).

    Its only DATE, DATETIME or TIMESTAMP column. With several, the first whose name contains
    ``start``, else the first in schema order. ``override`` (from ``time_columns``) wins."""
    names = [n for n, _ in columns]
    if override is not None:
        if override not in names:
            raise SchemaError(f"time column {override!r} is not a column of the table ({', '.join(names)})")
        kind = dict(columns)[override]
        if kind not in TIME_TYPES:
            raise SchemaError(f"time column {override!r} is {kind}, not a DATE, DATETIME or TIMESTAMP: the "
                              "forecast dates rows by the calendar, and a count of days from another date "
                              "(a study day) is not read as one")
        return override
    dated = [n for n, ty in columns if ty in TIME_TYPES]
    if len(dated) <= 1:
        return dated[0] if dated else None
    return next((n for n in dated if "start" in n.lower()), dated[0])


def time_columns(schemas: dict[str, dict], tables: list[str], overrides: dict[str, str] | None = None) -> dict[str, str | None]:
    """``{table: time column or None}`` for the tables, with the caller's overrides."""
    overrides = overrides or {}
    unknown = sorted(set(overrides) - set(schemas))
    if unknown:
        raise SchemaError(f"time_columns names {', '.join(unknown)}, which are not tables of the dataset")
    return {t: time_column(schemas[t]["columns"], overrides.get(t)) for t in tables}


def _shown(rows: int) -> str:
    """A row count as ``privacy.count`` gives it, with thousands separators when it is shown."""
    n = privacy.count(rows)
    return f"{n:,}" if isinstance(n, int) else n


def size_guard(schemas: dict[str, dict], tables: list[str], limit: int | None = None) -> int:
    """The rows the tables hold in all; refuses above the limit and names the largest tables."""
    limit = max_rows() if limit is None else limit
    total = sum(int(schemas[t]["num_rows"]) for t in tables)
    if total > limit:
        biggest = sorted(tables, key=lambda t: -int(schemas[t]["num_rows"]))[:3]
        raise SchemaError(
            f"the tables to read hold {total:,} rows, above the limit of {limit:,} "
            "(KUMO_FORECAST_MAX_ROWS). The largest: "
            + ", ".join(f"{t} ({_shown(int(schemas[t]['num_rows']))})" for t in biggest))
    return total


def code_columns(columns: list[tuple[str, str]], key: str, time: str | None) -> list[str]:
    """Columns that may hold a code: integer or string, not the key or the time column, named
    ``..._concept_id``, ``..._code`` or ``...code``. Whether one has at most 5,000 distinct values
    is checked against the data."""
    return [n for n, ty in columns if ty in CODE_TYPES and n not in (key, time) and CODE_NAME.search(n.lower())]


def value_column(columns: list[tuple[str, str]], key: str, code: str | None = None) -> str | None:
    """The numeric value column of a table: the first numeric column whose name contains ``value``
    (OMOP's ``value_as_number``)."""
    return next((n for n, ty in columns if ty in NUMBER_TYPES and "value" in n.lower() and n not in (key, code)), None)


def frequent_codes(counts: dict, min_share: float = MIN_CODE_SHARE, most: int = MOST_CODES) -> list:
    """The codes with at least ``min_share`` of the rows, the most frequent first, up to ``most``."""
    total = sum(counts.values())
    if not total:
        return []
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0])))
    return [c for c, n in ranked if n / total >= min_share][:most]


def split_name(table: str, code) -> str:
    """The name of the table holding one code's rows: ``<table>__<code>``."""
    return f"{table}{SEP}{re.sub(r'[^A-Za-z0-9_]', '_', str(code))}"


def concept_table(schemas: dict[str, dict]) -> str | None:
    """A ``concept``-shaped table (``concept_id`` and ``concept_name``), if the dataset has one."""
    for t, s in schemas.items():
        names = {n for n, _ in s["columns"]}
        if {"concept_id", "concept_name"} <= names:
            return t
    return None


def display_name(code, vocabulary: dict | None) -> str:
    """A code's name from the concept table, else the code itself."""
    return (vocabulary or {}).get(str(code), str(code))


def is_unique_first_rows(values: list) -> bool:
    """A column is a usable primary key when it has no repeats and no gaps in the rows read."""
    return len(values) > 0 and len(set(values)) == len(values) and all(v is not None for v in values)


def primary_key(table: str, columns: list[tuple[str, str]], first_rows: list | None) -> str | None:
    """``<table>_id`` when the column exists and is unique in the first 10,000 rows, else None
    (the model adds a row-number column)."""
    own = f"{table}_id"
    if any(n == own for n, _ in columns) and first_rows is not None and is_unique_first_rows(first_rows):
        return own
    return None


def entity_table(static: list[str], unique_on_key: dict[str, bool], schemas: dict[str, dict]) -> str | None:
    """The static table that holds one row per entity, else None (the entity table is then built
    from the distinct keys). With several, the one with the most columns, then schema order."""
    candidates = [t for t in static if unique_on_key.get(t)]
    if not candidates:
        return None
    return max(candidates, key=lambda t: (len(schemas[t]["columns"]), -list(schemas).index(t)))
