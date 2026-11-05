import math
import os

import pandas as pd
from pydantic import Field

import data_jobs
import database as db
import datasets
import disk_data
import execution
import live_query
import queries
import query_cancellation
from source_models import SummaryFilter, SummarySpec
from sql_utils import statement as text

__all__ = ["SummaryFilter", "SummarySpec", "SummaryRequest", "MaterializeRequest",
           "summarize", "materialize"]


class SummaryRequest(SummarySpec):
    filters: list[SummaryFilter] = Field(default_factory=list, max_length=200)
    page: int = Field(default=0, ge=0, le=10000000)
    page_size: int = Field(default=50, ge=1, le=200)


class MaterializeRequest(SummarySpec):
    """The full summary (every group, no display page) opened as a new dataset."""
    filters: list[SummaryFilter] = Field(default_factory=list, max_length=200)


def _clean(value):
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _aliases(groups, measure):
    used = set(groups)
    result = []
    for name in (["Rows", "Numeric values", "Sum", "Mean", "Minimum", "Maximum"] if measure else ["Rows"]):
        candidate = name
        while candidate in used:
            candidate += " (summary)"
        used.add(candidate)
        result.append(candidate)
    return result


def _sql_summary(select_groups, group_expr, number, row_alias, aliases, relation, where):
    q = live_query._q
    metrics = [f"COUNT(*) AS {q(row_alias)}"]
    if number:
        metrics.extend(f"{op}({number}) AS {q(name)}" for op, name in zip(("COUNT", "SUM", "AVG", "MIN", "MAX"), aliases[1:]))
    return f"SELECT {', '.join(select_groups + metrics)} FROM {relation} AS src WHERE {where} GROUP BY {', '.join(group_expr)}"


def _prepare(ds, req):
    columns = list(ds["df"].columns)
    if any(name not in columns for name in [*req.group_by, *([req.measure] if req.measure else [])]):
        raise ValueError("Unknown grouping or value column.")
    filters = [item.model_dump() for item in req.filters]
    if any(item["column"] not in columns for item in filters):
        raise ValueError("Unknown filter column.")
    aliases = _aliases(req.group_by, req.measure)
    order = ", ".join(f"{live_query._q(name)} ASC NULLS LAST" for name in req.group_by)
    return filters, aliases, req.group_by + aliases, order


def _begin_live(con):
    con.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
    con.exec_driver_sql("SET LOCAL search_path = pg_catalog")
    con.exec_driver_sql(f"SET LOCAL statement_timeout = {live_query.TIMEOUT_MS}")


def _live_sql(con, live, req, filters, aliases):
    q = live_query._q
    numeric = live_query._numeric_columns(con, live, [item["column"] for item in filters if item["kind"] == "range"] + ([req.measure] if req.measure else []))
    where, params = live_query._where(filters, live["columns"], numeric)
    groups = [f"src.{q(live['columns'][name])}" for name in req.group_by]
    selection = [f"{col} AS {q(name)}" for col, name in zip(groups, req.group_by)]
    number = live_query._numeric(f"src.{q(live['columns'][req.measure])}", numeric.get(req.measure)) if req.measure else None
    return _sql_summary(selection, groups, number, aliases[0], aliases, f"({live['sql']})", where), params


def _disk_sql(disk, req, filters, aliases, relation):
    q = live_query._q
    where, params = disk_data._where(filters, disk["columns"])
    groups = [f"src.{q(name)}" for name in req.group_by]
    selection = [f"{col} AS {q(name)}" for col, name in zip(groups, req.group_by)]
    numeric = f"TRY_CAST(src.{q(req.measure)} AS DOUBLE)" if req.measure else None
    number = f"CASE WHEN ISFINITE({numeric}) THEN {numeric} END" if numeric else None
    return _sql_summary(selection, groups, number, aliases[0], aliases, relation, where), params


def _disk_scan_bytes(disk):
    return int(disk.get("scan_bytes") or os.path.getsize(disk["path"]))


def _frame_summary(ds, req, filters, aliases):
    frame = datasets.apply_filters(ds["df"], filters)
    work = frame[req.group_by].copy()
    value_name = "__summary_value__"
    while value_name in work.columns:
        value_name += "_"
    if req.measure:
        numeric = pd.to_numeric(frame[req.measure], errors="coerce").replace([float("inf"), float("-inf")], float("nan"))
        work[value_name] = numeric
    grouped = work.groupby(req.group_by, dropna=False, observed=True, sort=True)
    out = grouped.size().rename(aliases[0]).to_frame()
    if req.measure:
        values = grouped[value_name]
        for name, value in zip(aliases[1:], [values.count(), values.sum(min_count=1), values.mean(), values.min(), values.max()]):
            out[name] = value
    out = out.reset_index().sort_values(req.group_by, na_position="last", kind="stable").reset_index(drop=True)
    return out, len(frame)


