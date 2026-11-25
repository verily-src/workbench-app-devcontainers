"""BigQuery dataset and table discovery."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from verily_profiler.models import BQColumnInfo, BQTableInfo


def get_table_api_metadata(
    project_id: str,
    dataset_id: str,
    table_id: str,
    *,
    billing_project: Optional[str] = None,
    log_failures: bool = False,
) -> tuple[Optional[int], Optional[int]]:
    """Return ``(num_rows, num_bytes)`` from the BigQuery Tables API.

    Use when ``INFORMATION_SCHEMA.TABLE_STORAGE`` is unavailable or omits
    ``total_logical_bytes``. Bytes come from the table resource's ``num_bytes``
    (storage size used for catalog display).
    """
    from google.cloud import bigquery

    client = bigquery.Client(project=billing_project or project_id)
    fq = f"{project_id}.{dataset_id}.{table_id}"
    try:
        t = client.get_table(fq)
        rows = getattr(t, "num_rows", None)
        nbytes = getattr(t, "num_bytes", None)
        return rows, nbytes
    except Exception as exc:
        if log_failures:
            print(f"  Tables API metadata failed for {fq}: {exc}")
        return None, None


def discover_datasets(
    project_id: str,
    billing_project: Optional[str] = None,
) -> list[str]:
    """List all datasets in a BigQuery project."""
    from google.cloud import bigquery

    client = bigquery.Client(project=billing_project or project_id)
    try:
        datasets = list(client.list_datasets(project_id))
        return sorted([ds.dataset_id for ds in datasets])
    except Exception as e:
        print(f"Could not list datasets in {project_id}: {e}")
        return []


def discover_tables(
    project_id: str,
    dataset_id: str,
    billing_project: Optional[str] = None,
) -> list[BQTableInfo]:
    """Discover all tables in a BigQuery dataset with column details.

    Runs TABLES+STORAGE and COLUMNS queries in parallel for speed.
    """
    from google.cloud import bigquery

    client = bigquery.Client(project=billing_project or project_id)

    table_meta: dict[str, dict] = {}
    col_rows: list = []

    def _fetch_tables_and_storage():
        meta: dict[str, dict] = {}
        try:
            q = f"""
            SELECT
                t.table_name, t.table_type,
                s.total_rows, s.total_logical_bytes
            FROM `{project_id}.{dataset_id}.INFORMATION_SCHEMA.TABLES` t
            LEFT JOIN `{project_id}.{dataset_id}.INFORMATION_SCHEMA.TABLE_STORAGE` s
                ON t.table_name = s.table_name
            ORDER BY t.table_name
            """
            for row in client.query(q).result():
                meta[row.table_name] = {
                    "table_type": row.table_type,
                    "row_count": getattr(row, "total_rows", None),
                    "size_bytes": getattr(row, "total_logical_bytes", None),
                }
        except Exception:
            try:
                q_tables = f"""
                SELECT table_name, table_type
                FROM `{project_id}.{dataset_id}.INFORMATION_SCHEMA.TABLES`
                ORDER BY table_name
                """
                for row in client.query(q_tables).result():
                    meta[row.table_name] = {"table_type": row.table_type, "row_count": None, "size_bytes": None}

                q_storage = f"""
                SELECT table_name, total_rows, total_logical_bytes
                FROM `{project_id}.{dataset_id}.INFORMATION_SCHEMA.TABLE_STORAGE`
                """
                for row in client.query(q_storage).result():
                    if row.table_name in meta:
                        meta[row.table_name]["row_count"] = row.total_rows
                        meta[row.table_name]["size_bytes"] = row.total_logical_bytes
            except Exception as e2:
                print(f"  Tables/storage discovery failed for {dataset_id}: {e2}")
        return meta

    def _fetch_columns():
        rows = []
        try:
            q = f"""
            SELECT table_name, column_name, data_type, is_nullable, ordinal_position
            FROM `{project_id}.{dataset_id}.INFORMATION_SCHEMA.COLUMNS`
            ORDER BY table_name, ordinal_position
            """
            rows = list(client.query(q).result())
        except Exception as e:
            print(f"  Column discovery failed for {dataset_id}: {e}")
        return rows

    with ThreadPoolExecutor(max_workers=2) as ex:
        f_meta = ex.submit(_fetch_tables_and_storage)
        f_cols = ex.submit(_fetch_columns)
        table_meta = f_meta.result()
        col_rows = f_cols.result()

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

    tables: list[BQTableInfo] = []
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
