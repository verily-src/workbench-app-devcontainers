import logging
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

def _validate(*identifiers: str):
    for ident in identifiers:
        if not _IDENTIFIER.match(ident):
            raise ValueError(f"Invalid BigQuery identifier: {ident!r}")

@ttl_cache(ttl=300)
def list_tables(project: str, dataset: str) -> list[str]:
    _validate(project, dataset)
    tables = [t.table_id
              for t in _client(project).list_tables(f"{project}.{dataset}")]
    logger.info("Found %d tables in %s.%s", len(tables), project, dataset)
    return tables

@ttl_cache(ttl=600, maxsize=4)
def fetch_table(project: str, dataset: str, table: str, cap: int) -> pd.DataFrame:

    _validate(project, dataset, table)
    query = f"SELECT * FROM `{project}.{dataset}.{table}` LIMIT {int(cap)}"
    return _client(project).query(query).to_dataframe()
