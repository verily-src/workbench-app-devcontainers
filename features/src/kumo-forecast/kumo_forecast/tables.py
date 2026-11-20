"""The tables a forecast reads, from BigQuery, cached per dataset as owner-only Parquet.

Kumo learns in context from the whole population's history, not only the cohort's, so the tables
are read whole once and kept until BigQuery says a table changed. A size guard
(``KUMO_FORECAST_MAX_ROWS``) refuses a dataset too large to hold in memory; a dataset the size of
All of Us would need the population sampled first.

Which tables and columns to read is decided by ``schema.py``; this module reads the schemas and
the data.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from . import privacy, schema

MAX_STRING_VALUES = 5000
URI = r"^(gs://|s3://|https?:)"
SKIP_TYPES = {"RECORD", "STRUCT", "BYTES", "GEOGRAPHY", "JSON", "RANGE", "INTERVAL"}


def datasets_of(dataset: str) -> list[str]:
    """The datasets a cohort's ``dataset`` names: one ``project.dataset``, or several joined by
    commas where one study keeps its tables in more than one (case report forms in one, screening
    in another)."""
    return [d for d in dataset.split(",") if d]


def read_schemas(client, dataset: str) -> dict[str, dict]:
    """``{table: {"num_rows", "modified", "columns", "source", "table"}}`` for the base tables of
    the dataset, or of each of the datasets ``dataset`` names (``datasets_of``). ``source`` is the
    table's dataset and ``table`` its own name; a name two datasets share is told apart by its
    dataset's name (``crf_DM``). Views are not read. A repeated or nested column is left out."""
    found: list[tuple[str, str, dict]] = []
    for source in datasets_of(dataset):
        for item in client.list_tables(source):
            if item.table_type != "TABLE":
                continue
            meta = client.get_table(f"{source}.{item.table_id}")
            columns = [(f.name, f.field_type) for f in meta.schema
                       if f.field_type not in SKIP_TYPES and f.mode != "REPEATED"]
            found.append((source, item.table_id, {
                "num_rows": int(meta.num_rows or 0), "columns": columns,
                "modified": meta.modified.isoformat() if meta.modified else ""}))
    shared = {t for t in {t for _, t, _ in found} if sum(1 for _, u, _ in found if u == t) > 1}
    out: dict[str, dict] = {}
    for source, table, entry in found:
        name = f"{source.split('.')[-1]}_{table}" if table in shared else table
        out[name] = {**entry, "source": source, "table": table}
    return out


@dataclass
class Plan:
    """What to read: the tables with the entity key, how each is dated, and the guard's total."""
    key: str
    tables: list[str]
    time: dict[str, str | None]
    rows: int
    schemas: dict[str, dict] = field(repr=False, default_factory=dict)


def plan(schemas: dict[str, dict], key: str, overrides: dict[str, str] | None = None,
         chosen: list[str] | None = None) -> Plan:
    """The tables a forecast keyed on ``key`` would read: ``chosen`` (each must exist in the dataset
    and have the key column), else every table with the key. Raises if there are none or too many rows."""
    names = schema.choose_tables(schemas, key, chosen)
    if not names:
        raise schema.SchemaError(f"no table of the dataset has a {key} column to link the cohort's members by")
    time = schema.time_columns(schemas, names, overrides)
    if not any(time.values()):
        raise schema.SchemaError(
            f"none of the tables to read ({', '.join(names)}) has a DATE, DATETIME or TIMESTAMP column, so "
            "a forecast has no history to learn from. The forecast needs calendar dates; times kept as a "
            "count of days from another date (a study day) are not read as dates")
    rows = schema.size_guard(schemas, names)
    return Plan(key, names, time, rows, schemas)


# The most column names get_cohort_info shows per table: the agent chooses tables by their rows and
# time column, and every column of a wide dataset would fill the agent's context.
SHOWN_COLUMNS = 20


