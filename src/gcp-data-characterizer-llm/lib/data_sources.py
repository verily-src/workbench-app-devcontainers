"""Load data from GCS or BigQuery for profiling and chat."""
import io
import pandas as pd
from google.cloud import storage
from google.cloud import bigquery


def load_from_gcs(bucket_name: str, path: str, format: str = "csv") -> pd.DataFrame:
    """Load a file from GCS into a DataFrame. path is blob path (no gs://)."""
    client = storage.Client()
    bucket = client.bucket(bucket_name.strip())
    blob = bucket.blob(path.strip().lstrip("/"))
    data = blob.download_as_bytes()
    if format.lower() in ("csv", "txt"):
        return pd.read_csv(io.BytesIO(data))
    if format.lower() == "parquet":
        return pd.read_parquet(io.BytesIO(data))
    if format.lower() == "json":
        return pd.read_json(io.BytesIO(data))
    return pd.read_csv(io.BytesIO(data))


def load_from_bigquery(
    project: str, dataset: str, table: str, limit: int = 100_000
) -> pd.DataFrame:
    """Load a BigQuery table into a DataFrame (with optional row limit)."""
    client = bigquery.Client(project=project)
    full_id = f"`{project}.{dataset}.{table}`"
    query = f"SELECT * FROM {full_id} LIMIT {limit}"
    return client.query(query).to_dataframe()


def list_gcs_buckets(project: str | None = None) -> list[str]:
    """List bucket names the current credentials can access."""
    client = storage.Client(project=project)
    return [b.name for b in client.list_buckets()]


def list_gcs_blobs(bucket_name: str, prefix: str = "", max_results: int = 500) -> list[str]:
    """List blob paths in a bucket under optional prefix."""
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blobs = list(bucket.list_blobs(prefix=prefix or None, max_results=max_results))
    return [b.name for b in blobs]


def list_bigquery_datasets(project: str) -> list[str]:
    """List dataset IDs in a project."""
    client = bigquery.Client(project=project)
    return [d.dataset_id for d in client.list_datasets(project=project)]


def list_bigquery_tables(project: str, dataset: str) -> list[str]:
    """List table IDs in a dataset."""
    client = bigquery.Client(project=project)
    return [t.table_id for t in client.list_tables(f"{project}.{dataset}")]
