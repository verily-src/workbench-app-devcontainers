import math
import os

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal

import database as db
import datasets
import disk_data
import execution
import live_query


class SummaryFilter(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    column: str = Field(min_length=1, max_length=512)
    kind: Literal["categorical", "range"]
    values: list[str] | None = Field(default=None, max_length=1000)
    min: float | None = None
    max: float | None = None


class SummaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    group_by: list[str] = Field(min_length=1, max_length=5)
    measure: str | None = None
    filters: list[SummaryFilter] = Field(default_factory=list, max_length=200)
    page: int = Field(default=0, ge=0, le=10000000)
    page_size: int = Field(default=50, ge=1, le=200)

    @model_validator(mode="after")
    def distinct_groups(self):
        if any(not item or len(item) > 512 for item in self.group_by) or len(set(self.group_by)) != len(self.group_by):
            raise ValueError("Choose distinct grouping columns.")
        return self


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


@execution.workload("interactive")
def summarize(dataset_id: str, request: dict | SummaryRequest) -> dict:
    req = request if isinstance(request, SummaryRequest) else SummaryRequest.model_validate(request)
    ds = datasets.get(dataset_id)
    columns = list(ds["df"].columns)
    if any(name not in columns for name in [*req.group_by, *([req.measure] if req.measure else [])]):
        raise ValueError("Unknown grouping or value column.")
    filters = [item.model_dump() for item in req.filters]
    if any(item["column"] not in columns for item in filters):
        raise ValueError("Unknown filter column.")
    aliases = _aliases(req.group_by, req.measure)
    q = live_query._q
    result_columns = req.group_by + aliases
    live = ds.get("live_source")
    disk = ds.get("disk_source")
    if live:
        disk_data.guard_live_query(live, [], None)
        with db.get_engine_for_resource(live["resource_id"]).begin() as con:
            con.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            con.exec_driver_sql("SET LOCAL search_path = pg_catalog")
            con.exec_driver_sql(f"SET LOCAL statement_timeout = {live_query.TIMEOUT_MS}")
            numeric = live_query._numeric_columns(con, live, [item["column"] for item in filters if item["kind"] == "range"] + ([req.measure] if req.measure else []))
            where, params = live_query._where(filters, live["columns"], numeric)
            groups = [f"src.{q(live['columns'][name])}" for name in req.group_by]
            selection = [f"{col} AS {q(name)}" for col, name in zip(groups, req.group_by)]
            number = live_query._numeric(f"src.{q(live['columns'][req.measure])}", numeric.get(req.measure)) if req.measure else None
            sql = _sql_summary(selection, groups, number, aliases[0], aliases, f"({live['sql']})", where)
            totals = live_query._query(con, live, f"SELECT COUNT(*), COALESCE(SUM({q(aliases[0])}), 0) FROM ({sql}) summary", params).one()
            order = ", ".join(f"{q(name)} ASC NULLS LAST" for name in req.group_by)
            data = live_query._query(con, live, f"SELECT * FROM ({sql}) summary ORDER BY {order} LIMIT :summary_limit OFFSET :summary_offset", {**params, "summary_limit": req.page_size, "summary_offset": req.page * req.page_size}).fetchall()
        scope, sampled = "database", False
    elif disk:
        disk_data._budget(int(disk.get("scan_bytes") or os.path.getsize(disk["path"])) * 2)
        where, params = disk_data._where(filters, disk["columns"])
        groups = [f"src.{q(name)}" for name in req.group_by]
        selection = [f"{col} AS {q(name)}" for col, name in zip(groups, req.group_by)]
        numeric = f"TRY_CAST(src.{q(req.measure)} AS DOUBLE)" if req.measure else None
        number = f"CASE WHEN ISFINITE({numeric}) THEN {numeric} END" if numeric else None
        sql = _sql_summary(selection, groups, number, aliases[0], aliases, q(disk.get("table", "data")), where)
        con = disk_data._connect(disk["path"], read_only=True)
        try:
            con.execute("BEGIN TRANSACTION")
            totals = con.execute(f"SELECT COUNT(*), COALESCE(SUM({q(aliases[0])}), 0) FROM ({sql}) summary", params).fetchone()
            order = ", ".join(f"{q(name)} ASC NULLS LAST" for name in req.group_by)
            data = con.execute(f"SELECT * FROM ({sql}) summary ORDER BY {order} LIMIT ? OFFSET ?", [*params, req.page_size, req.page * req.page_size]).fetchall()
            con.execute("COMMIT")
        finally:
            con.close()
        scope, sampled = "loaded", bool(ds.get("capped"))
    else:
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
        out = out.reset_index().sort_values(req.group_by, na_position="last", kind="stable")
        totals = (len(out), len(frame))
        data = out.iloc[req.page * req.page_size:(req.page + 1) * req.page_size].itertuples(index=False, name=None)
        scope, sampled = "loaded", bool(ds.get("capped"))
    return {"columns": result_columns, "rows": [[_clean(value) for value in row] for row in data],
            "total_groups": int(totals[0]), "input_rows": int(totals[1]), "page": req.page,
            "page_size": req.page_size, "scope": scope, "sampled": sampled}
