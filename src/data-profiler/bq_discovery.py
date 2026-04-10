"""
BigQuery dataset and table discovery via INFORMATION_SCHEMA.

Handles:
  - Dataset listing for a project
  - Table listing with full column schema for a dataset
"""

from __future__ import annotations

from typing import Optional

from models import BQColumnInfo, BQTableInfo


def discover_bq_datasets(
    project_id: str,
    billing_project_id: Optional[str] = None,
) -> list[str]:
    """List all datasets in a BigQuery project."""
    from google.cloud import bigquery

    client = bigquery.Client(project=billing_project_id or project_id)
    try:
        datasets = list(client.list_datasets(project_id))
        return sorted([ds.dataset_id for ds in datasets])
    except Exception as e:
        print(f"Could not list datasets in {project_id}: {e}")
        return []


def discover_bq_tables(
    project_id: str,
    dataset_id: str,
    billing_project_id: Optional[str] = None,
) -> list[BQTableInfo]:
    """
    Discover all tables in a BigQuery dataset with column details.
    Queries INFORMATION_SCHEMA for complete schema information.
    """
    from google.cloud import bigquery

    client = bigquery.Client(project=billing_project_id or project_id)
    tables: list[BQTableInfo] = []

    try:
        tables_sql = f"""
        SELECT table_name, table_type, row_count, size_bytes
        FROM `{project_id}.{dataset_id}.INFORMATION_SCHEMA.TABLES`
        ORDER BY table_name
        """
        table_rows = client.query(tables_sql).result()
        table_meta = {
            row.table_name: {
                "table_type": row.table_type,
                "row_count": row.row_count,
                "size_bytes": row.size_bytes,
            }
            for row in table_rows
        }
    except Exception as e:
        print(f"Could not query INFORMATION_SCHEMA.TABLES: {e}")
        table_meta = {}

    try:
        cols_sql = f"""
        SELECT table_name, column_name, data_type, is_nullable, description, ordinal_position
        FROM `{project_id}.{dataset_id}.INFORMATION_SCHEMA.COLUMN_FIELD_PATHS`
        ORDER BY table_name, ordinal_position
        """
        col_rows = list(client.query(cols_sql).result())
    except Exception:
        try:
            cols_sql = f"""
            SELECT table_name, column_name, data_type, is_nullable, ordinal_position
            FROM `{project_id}.{dataset_id}.INFORMATION_SCHEMA.COLUMNS`
            ORDER BY table_name, ordinal_position
            """
            col_rows = list(client.query(cols_sql).result())
        except Exception as e:
            print(f"Could not query INFORMATION_SCHEMA.COLUMNS: {e}")
            col_rows = []

    table_columns: dict[str, list[BQColumnInfo]] = {}
    for row in col_rows:
        col = BQColumnInfo(
            column_name=row.column_name,
            data_type=row.data_type,
            is_nullable=getattr(row, "is_nullable", "YES"),
            description=getattr(row, "description", None),
            ordinal_position=getattr(row, "ordinal_position", 0),
        )
        table_columns.setdefault(row.table_name, []).append(col)

    all_table_names = set(table_meta.keys()) | set(table_columns.keys())
    for table_name in sorted(all_table_names):
        meta = table_meta.get(table_name, {})
        info = BQTableInfo(
            project_id=project_id,
            dataset_id=dataset_id,
            table_id=table_name,
            columns=table_columns.get(table_name, []),
            row_count=meta.get("row_count"),
            size_bytes=meta.get("size_bytes"),
            table_type=meta.get("table_type", "BASE TABLE"),
        )
        tables.append(info)

    return tables