def describe_keyed(schemas: dict[str, dict], key: str, overrides: dict[str, str] | None = None) -> list[dict]:
    """Every table with the key, for the agent to choose from: rows, time column, and the first
    SHOWN_COLUMNS column names (with how many more there are)."""
    out = []
    for t in schema.tables_with_key(schemas, key):
        names = [n for n, _ in schemas[t]["columns"]]
        entry = {"table": t, "rows": privacy.count(int(schemas[t]["num_rows"])),
                 "time_column": schema.time_column(schemas[t]["columns"], (overrides or {}).get(t)),
                 "columns": names[:SHOWN_COLUMNS]}
        if len(names) > SHOWN_COLUMNS:
            entry["more_columns"] = len(names) - SHOWN_COLUMNS
        out.append(entry)
    return out


def _ref(dataset: str, table: str) -> str:
    return f"`{dataset.replace('.', '`.`')}`.`{table}`"


def load(client, dataset: str, p: Plan, cache_dir: Path) -> dict[str, pd.DataFrame]:
    """Every table of the plan, from the cache while BigQuery's stamp (modified time, rows, columns)
    is unchanged. Date columns come back as datetimes without a time zone."""
    cache_dir = Path(cache_dir) / dataset.replace(".", "__").replace(",", "+")
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(cache_dir.parent, 0o700)
    os.chmod(cache_dir, 0o700)
    out: dict[str, pd.DataFrame] = {}
    for name in p.tables:
        meta = p.schemas[name]
        cols = [c for c, _ in meta["columns"]]
        stamp = f"{meta['modified']}|{meta['num_rows']}|{','.join(cols)}|compact1"
        data, side = cache_dir / f"{name}.parquet", cache_dir / f"{name}.json"
        cached = json.loads(side.read_text()) if side.exists() else {}
        if data.exists() and cached.get("stamp") == stamp:
            df = pd.read_parquet(data)
            kept = cached["columns"]
        else:
            sql = (f"SELECT {', '.join(f'`{c}`' for c in cols)} "
                   f"FROM {_ref(meta.get('source', dataset), meta.get('table', name))}")
            df = client.query(sql).to_dataframe()
            df, kept = compact(df, p.key)
            df.to_parquet(data, index=False)
            side.write_text(json.dumps({"stamp": stamp, "columns": kept}))
            for f in (data, side):
                os.chmod(f, 0o600)
        meta["columns"] = [(c, ty) for c, ty in meta["columns"] if c in kept]
        for c, ty in meta["columns"]:
            if ty in schema.TIME_TYPES and c in df:
                df[c] = _naive(df[c])
        out[name] = df
    return out


def compact(df: pd.DataFrame, key: str) -> tuple[pd.DataFrame, list[str]]:
    """The table as the model reads it, in less memory: a string column with more than
    ``MAX_STRING_VALUES`` distinct values is free text or an identifier and is dropped; the others
    become categories. The entity key is kept as it is. Returns the table and the columns kept."""
    drop = []
    for c in df.columns:
        if c == key or df[c].dtype.kind != "O" and not pd.api.types.is_string_dtype(df[c]):
            continue
        if df[c].nunique() > MAX_STRING_VALUES or _looks_like_locations(df[c]):
            drop.append(c)
        else:
            df[c] = df[c].astype("category")
    df = df.drop(columns=drop)
    return df, list(df.columns)


def _looks_like_locations(values: pd.Series) -> bool:
    """A string column whose sampled values are URIs (file locations), judged by value."""
    sample = values.dropna().astype(str).head(200)
    return len(sample) > 0 and bool(sample.str.match(URI).all())


def _naive(values: pd.Series) -> pd.Series:
    """Datetimes without a time zone: a TIMESTAMP is read as UTC, so columns of different types compare."""
    out = pd.to_datetime(values, utc=True)
    return out.dt.tz_localize(None)


def vocabulary(client, dataset: str, schemas: dict[str, dict]) -> dict[str, str]:
    """``{code: name}`` from a concept-shaped table (``concept_id``, ``concept_name``), else empty."""
    name = schema.concept_table(schemas)
    if name is None:
        return {}
    meta = schemas[name]
    ref = _ref(meta.get("source", dataset), meta.get("table", name))
    df = client.query(f"SELECT concept_id, concept_name FROM {ref}").to_dataframe()
    return dict(zip(df.concept_id.astype(str), df.concept_name))