@execution.workload("interactive")
def summarize(dataset_id: str, request: dict | SummaryRequest) -> dict:
    req = request if isinstance(request, SummaryRequest) else SummaryRequest.model_validate(request)
    ds = datasets.get(dataset_id)
    filters, aliases, result_columns, order = _prepare(ds, req)
    q = live_query._q
    live = ds.get("live_source")
    disk = ds.get("disk_source")
    if live:
        disk_data.guard_live_query(live, [], None)
        with db.get_engine_for_resource(live["resource_id"]).begin() as con:
            _begin_live(con)
            sql, params = _live_sql(con, live, req, filters, aliases)
            totals = live_query._query(con, live, f"SELECT COUNT(*), COALESCE(SUM({q(aliases[0])}), 0) FROM ({sql}) summary", params).one()
            data = live_query._query(con, live, f"SELECT * FROM ({sql}) summary ORDER BY {order} LIMIT :summary_limit OFFSET :summary_offset", {**params, "summary_limit": req.page_size, "summary_offset": req.page * req.page_size}).fetchall()
        scope, sampled = "database", False
    elif disk:
        disk_data._budget(_disk_scan_bytes(disk) * 2)
        sql, params = _disk_sql(disk, req, filters, aliases, q(disk.get("table", "data")))
        con = disk_data._connect(disk["path"], read_only=True)
        try:
            con.execute("BEGIN TRANSACTION")
            totals = con.execute(f"SELECT COUNT(*), COALESCE(SUM({q(aliases[0])}), 0) FROM ({sql}) summary", params).fetchone()
            data = con.execute(f"SELECT * FROM ({sql}) summary ORDER BY {order} LIMIT ? OFFSET ?", [*params, req.page_size, req.page * req.page_size]).fetchall()
            con.execute("COMMIT")
        finally:
            con.close()
        scope, sampled = "loaded", bool(ds.get("capped"))
    else:
        out, input_rows = _frame_summary(ds, req, filters, aliases)
        totals = (len(out), input_rows)
        data = out.iloc[req.page * req.page_size:(req.page + 1) * req.page_size].itertuples(index=False, name=None)
        scope, sampled = "loaded", bool(ds.get("capped"))
    return {"columns": result_columns, "rows": [[_clean(value) for value in row] for row in data],
            "total_groups": int(totals[0]), "input_rows": int(totals[1]), "page": req.page,
            "page_size": req.page_size, "scope": scope, "sampled": sampled}


@disk_data._bounded_materialization
def _stage_live(live, sql, params, columns):
    """Stream a large database summary into a new local DuckDB table."""
    estimate = int(live.get("estimated_bytes") or disk_data._estimate_live_bytes(live))
    disk_data._budget(estimate, estimate)
    path = disk_data._new_path()
    writer = disk_data._connect(path)
    try:
        engine = db.get_engine_for_resource(live["resource_id"])
        with engine.connect() as conn:
            transaction = conn.begin()
            try:
                with query_cancellation.postgres_connection(conn):
                    rows, used = disk_data._stage_live_rows(
                        writer, conn, text(sql), {**live, "params": {**live.get("params", {}), **params}},
                        columns, {}, "data", 0, estimate)
            finally:
                transaction.rollback()
        frame = writer.execute(f'SELECT * FROM "data" LIMIT {queries.ROW_CAP}').df()
        writer.close()
        return frame, {"path": path, "table": "data", "columns": list(columns), "rows": rows,
                       "estimated_bytes": used, "scan_bytes": os.path.getsize(path),
                       "large_warning": used >= disk_data.LARGE_OPERATION_BYTES}
    except Exception:
        try:
            writer.close()
        except Exception:
            pass
        disk_data.remove({"path": path})
        raise


