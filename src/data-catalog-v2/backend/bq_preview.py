"""
BigQuery table preview: capped sample rows + schema (read-only).
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Optional

from google.cloud import bigquery

from verily_profiler.models import BQTableInfo

MAX_PREVIEW_ROWS = 500
MAX_EXPLORE_ROWS = 5000


def _serialize_cell(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, (bytes,)):
        return val.decode("utf-8", errors="replace")
    if isinstance(val, Decimal):
        return float(val)
    if hasattr(val, "isoformat"):
        return val.isoformat()
    if isinstance(val, (dict, list)):
        return json.loads(json.dumps(val, default=str))
    return val


def preview_table(
    table_info: BQTableInfo,
    billing_project_id: Optional[str] = None,
    limit: int = MAX_PREVIEW_ROWS,
) -> dict[str, Any]:
    """
    Run SELECT * FROM table LIMIT N. Returns columns + rows (JSON-serializable).
    """
    limit = max(1, min(int(limit), MAX_EXPLORE_ROWS))
    client = bigquery.Client(project=billing_project_id or table_info.project_id)
    fq = f"`{table_info.project_id}.{table_info.dataset_id}.{table_info.table_id}`"
    sql = f"SELECT * FROM {fq} LIMIT {limit}"

    query_job = client.query(sql)
    rows = list(query_job.result())
    schema_fields = list(query_job.schema or [])

    if schema_fields:
        columns_meta = [
            {
                "name": f.name,
                "type": f.field_type,
                "mode": getattr(f, "mode", "NULLABLE"),
            }
            for f in schema_fields
        ]
    elif table_info.columns:
        columns_meta = [
            {
                "name": c.column_name,
                "type": c.data_type,
                "mode": "NULLABLE" if c.is_nullable == "YES" else "REQUIRED",
                "description": c.description,
            }
            for c in table_info.columns
        ]
    elif rows:
        columns_meta = [{"name": k, "type": "UNKNOWN", "mode": "NULLABLE"} for k in rows[0].keys()]
    else:
        columns_meta = []

    out_rows: list[list[Any]] = []
    for r in rows:
        out_rows.append([_serialize_cell(r[k]) for k in r.keys()])

    total_rows = table_info.row_count
    return {
        "fq_table": table_info.fq_name,
        "columns": columns_meta,
        "rows": out_rows,
        "preview_row_count": len(out_rows),
        "total_rows": total_rows,
        "size_bytes": table_info.size_bytes,
    }
