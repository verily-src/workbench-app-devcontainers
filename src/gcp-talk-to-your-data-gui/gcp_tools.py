"""
GCP data source discovery, load, and LLM 'talk to your data'.
Uses Application Default Credentials (ADC) - no API key needed for GCP in Workbench.
"""
import io
from typing import Optional

import pandas as pd
from google.cloud import storage
from google.cloud import bigquery
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


def list_bigquery_datasets(project: str) -> list[str]:
    """List dataset IDs in a project."""
    client = bigquery.Client(project=project)
    return sorted([d.dataset_id for d in client.list_datasets(project=project)])


def list_bigquery_tables(project: str, dataset: str) -> list[str]:
    """List table IDs in a dataset."""
    client = bigquery.Client(project=project)
    return sorted([t.table_id for t in client.list_tables(f"{project}.{dataset}")])


def load_from_bigquery(
    project: str, dataset: str, table: str, limit: int = 100_000
) -> pd.DataFrame:
    """Load a BigQuery table into a DataFrame (with optional row limit)."""
    client = bigquery.Client(project=project)
    full_id = f"`{project}.{dataset}.{table}`"
    query = f"SELECT * FROM {full_id} LIMIT {limit}"
    return client.query(query).to_dataframe()


def get_openai_key_from_secret_manager(project_id: str, team_alias: str) -> str:
    """
    Fetch the OpenAI API key from Google Cloud Secret Manager (team-alias format).
    Secret name: {team_alias}openai-api-key, version: live.
    """
    from google.cloud import secretmanager
    name = f"projects/{project_id}/secrets/{team_alias}openai-api-key/versions/live"
    client = secretmanager.SecretManagerServiceClient()
    response = client.access_secret_version(name=name)
    return response.payload.data.decode("UTF-8")


def get_openai_key_by_secret_name(
    project_id: str, secret_name: str, version: str = "latest"
) -> str:
    """
    Fetch the OpenAI API key from Secret Manager by full secret name.
    E.g. project_id='wb-smart-cabbage-5940', secret_name='si-ops-openai-api-key', version='latest'.
    """
    from google.cloud import secretmanager
    name = f"projects/{project_id}/secrets/{secret_name}/versions/{version}"
    client = secretmanager.SecretManagerServiceClient()
    response = client.access_secret_version(name=name)
    return response.payload.data.decode("UTF-8")


def data_summary_for_llm(df: pd.DataFrame) -> tuple[str, str]:
    """Return (data_summary, schema_and_sample) for LLM context."""
    data_summary = (
        f"Rows: {len(df):,}, Columns: {len(df.columns)}. "
        f"Column names: {list(df.columns)}."
    )
    schema_and_sample = (
        f"dtypes:\n{df.dtypes.to_string()}\n\n"
        f"Sample (first 20 rows):\n{df.head(20).to_string()}"
    )
    return data_summary, schema_and_sample


# US endpoint for company keys (e.g. Verily)
OPENAI_US_BASE_URL = "https://us.api.openai.com/v1/"


def talk_to_data(
    api_key: str,
    data_summary: str,
    schema_and_sample: str,
    question: str,
    model: str = "gpt-4o-mini",
    base_url: Optional[str] = None,
) -> str:
    """
    Send question + data context to an OpenAI-compatible LLM.
    Use base_url=OPENAI_US_BASE_URL for company keys that require the US endpoint.
    """
    if not api_key or not api_key.strip():
        return "Please provide your LLM API key to use Talk to your data."

    try:
        from openai import OpenAI
    except ImportError:
        return "Install openai: pip install openai"

    client = OpenAI(
        api_key=api_key.strip(),
        base_url=base_url or "https://api.openai.com/v1",
    )
    system = """You are a helpful data analyst. The user is asking questions about a dataset.
Use the following context about the data to answer accurately. If the question cannot be answered from the context, say so.
You can describe patterns, suggest aggregations, or answer factual questions about the schema and sample.
Be concise. If the user asks for code (e.g. Python/pandas), you may provide it in a markdown code block."""
    user_content = (
        f"## Data summary\n{data_summary}\n\n"
        f"## Schema and sample\n{schema_and_sample}\n\n"
        f"## User question\n{question}"
    )
    try:
        response = client.chat.completions.create(
            model=model.strip() or "gpt-4o-mini",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            max_tokens=1024,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"LLM error: {e}"
