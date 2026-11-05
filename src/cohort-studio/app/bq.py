import json
import logging
import os
import re

import pandas as pd

from cache import ttl_cache

logger = logging.getLogger(__name__)

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_\-]+$")
_clients: dict = {}

def _client(project: str):
    if project not in _clients:
        from google.cloud import bigquery
        _clients[project] = bigquery.Client(project=project)
    return _clients[project]

def billing_project(configured: str = "", data_project: str = "") -> str:
    """Project that runs (and pays for) query jobs."""
    return configured or os.environ.get("STUDIO_BQ_BILLING_PROJECT", "") or data_project


def _flat(value):
    """Arrays and records as text, so nested tables load as flat columns."""
    if value is None:
        return None
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes)):
        value = value.tolist()
    if isinstance(value, dict):
        if len(value) == 1:
            return _flat(next(iter(value.values())))
        return json.dumps(value, default=str, sort_keys=True)
    if isinstance(value, (list, tuple)):
        raw = [v.tolist() if hasattr(v, "tolist") and not isinstance(v, (str, bytes)) else v
               for v in value]
        structured = any(isinstance(v, (list, tuple)) or (isinstance(v, dict) and len(v) != 1)
                         for v in raw)
        if structured:
            return json.dumps(raw, default=str, sort_keys=True)   # keep nesting unambiguous
        items = [_flat(v) for v in raw]
        return ", ".join("" if v is None else str(v) for v in items)
    return value


def flatten(df: pd.DataFrame) -> pd.DataFrame:
    for column in df.columns:
        if df[column].dtype != object:
            continue
        sample = df[column].dropna().head(50)
        if any(isinstance(v, (list, tuple, dict)) or (hasattr(v, "tolist") and not isinstance(v, (str, bytes)))
               for v in sample):
            df[column] = df[column].map(_flat)
    return df


def _validate(*identifiers: str):
    for ident in identifiers:
        if not _IDENTIFIER.match(ident):
            raise ValueError(f"Invalid BigQuery identifier: {ident!r}")

@ttl_cache(ttl=300)
def list_tables(project: str, dataset: str, billing: str = "") -> list[str]:
    _validate(project, dataset)
    tables = [t.table_id for t in
              _client(billing_project(billing, project)).list_tables(f"{project}.{dataset}")]
    logger.info("Found %d tables in %s.%s", len(tables), project, dataset)
    return tables

@ttl_cache(ttl=300)
def table_info(project: str, dataset: str, table: str, billing: str = "") -> dict:
    """Row count, size and column count from table metadata (no query cost)."""
    _validate(project, dataset, table)
    t = _client(billing_project(billing, project)).get_table(f"{project}.{dataset}.{table}")
    info = {"columns": len(t.schema)}
    if t.num_rows is not None:
        info["rows"] = int(t.num_rows)
    if t.num_bytes is not None:
        info["bytes"] = int(t.num_bytes)
    if t.modified is not None:
        info["modified"] = t.modified.isoformat()
    return info

@ttl_cache(ttl=600, maxsize=4)
def fetch_table(project: str, dataset: str, table: str, cap: int,
                billing: str = "") -> pd.DataFrame:

    _validate(project, dataset, table)
    query = f"SELECT * FROM `{project}.{dataset}.{table}` LIMIT {int(cap)}"
    df = _client(billing_project(billing, project)).query(query).to_dataframe()
    return flatten(df)


# --- Full-table reads for cross-source joins (BigQuery Storage Read API) ---

_storage_clients: dict = {}
# Table types the Storage Read API can read. Logical views, external tables
# and materialized views are not readable this way; joins keep their loaded
# (capped) rows instead.
STREAMABLE_TABLE_TYPES = {"TABLE"}


def _storage_client(billing: str):
    if billing not in _storage_clients:
        from google.cloud import bigquery_storage_v1
        credentials = getattr(_client(billing), "_credentials", None)
        _storage_clients[billing] = (bigquery_storage_v1.BigQueryReadClient(credentials=credentials)
                                     if credentials is not None
                                     else bigquery_storage_v1.BigQueryReadClient())
    return _storage_clients[billing]


def full_source(ds: dict) -> dict | None:
    """Where to read every row of a capped, in-memory BigQuery dataset, or None.

    Only datasets opened from a BigQuery table reference qualify. Column
    settings that change a column's type were applied to the loaded rows
    only, so such datasets keep their loaded rows.
    """
    ref = ds.get("source_ref") or {}
    if (ref.get("kind") != "bq" or not ds.get("capped")
            or ds.get("live_source") or ds.get("disk_source")):
        return None
    if any(s.get("logical_type") for s in ref.get("settings") or []):
        return None
    import database as db
    for d in db.list_bq_datasets():
        if d["id"] == ref.get("resource_id"):
            table = ref.get("table")
            _validate(d["project"], d["dataset"], table)
            return {"resource_id": d["id"], "project": d["project"], "dataset": d["dataset"],
                    "table": table,
                    "billing": billing_project(d.get("billing_project", ""), d["project"])}
    return None


