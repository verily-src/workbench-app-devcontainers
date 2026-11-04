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
