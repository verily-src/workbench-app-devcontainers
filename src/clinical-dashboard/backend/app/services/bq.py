"""BigQuery service for data queries"""
from google.cloud import bigquery
from ..config import get_settings

settings = get_settings()


def get_bq_client() -> bigquery.Client:
    """Get a BigQuery client with cost guardrails."""
    # Use app_project for authentication, query data from bhs_project
    client = bigquery.Client(project=settings.app_project)
    return client


def query_to_dataframe(query: str):
    """Execute a BigQuery query and return a pandas DataFrame."""
    client = get_bq_client()

    job_config = bigquery.QueryJobConfig(
        maximum_bytes_billed=settings.bq_max_bytes_billed
    )

    query_job = client.query(query, job_config=job_config)
    return query_job.to_dataframe()
