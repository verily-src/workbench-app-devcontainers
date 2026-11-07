"""Bounded grouped statistics and two-group comparisons for Studio Agent.

Both run on the dataset's own query path: live Aurora SQL, the disk DuckDB
copy, or in-memory rows. Results state that scope, as the dashboard does.
"""
import math
import os
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

import database as db
import datasets
import disk_data
import execution
import filter_rules
import live_query
from group_summary import _clean

OPS = ("count", "mean", "median", "min", "max", "distinct")
_NUMERIC_OPS = {"mean", "median", "min", "max"}
MAX_GROUPS = 50
_ROWS = "__rows"


class Metric(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    op: Literal["count", "mean", "median", "min", "max", "distinct"]
    column: str | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def needs_column(self):
        if self.op != "count" and self.column is None:
            raise ValueError(f"{self.op} needs a column.")
        return self

    @property
    def label(self) -> str:
        return f"{self.op}({self.column})" if self.column else "rows"


class AggregateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    group_by: list[str] = Field(default_factory=list, max_length=3)
    metrics: list[Metric] = Field(min_length=1, max_length=8)
    limit: int = Field(default=25, ge=1, le=MAX_GROUPS)

    @model_validator(mode="after")
    def distinct_names(self):
        if len(set(self.group_by)) != len(self.group_by):
            raise ValueError("Choose distinct group_by columns.")
        labels = [metric.label for metric in self.metrics]
        if len(set(labels)) != len(labels):
            raise ValueError("Each metric must be distinct.")
        return self


def scope(ds: dict) -> dict:
    """The app's scope fields plus a plain statement of what was counted."""
    sampled = bool(ds.get("capped"))
    if ds.get("live_source") is not None:
        return {"scope": "database", "sampled": False,
                "scope_note": "Full database source, queried live."}
    if ds.get("disk_source") is not None:
        note = ("Loaded rows only: the import was capped, so the source may hold more rows."
                if sampled else "Complete imported source, queried on disk.")
    else:
        note = ("Loaded rows only: a capped subset of the source." if sampled
                else "All loaded rows of the source.")
    return {"scope": "loaded", "sampled": sampled, "scope_note": note}


def _check_columns(ds: dict, names) -> None:
    columns = set(ds["df"].columns)
    unknown = [name for name in names if name not in columns]
    if unknown:
        raise ValueError(f"Unknown column: {unknown[0]}. Use the dashboard column metadata.")


def _metric_sql(metric: Metric, raw, number) -> str:
    if metric.op == "count":
        return f"COUNT({raw})" if metric.column else "COUNT(*)"
    if metric.op == "distinct":
        return f"COUNT(DISTINCT {raw})"
    if metric.op == "median":
        return number["median"]
    return {"mean": "AVG", "min": "MIN", "max": "MAX"}[metric.op] + f"({number['value']})"


def _grouped_sql(groups, metrics, relation, where):
    q = live_query._q
    select = [f"{expr} AS {q(f'g{i}')}" for i, expr in enumerate(groups)]
    select.append(f"COUNT(*) AS {q(_ROWS)}")
    select += [f"{expr} AS {q(f'm{i}')}" for i, expr in enumerate(metrics)]
    group = f" GROUP BY {', '.join(groups)}" if groups else ""
    inner = f"SELECT {', '.join(select)} FROM {relation} AS src WHERE {where}{group}"
    order = ", ".join([f"{q(_ROWS)} DESC"] + [f"{q(f'g{i}')} ASC NULLS LAST"
                                              for i in range(len(groups))])
    return inner, order


def _live_aggregate(ds, req, metrics_in, filters):
    live = ds["live_source"]
    q = live_query._q
    disk_data.guard_live_query(live, [], None)
    numeric_names = [f["column"] for f in filter_rules.leaves(filters)
                     if f["kind"] in ("range", "categorical")] + [
        m.column for m in metrics_in if m.op in _NUMERIC_OPS]
    with db.get_engine_for_resource(live["resource_id"]).begin() as con:
        con.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        con.exec_driver_sql("SET LOCAL search_path = pg_catalog")
        con.exec_driver_sql("SET LOCAL TimeZone = 'UTC'")
        con.exec_driver_sql(f"SET LOCAL statement_timeout = {live_query.TIMEOUT_MS}")
        numeric = live_query._numeric_columns(con, live, numeric_names)
        where, params = live_query._where(filters, live["columns"], numeric)
        groups = [f"src.{q(live['columns'][name])}" for name in req.group_by]
        metrics = []
        for metric in metrics_in:
            raw = f"src.{q(live['columns'][metric.column])}" if metric.column else None
            number = None
            if metric.op in _NUMERIC_OPS:
                value = live_query._numeric(raw, numeric.get(metric.column))
                number = {"value": value, "median":
                          f"PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY {value})"}
            metrics.append(_metric_sql(metric, raw, number))
        inner, order = _grouped_sql(groups, metrics, f"({live['sql']})", where)
        totals = live_query._query(
            con, live, f"SELECT COUNT(*), COALESCE(SUM({q(_ROWS)}), 0) FROM ({inner}) g",
            params).one()
        data = live_query._query(
            con, live, f"SELECT * FROM ({inner}) g ORDER BY {order} LIMIT :agent_limit",
            {**params, "agent_limit": req.limit}).fetchall()
    return totals, data


def _disk_aggregate(ds, req, metrics_in, filters):
    disk = ds["disk_source"]
    q = live_query._q
    disk_data._budget(int(disk.get("scan_bytes") or os.path.getsize(disk["path"])) * 2)
    where, params = disk_data._where(filters, disk_data.column_types(disk))
    groups = [f"src.{q(name)}" for name in req.group_by]
    metrics = []
    for metric in metrics_in:
        raw = f"src.{q(metric.column)}" if metric.column else None
        number = None
        if metric.op in _NUMERIC_OPS:
            cast = f"TRY_CAST({raw} AS DOUBLE)"
            value = f"CASE WHEN ISFINITE({cast}) THEN {cast} END"
            number = {"value": value, "median": f"MEDIAN({value})"}
        metrics.append(_metric_sql(metric, raw, number))
    inner, order = _grouped_sql(groups, metrics, q(disk.get("table", "data")), where)
    con = disk_data._connect(disk["path"], read_only=True)
    try:
        con.execute("BEGIN TRANSACTION")
        totals = con.execute(
            f"SELECT COUNT(*), COALESCE(SUM({q(_ROWS)}), 0) FROM ({inner}) g", params).fetchone()
        data = con.execute(f"SELECT * FROM ({inner}) g ORDER BY {order} LIMIT ?",
                           [*params, req.limit]).fetchall()
        con.execute("COMMIT")
    finally:
        con.close()
    return totals, data


def _memory_aggregate(ds, req, metrics_in, filters):
    frame = datasets.apply_filters(ds["df"], filters)
    def stats(part: pd.DataFrame) -> list:
        values = [len(part)]
        for metric in metrics_in:
            series = part[metric.column] if metric.column else None
            if metric.op == "count":
                values.append(len(part) if series is None else int(series.notna().sum()))
            elif metric.op == "distinct":
                values.append(int(series.nunique(dropna=True)))
            else:
                number = pd.to_numeric(series, errors="coerce").replace(
                    [math.inf, -math.inf], math.nan)
                values.append(getattr(number, metric.op)())
        return values
    if not req.group_by:
        return (1, len(frame)), [stats(frame)]
    rows = []
    for key, part in frame.groupby(req.group_by, dropna=False, observed=True, sort=True):
        key = key if isinstance(key, tuple) else (key,)
        rows.append([*key, *stats(part)])
    width = len(req.group_by)
    rows.sort(key=lambda row: -row[width])
    return (len(rows), len(frame)), rows[:req.limit]


def _round(value):
    value = _clean(value)
    if isinstance(value, float):
        return round(value, 6)
    if hasattr(value, "is_finite"):  # Decimal from PostgreSQL
        return round(float(value), 6) if value.is_finite() else None
    return value


@execution.workload("interactive")
def aggregate(dataset_id: str, request: dict | AggregateRequest, filters: list[dict]) -> dict:
    req = request if isinstance(request, AggregateRequest) else AggregateRequest.model_validate(request)
    ds = datasets.get(dataset_id)
    _check_columns(ds, [*req.group_by, *(m.column for m in req.metrics if m.column)])
    # Row counts are always returned; a column-less count adds nothing more.
    metrics = [m for m in req.metrics if m.column]
    run = (_live_aggregate if ds.get("live_source") is not None else
           _disk_aggregate if ds.get("disk_source") is not None else _memory_aggregate)
    totals, data = run(ds, req, metrics, filters)
    total_groups = int(totals[0])
    return {"columns": [*req.group_by, "rows", *(m.label for m in metrics)],
            "rows": [[_round(value) for value in row] for row in data],
            "total_groups": total_groups, "rows_considered": int(totals[1]),
            "truncated": total_groups > len(data), "filters": filters,
            "numeric_note": "mean/median/min/max ignore non-numeric and missing values.",
            **scope(ds)}


def _profiles(ds: dict, columns: list[str]) -> list[dict]:
    import compare
    profiles = {p["name"]: p for p in compare._profiles(ds)}
    selected = []
    for name in columns:
        profile = profiles.get(name)
        if profile is None:
            raise ValueError(f"Unknown column: {name}. Use the dashboard column metadata.")
        if profile.get("filter_kind") not in {"range", "categorical"}:
            raise ValueError(f"Column {name} is not numeric or categorical and cannot be compared.")
        selected.append(profile)
    return selected


@execution.workload("interactive")
def compare_groups(dataset_id: str, filters_a: list[dict], filters_b: list[dict],
                   columns: list[str]) -> dict:
    import compare
    if not 1 <= len(columns) <= 12 or len(set(columns)) != len(columns):
        raise ValueError("Choose one to twelve distinct columns.")
    ds = datasets.get(dataset_id)
    profiles = _profiles(ds, columns)
    if ds.get("live_source") is not None:
        import live_compare
        disk_data.guard_live_query(ds["live_source"], [], None)
        result = live_compare.compare(ds["live_source"], profiles, filters_a, filters_b)
    elif ds.get("disk_source") is not None:
        result = disk_data.compare(ds["disk_source"], profiles, filters_a, filters_b)
    else:
        df = ds["df"]
        a, b = datasets.apply_filters(df, filters_a), datasets.apply_filters(df, filters_b)
        results = []
        for profile in profiles:
            name = profile["name"]
            test = (compare._numeric_test if profile["filter_kind"] == "range"
                    else compare._categorical_test)
            results.append({"column": name, "kind": profile["filter_kind"],
                            **test(a[name], b[name])})
        for item, q in zip(results, compare._benjamini_hochberg([r.get("p") for r in results])):
            item["q"] = q
        result = {"a_n": int(len(a)), "b_n": int(len(b)),
                  "n_overlap": int(len(a.index.intersection(b.index))), "results": results}
    order = {name: i for i, name in enumerate(columns)}
    result["results"] = sorted(result["results"], key=lambda r: order.get(r["column"], 99))
    result.pop("scope", None)
    return {**result, "filters_a": filters_a, "filters_b": filters_b,
            "counts_are": "rows (not distinct people unless rows are person-level)",
            **scope(ds)}
