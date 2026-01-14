"""BigQuery service for query execution and schema discovery."""

from google.cloud import bigquery
from google.api_core import exceptions
import pandas as pd
from typing import Dict, List, Optional, Tuple
import time
from config import AppConfig


class BigQueryService:
    """Handles BigQuery operations."""

    def __init__(self, config: AppConfig):
        """
        Initialize BigQuery service.

        Args:
            config: Application configuration
        """
        self.config = config
        self.client = bigquery.Client(project=config.project_id)

    def execute_query(self, sql: str) -> Tuple[Optional[pd.DataFrame], Dict]:
        """
        Execute SQL query and return results.

        Args:
            sql: SQL query to execute

        Returns:
            Tuple of (dataframe, metadata) where metadata contains query stats
        """
        metadata = {
            "success": False,
            "row_count": 0,
            "bytes_processed": 0,
            "execution_time_ms": 0,
            "error": None
        }

        start_time = time.time()

        try:
            # Configure query job
            job_config = bigquery.QueryJobConfig(
                use_query_cache=True,
                maximum_bytes_billed=self.config.max_bytes_billed,
            )

            # Execute query
            query_job = self.client.query(sql, job_config=job_config)

            # Wait for results with timeout
            df = query_job.result(
                timeout=self.config.query_timeout_seconds
            ).to_dataframe(max_results=self.config.max_results)

            # Update metadata
            metadata.update({
                "success": True,
                "row_count": len(df),
                "bytes_processed": query_job.total_bytes_processed or 0,
                "execution_time_ms": int((time.time() - start_time) * 1000),
                "bytes_billed": query_job.total_bytes_billed or 0,
                "cache_hit": query_job.cache_hit or False
            })

            return df, metadata

        except exceptions.Forbidden as e:
            metadata["error"] = f"Permission denied: {str(e)}"
            metadata["execution_time_ms"] = int((time.time() - start_time) * 1000)
            return None, metadata

        except exceptions.BadRequest as e:
            metadata["error"] = f"Invalid query: {str(e)}"
            metadata["execution_time_ms"] = int((time.time() - start_time) * 1000)
            return None, metadata

        except exceptions.DeadlineExceeded:
            metadata["error"] = f"Query timeout exceeded ({self.config.query_timeout_seconds}s)"
            metadata["execution_time_ms"] = int((time.time() - start_time) * 1000)
            return None, metadata

        except Exception as e:
            metadata["error"] = f"Query execution failed: {str(e)}"
            metadata["execution_time_ms"] = int((time.time() - start_time) * 1000)
            return None, metadata

    def get_dataset_schema(self, dataset_id: str) -> Dict[str, List[Dict]]:
        """
        Get schema information for all tables in a dataset.

        Args:
            dataset_id: BigQuery dataset ID

        Returns:
            Dict mapping table names to their column schemas
        """
        schema_info = {}

        try:
            dataset_ref = f"{self.config.project_id}.{dataset_id}"
            tables = list(self.client.list_tables(dataset_ref))

            for table_item in tables:
                table = self.client.get_table(table_item)
                schema_info[table.table_id] = [
                    {
                        "name": field.name,
                        "type": field.field_type,
                        "mode": field.mode,
                        "description": field.description or ""
                    }
                    for field in table.schema
                ]

        except exceptions.NotFound:
            schema_info["error"] = f"Dataset '{dataset_id}' not found"
        except exceptions.Forbidden:
            schema_info["error"] = f"Permission denied for dataset '{dataset_id}'"
        except Exception as e:
            schema_info["error"] = f"Error loading schema: {str(e)}"

        return schema_info

    def list_datasets(self) -> List[str]:
        """
        List all datasets in the project.

        Returns:
            List of dataset IDs
        """
        try:
            datasets = list(self.client.list_datasets())
            return [dataset.dataset_id for dataset in datasets]
        except exceptions.Forbidden:
            return []
        except Exception:
            return []

    def get_table_preview(
        self,
        dataset_id: str,
        table_id: str,
        limit: int = 5
    ) -> Optional[pd.DataFrame]:
        """
        Get a preview of table data.

        Args:
            dataset_id: BigQuery dataset ID
            table_id: BigQuery table ID
            limit: Number of rows to preview

        Returns:
            DataFrame with preview data or None if error
        """
        try:
            query = f"""
            SELECT *
            FROM `{self.config.project_id}.{dataset_id}.{table_id}`
            LIMIT {limit}
            """
            df, _ = self.execute_query(query)
            return df
        except Exception:
            return None

    def test_connection(self) -> Tuple[bool, str]:
        """
        Test BigQuery connection and permissions.

        Returns:
            Tuple of (success, message)
        """
        try:
            # Try to list datasets
            datasets = self.list_datasets()
            if datasets:
                return True, f"Connected successfully. Found {len(datasets)} datasets."
            else:
                return True, "Connected successfully. No datasets found or no permissions."
        except Exception as e:
            return False, f"Connection failed: {str(e)}"
