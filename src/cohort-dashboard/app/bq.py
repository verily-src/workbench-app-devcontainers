"""BigQuery engine for GCP workspaces.

BQ_DATASET is a first-class Workbench resource type; on a GCP workspace
the VM's gcloud application-default credentials authorize the client.
"""

import logging
import re

import pandas as pd

logger = logging.getLogger(__name__)

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_\-]+$")


def _validate(*identifiers: str):
    for ident in identifiers:
        if not _IDENTIFIER.match(ident):
            raise ValueError(f"Invalid BigQuery identifier: {ident!r}")


def list_tables(project: str, dataset: str) -> list[str]:
    from google.cloud import bigquery
    _validate(project, dataset)
    client = bigquery.Client(project=project)
    tables = [t.table_id for t in client.list_tables(f"{project}.{dataset}")]
    logger.info("Found %d tables in %s.%s", len(tables), project, dataset)
    return tables


def fetch_table(project: str, dataset: str, table: str, cap: int) -> pd.DataFrame:
    from google.cloud import bigquery
    _validate(project, dataset, table)
    client = bigquery.Client(project=project)
    query = f"SELECT * FROM `{project}.{dataset}.{table}` LIMIT {int(cap)}"
    return client.query(query).to_dataframe()
