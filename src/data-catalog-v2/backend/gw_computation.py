"""
Translates Graphic Walker IDataQueryPayload workflows into BigQuery SQL
and executes them, returning rows for the visualization engine.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from google.cloud import bigquery

MAX_ROWS = 50_000


def execute_workflow(
    fq_table: str,
    payload: dict[str, Any],
    billing_project: Optional[str] = None,
) -> list[dict[str, Any]]:
    sql = translate(fq_table, payload)
    client = bigquery.Client(project=billing_project)
    rows = client.query(sql).result()
    return [dict(r) for r in rows]


def translate(fq_table: str, payload: dict[str, Any]) -> str:
    workflow: list[dict] = payload.get("workflow", [])
    limit = payload.get("limit") or MAX_ROWS
    offset = payload.get("offset") or 0

    where_clauses: list[str] = []
    transforms: list[dict] = []
    view_query: Optional[dict] = None
    order_clauses: list[str] = []

    for step in workflow:
        stype = step.get("type")
        if stype == "filter":
            where_clauses.extend(_build_filters(step.get("filters", [])))
        elif stype == "transform":
            transforms.extend(step.get("transform", []))
        elif stype == "view":
            queries = step.get("query", [])
            if queries:
                view_query = queries[0]
        elif stype == "sort":
            direction = "ASC" if step.get("sort") == "ascending" else "DESC"
            for col in step.get("by", []):
                order_clauses.append(f"`{_safe(col)}` {direction}")

    safe_table = _safe_table(fq_table)

    if view_query is None:
        sql = f"SELECT * FROM `{safe_table}`"
        if where_clauses:
            sql += " WHERE " + " AND ".join(where_clauses)
        if order_clauses:
            sql += " ORDER BY " + ", ".join(order_clauses)
        sql += f" LIMIT {int(limit)} OFFSET {int(offset)}"
        return sql

    op = view_query.get("op")

    if op == "raw":
        fields = view_query.get("fields", [])
        select_cols = ", ".join(f"`{_safe(f)}`" for f in fields) if fields else "*"
        sql = f"SELECT {select_cols} FROM `{safe_table}`"
        if where_clauses:
            sql += " WHERE " + " AND ".join(where_clauses)
        if order_clauses:
            sql += " ORDER BY " + ", ".join(order_clauses)
        sql += f" LIMIT {int(limit)} OFFSET {int(offset)}"
        return sql

    if op == "aggregate":
        return _build_agg_query(
            safe_table, view_query, where_clauses, order_clauses,
            transforms, limit, offset,
        )

    if op == "bin":
        return _build_bin_query(
            safe_table, view_query, where_clauses, order_clauses,
            limit, offset,
        )

    if op == "fold":
        return _build_fold_query(
            safe_table, view_query, where_clauses, order_clauses,
            limit, offset,
        )

    sql = f"SELECT * FROM `{safe_table}`"
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    sql += f" LIMIT {int(limit)} OFFSET {int(offset)}"
    return sql


def _build_agg_query(
    table: str,
    vq: dict,
    where: list[str],
    order: list[str],
    transforms: list[dict],
    limit: int,
    offset: int,
) -> str:
    group_by = vq.get("groupBy", [])
    measures = vq.get("measures", [])

    select_parts: list[str] = []
    bin_expressions: dict[str, str] = {}

    for t in transforms:
        expr = t.get("expression", {})
        expr_op = expr.get("op")
        if expr_op == "bin":
            params = expr.get("params", [])
            src_field = _param_value(params, "field")
            bin_size = _param_value(params, "value")
            as_name = expr.get("as", t.get("key", ""))
            if src_field and bin_size:
                bin_expr = f"FLOOR(CAST(`{_safe(src_field)}` AS FLOAT64) / {float(bin_size)}) * {float(bin_size)}"
                bin_expressions[as_name] = bin_expr
        elif expr_op == "dateTimeDrill":
            params = expr.get("params", [])
            src_field = _param_value(params, "field")
            drill_level = _param_value(params, "value")
            as_name = expr.get("as", t.get("key", ""))
            if src_field:
                bin_expressions[as_name] = _date_drill_expr(src_field, drill_level)

    for col in group_by:
        if col in bin_expressions:
            select_parts.append(f"{bin_expressions[col]} AS `{_safe(col)}`")
        else:
            select_parts.append(f"`{_safe(col)}`")

    for m in measures:
        field = m.get("field", "")
        agg = m.get("agg", "count")
        as_key = m.get("asFieldKey", field)
        agg_expr = _agg_expression(field, agg)
        select_parts.append(f"{agg_expr} AS `{_safe(as_key)}`")

    sql = f"SELECT {', '.join(select_parts)} FROM `{table}`"
    if where:
        sql += " WHERE " + " AND ".join(where)

    if group_by:
        group_refs = []
        for i, col in enumerate(group_by):
            group_refs.append(str(i + 1))
        sql += " GROUP BY " + ", ".join(group_refs)

    if order:
        sql += " ORDER BY " + ", ".join(order)

    sql += f" LIMIT {int(limit)} OFFSET {int(offset)}"
    return sql


def _build_bin_query(
    table: str, vq: dict, where: list[str],
    order: list[str], limit: int, offset: int,
) -> str:
    bin_by = vq.get("binBy", "")
    new_col = vq.get("newBinCol", bin_by + "_bin")
    bin_size = vq.get("binSize", 10)

    bin_expr = f"FLOOR(CAST(`{_safe(bin_by)}` AS FLOAT64) / {float(bin_size)}) * {float(bin_size)}"
    sql = f"SELECT *, {bin_expr} AS `{_safe(new_col)}` FROM `{table}`"
    if where:
        sql += " WHERE " + " AND ".join(where)
    if order:
        sql += " ORDER BY " + ", ".join(order)
    sql += f" LIMIT {int(limit)} OFFSET {int(offset)}"
    return sql


def _build_fold_query(
    table: str, vq: dict, where: list[str],
    order: list[str], limit: int, offset: int,
) -> str:
    fold_by = vq.get("foldBy", [])
    key_col = vq.get("newFoldKeyCol", "key")
    val_col = vq.get("newFoldValueCol", "value")

    if not fold_by:
        return f"SELECT * FROM `{table}` LIMIT {limit}"

    unions = []
    for col in fold_by:
        unions.append(
            f"SELECT *, '{_safe(col)}' AS `{_safe(key_col)}`, "
            f"CAST(`{_safe(col)}` AS STRING) AS `{_safe(val_col)}` "
            f"FROM `{table}`"
        )

    inner = " UNION ALL ".join(unions)
    sql = f"SELECT * FROM ({inner})"
    if where:
        sql += " WHERE " + " AND ".join(where)
    if order:
        sql += " ORDER BY " + ", ".join(order)
    sql += f" LIMIT {int(limit)} OFFSET {int(offset)}"
    return sql


def _build_filters(filters: list[dict]) -> list[str]:
    clauses: list[str] = []
    for f in filters:
        fid = f.get("fid", "")
        rule = f.get("rule")
        if not rule or not fid:
            continue
        rtype = rule.get("type")
        val = rule.get("value")

        if rtype == "range" and isinstance(val, list) and len(val) == 2:
            lo, hi = val
            if lo is not None:
                clauses.append(f"`{_safe(fid)}` >= {_literal(lo)}")
            if hi is not None:
                clauses.append(f"`{_safe(fid)}` <= {_literal(hi)}")

        elif rtype == "temporal range" and isinstance(val, list) and len(val) == 2:
            lo, hi = val
            if lo is not None:
                clauses.append(f"UNIX_MILLIS(CAST(`{_safe(fid)}` AS TIMESTAMP)) >= {int(lo)}")
            if hi is not None:
                clauses.append(f"UNIX_MILLIS(CAST(`{_safe(fid)}` AS TIMESTAMP)) <= {int(hi)}")

        elif rtype == "one of" and isinstance(val, list):
            if val:
                literals = ", ".join(_literal(v) for v in val)
                clauses.append(f"`{_safe(fid)}` IN ({literals})")

        elif rtype == "not in" and isinstance(val, list):
            if val:
                literals = ", ".join(_literal(v) for v in val)
                clauses.append(f"`{_safe(fid)}` NOT IN ({literals})")

    return clauses


def _agg_expression(field: str, agg: str) -> str:
    agg_map = {
        "sum": "SUM",
        "count": "COUNT",
        "max": "MAX",
        "min": "MIN",
        "mean": "AVG",
        "median": "APPROX_QUANTILES({col}, 2)[OFFSET(1)]",
        "variance": "VARIANCE",
        "stdev": "STDDEV",
        "distinctCount": "COUNT(DISTINCT {col})",
    }
    if agg == "count" and (not field or field == "*"):
        return "COUNT(*)"

    template = agg_map.get(agg, "COUNT")
    col = f"`{_safe(field)}`"

    if "{col}" in template:
        return template.replace("{col}", col)
    return f"{template}({col})"


def _date_drill_expr(field: str, level: Optional[str]) -> str:
    col = f"`{_safe(field)}`"
    mapping = {
        "year": f"EXTRACT(YEAR FROM CAST({col} AS TIMESTAMP))",
        "quarter": f"EXTRACT(QUARTER FROM CAST({col} AS TIMESTAMP))",
        "month": f"EXTRACT(MONTH FROM CAST({col} AS TIMESTAMP))",
        "week": f"EXTRACT(WEEK FROM CAST({col} AS TIMESTAMP))",
        "day": f"EXTRACT(DAY FROM CAST({col} AS TIMESTAMP))",
        "hour": f"EXTRACT(HOUR FROM CAST({col} AS TIMESTAMP))",
        "minute": f"EXTRACT(MINUTE FROM CAST({col} AS TIMESTAMP))",
    }
    return mapping.get(level or "year", f"CAST({col} AS STRING)")


def _param_value(params: list[dict], ptype: str) -> Any:
    for p in params:
        if p.get("type") == ptype:
            return p.get("value")
    return None


_SAFE_COL_RE = re.compile(r"[^a-zA-Z0-9_]")
_SAFE_TABLE_RE = re.compile(r"[^a-zA-Z0-9_.\-]")


def _safe(name: str) -> str:
    """Sanitise a column name (alphanumeric + underscore only)."""
    return _SAFE_COL_RE.sub("", name)


def _safe_table(fq: str) -> str:
    """Sanitise a fully-qualified table reference (allows hyphens for GCP project IDs)."""
    return _SAFE_TABLE_RE.sub("", fq)


def _literal(val: Any) -> str:
    if val is None:
        return "NULL"
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if isinstance(val, (int, float)):
        return str(val)
    escaped = str(val).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"