@disk_data._bounded_materialization
def _stage_disk(disk, sql, params):
    """Write a large summary of a local DuckDB dataset into a new DuckDB table."""
    scan_bytes = _disk_scan_bytes(disk)
    disk_data._budget(scan_bytes, scan_bytes)
    path = disk_data._new_path()
    writer, reader = disk_data._connect(path), disk_data._connect(path)
    try:
        reader.execute(f"ATTACH {disk_data._lit(disk['path'])} AS {live_query._q('input')} (READ_ONLY)")
        with query_cancellation.duckdb_connection(writer), query_cancellation.duckdb_connection(reader):
            rows, materialized = disk_data._stream_duck_query(reader, writer, sql, "data", scan_bytes, params)
        frame = reader.execute(f'SELECT * FROM "data" LIMIT {queries.ROW_CAP}').df()
        return frame, {"path": path, "table": "data", "columns": list(frame.columns), "rows": rows,
                       "estimated_bytes": scan_bytes + materialized, "scan_bytes": os.path.getsize(path),
                       "large_warning": scan_bytes + materialized >= disk_data.LARGE_OPERATION_BYTES}
    except Exception:
        for con in (reader, writer):
            try:
                con.close()
            except Exception:
                pass
        disk_data.remove({"path": path})
        raise
    finally:
        for con in (reader, writer):
            try:
                con.close()
            except Exception:
                pass


def label(source: str, spec: dict) -> str:
    return f"{source} · Group summary ({', '.join(spec['group_by'])})"


@execution.workload("bulk")
def materialize(dataset_id: str, request: dict | MaterializeRequest) -> dict:
    """Compute every group of a summary for a new dataset tab.

    Results of up to ``queries.ROW_CAP`` groups are returned in memory; larger
    results are staged to a new local DuckDB file (``disk_source``) under the
    same size budgets as joins and calculated fields.
    """
    req = request if isinstance(request, MaterializeRequest) else MaterializeRequest.model_validate(request)
    ds = datasets.get(dataset_id)
    filters, aliases, result_columns, order = _prepare(ds, req)
    q = live_query._q
    live = ds.get("live_source")
    disk = ds.get("disk_source")
    staged = None
    data_jobs.report("Summarizing groups")
    if live:
        disk_data.guard_live_query(live, [], None)
        with db.get_engine_for_resource(live["resource_id"]).begin() as con:
            _begin_live(con)
            sql, params = _live_sql(con, live, req, filters, aliases)
            ordered = f"SELECT * FROM ({sql}) summary ORDER BY {order}"
            totals = live_query._query(con, live, f"SELECT COUNT(*), COALESCE(SUM({q(aliases[0])}), 0) FROM ({sql}) summary", params).one()
            if int(totals[0]) <= queries.ROW_CAP:
                rows = live_query._query(con, live, ordered, params).fetchall()
                frame = pd.DataFrame([list(row) for row in rows], columns=result_columns)
        if int(totals[0]) > queries.ROW_CAP:
            data_jobs.report("Staging summary groups locally", rows=int(totals[0]))
            frame, staged = _stage_live(live, ordered, params, result_columns)
        scope, sampled = "database", False
    elif disk:
        disk_data._budget(_disk_scan_bytes(disk) * 2)
        sql, params = _disk_sql(disk, req, filters, aliases, q(disk.get("table", "data")))
        con = disk_data._connect(disk["path"], read_only=True)
        try:
            con.execute("BEGIN TRANSACTION")
            totals = con.execute(f"SELECT COUNT(*), COALESCE(SUM({q(aliases[0])}), 0) FROM ({sql}) summary", params).fetchone()
            if int(totals[0]) <= queries.ROW_CAP:
                frame = con.execute(f"SELECT * FROM ({sql}) summary ORDER BY {order}", params).df()
            con.execute("COMMIT")
        finally:
            con.close()
        if int(totals[0]) > queries.ROW_CAP:
            data_jobs.report("Staging summary groups locally", rows=int(totals[0]))
            staged_sql, _ = _disk_sql(disk, req, filters, aliases,
                                      f"{q('input')}.{q(disk.get('table', 'data'))}")
            frame, staged = _stage_disk(disk, f"SELECT * FROM ({staged_sql}) summary ORDER BY {order}", params)
        scope, sampled = "loaded", bool(ds.get("capped"))
    else:
        frame, input_rows = _frame_summary(ds, req, filters, aliases)
        totals = (len(frame), input_rows)
        scope, sampled = "loaded", bool(ds.get("capped"))
    spec = {"group_by": list(req.group_by), "measure": req.measure}
    return {"df": frame, "disk_source": staged, "capped": sampled,
            "label": label(ds["source"], spec), "spec": spec, "filters": filters,
            "summary": {"total_groups": int(totals[0]), "input_rows": int(totals[1]),
                        "scope": scope, "sampled": sampled, "staged": staged is not None}}