def table_meta(spec: dict) -> dict:
    """Schema, size and type of a table from metadata (no query cost)."""
    t = _client(spec["billing"]).get_table(f"{spec['project']}.{spec['dataset']}.{spec['table']}")
    return {"types": {f.name: str(f.field_type).upper() for f in t.schema},
            "num_rows": None if t.num_rows is None else int(t.num_rows),
            "num_bytes": None if t.num_bytes is None else int(t.num_bytes),
            "table_type": str(getattr(t, "table_type", "") or "").upper()}


def _bq_string(value: str) -> str:
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") \
        .replace("\n", "\\n").replace("\r", "\\r") + "'"


_NUMBER_TYPES = {"INT64", "INTEGER", "FLOAT64", "FLOAT", "NUMERIC", "BIGNUMERIC",
                 "DECIMAL", "BIGDECIMAL"}


def _bq_literal(value, kind: str, bq_type: str) -> str | None:
    if kind == "number" and bq_type in _NUMBER_TYPES:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if isinstance(value, int):
            return repr(value) if abs(value) < 2 ** 63 else None
        return repr(float(value))
    if kind == "bool" and bq_type in {"BOOL", "BOOLEAN"} and isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if bq_type == "DATE" and kind == "time":
        import datetime
        if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
            return f"DATE '{value.isoformat()}'"
        return None
    if bq_type == "STRING" and kind in ("text", "unknown") and isinstance(value, str):
        return _bq_string(value)
    return None


def row_restriction(filters: list[dict], types: dict[str, str]) -> tuple[str, list[dict]]:
    """(BigQuery row restriction, residual filters) for checked join filters.

    A filter is pushed into the read only when BigQuery evaluates it exactly
    as DuckDB would after staging: matching column and value types and the
    same comparison semantics. `contains` (ILIKE with an escape) and
    timestamp comparisons (time zones) always stay residual.
    """
    clauses, residual = [], []
    for f in filters:
        column, op = f["column"], f["op"]
        bq_type = types.get(column)
        clause = None
        if bq_type and _IDENTIFIER.match(column) and op != "contains":
            ref = f"`{column}`"
            if op in ("is null", "is not null"):
                clause = f"{ref} {op.upper()}"
            else:
                literals = [_bq_literal(v, f["kind"], bq_type) for v in f["values"]]
                if f["text"] and bq_type != "STRING":
                    literals = [None]
                if literals and None not in literals:
                    if op in ("in", "not in"):
                        clause = f"{ref} {op.upper()} ({', '.join(literals)})"
                    else:
                        clause = f"{ref} {op} {literals[0]}"
        if clause is None:
            residual.append(f)
        else:
            clauses.append(f"({clause})")
    return " AND ".join(clauses), residual


def _flat_arrow(batch):
    """Arrow batch with nested and wide-decimal columns as loaded rows have them."""
    import pyarrow as pa
    import pyarrow.types as pt
    arrays, fields, changed = [], [], False
    for field, column in zip(batch.schema, batch.columns):
        kind = field.type
        if pt.is_list(kind) or pt.is_large_list(kind) or pt.is_struct(kind) or pt.is_map(kind):
            values = [_flat(v) for v in column.to_pylist()]
            column = pa.array([None if v is None else str(v) for v in values], type=pa.string())
            field, changed = pa.field(field.name, pa.string()), True
        elif pt.is_decimal(kind) and getattr(kind, "precision", 0) > 38:
            column = column.cast(pa.float64(), safe=False)
            field, changed = pa.field(field.name, pa.float64()), True
        elif isinstance(kind, pa.ExtensionType):
            column = column.storage if hasattr(column, "storage") else column
            field, changed = pa.field(field.name, column.type), True
        arrays.append(column)
        fields.append(field)
    return pa.RecordBatch.from_arrays(arrays, schema=pa.schema(fields)) if changed else batch


def read_batches(spec: dict, columns: list[str] | None = None, restriction: str = "",
                 on_stream=None):
    """Yield Arrow record batches of the table via the Storage Read API.

    The read session (and its cost) belongs to the billing project. One
    stream keeps rows in a single ordered sequence; `on_stream(stream)` is
    called with the open ReadRowsStream so callers can cancel it.
    """
    from google.cloud.bigquery_storage_v1 import types
    for name in columns or []:
        if not _IDENTIFIER.match(name):
            columns = None              # unsafe name: read every column instead
            break
    options = types.ReadSession.TableReadOptions(
        selected_fields=list(columns or []), row_restriction=restriction or "")
    session = types.ReadSession(
        table=f"projects/{spec['project']}/datasets/{spec['dataset']}/tables/{spec['table']}",
        data_format=types.DataFormat.ARROW, read_options=options)
    client = _storage_client(spec["billing"])
    session = client.create_read_session(parent=f"projects/{spec['billing']}",
                                         read_session=session, max_stream_count=1)
    if not session.streams:
        return                              # no rows match
    stream = client.read_rows(session.streams[0].name)
    if on_stream is not None:
        on_stream(stream)
    for page in stream.rows(session).pages:
        data = page.to_arrow()
        for batch in (data.to_batches() if hasattr(data, "to_batches") else [data]):
            yield _flat_arrow(batch)
