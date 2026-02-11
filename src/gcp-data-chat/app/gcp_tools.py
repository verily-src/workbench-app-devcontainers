"""
GCP data operations: GCS, BigQuery, Secret Manager.
Uses Application Default Credentials (ADC) — no API key needed for GCP in Workbench.
"""
import io
from typing import Optional

import pandas as pd
from google.cloud import storage, bigquery
from google.auth import default as auth_default


def get_default_project() -> Optional[str]:
    """Get the default GCP project from Application Default Credentials."""
    try:
        _, project = auth_default()
        return project
    except Exception:
        return None


def list_gcs_buckets(project: Optional[str] = None) -> list[str]:
    """List bucket names the current credentials can access."""
    client = storage.Client(project=project)
    return sorted([b.name for b in client.list_buckets()])


def list_gcs_blobs(bucket_name: str, prefix: str = "", max_results: int = 500) -> list[str]:
    """List blob paths in a bucket under optional prefix."""
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blobs = list(bucket.list_blobs(prefix=prefix or None, max_results=max_results))
    return [b.name for b in blobs]


def load_from_gcs(bucket_name: str, path: str, fmt: str = "csv") -> pd.DataFrame:
    """Load a file from GCS into a DataFrame. path is blob path (no gs://)."""
    client = storage.Client()
    bucket = client.bucket(bucket_name.strip())
    blob = bucket.blob(path.strip().lstrip("/"))
    data = blob.download_as_bytes()
    fmt = fmt.lower()
    if fmt in ("csv", "txt"):
        return pd.read_csv(io.BytesIO(data))
    if fmt == "parquet":
        return pd.read_parquet(io.BytesIO(data))
    if fmt == "json":
        return pd.read_json(io.BytesIO(data))
    return pd.read_csv(io.BytesIO(data))


def list_bigquery_datasets(project: str) -> list[str]:
    """List dataset IDs in a project."""
    client = bigquery.Client(project=project)
    return sorted([d.dataset_id for d in client.list_datasets(project=project)])


def list_bigquery_tables(project: str, dataset: str) -> list[str]:
    """List table IDs in a dataset."""
    client = bigquery.Client(project=project)
    return sorted([t.table_id for t in client.list_tables(f"{project}.{dataset}")])


def load_from_bigquery(
    project: str, dataset: str, table: str, limit: int = 50_000
) -> pd.DataFrame:
    """Load a BigQuery table into a DataFrame (with optional row limit)."""
    client = bigquery.Client(project=project)
    full_id = f"`{project}.{dataset}.{table}`"
    query = f"SELECT * FROM {full_id} LIMIT {limit}"
    return client.query(query).to_dataframe()


def fetch_secret(project_id: str, secret_name: str, version: str = "latest") -> str:
    """Fetch a secret value from Google Cloud Secret Manager."""
    from google.cloud import secretmanager

    name = f"projects/{project_id}/secrets/{secret_name}/versions/{version}"
    client = secretmanager.SecretManagerServiceClient()
    response = client.access_secret_version(name=name)
    return response.payload.data.decode("UTF-8")
