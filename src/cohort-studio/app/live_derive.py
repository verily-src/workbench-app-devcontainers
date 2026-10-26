import hashlib
import math
import uuid

import pandas as pd
import database as db
import disk_data
import queries
from sql_utils import statement as text


def _q(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _number(column: str) -> str:
    value = f"TRIM(({column})::text)"
    pattern = r"^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$"
    return (f"CASE WHEN {value} ~ '{pattern}' "
            f"THEN ({value})::double precision END")


def _bind(params: dict, prefix: str, suffix: str, value):
    name = f"d_{prefix}_{suffix}"
    params[name] = value
    return f":{name}"


def _default_bin_labels(breaks: list[float]) -> list[str]:
    cut = pd.cut(pd.Series([], dtype="float64"), bins=breaks,
                 include_lowest=True)
    return [str(interval) for interval in cut.cat.categories]


def _expression(frame: pd.DataFrame, live: dict, spec: dict,
                prefix: str) -> tuple[str, dict]:
    op = spec["op"]
    local = {}
    columns = live["columns"]

    def column(name):
        if name not in columns:
            raise ValueError(f"Unknown column: {name}")
        return f"src.{_q(columns[name])}"

    if op == "bin":
        name = spec.get("column")
        value = _number(column(name))
        breaks = [float(v) for v in spec.get("breaks") or []]
        labels = spec.get("labels") or _default_bin_labels(breaks)
        clauses = []
        for i, label in enumerate(labels):
            low_op = ">=" if i == 0 else ">"
            low = _bind(local, prefix, f"lo{i}", breaks[i])
            high = _bind(local, prefix, f"hi{i}", breaks[i + 1])
            out = _bind(local, prefix, f"label{i}", str(label))
            clauses.append(f"WHEN {value} {low_op} {low} AND {value} <= {high} THEN {out}")
        return "CASE " + " ".join(clauses) + " ELSE NULL::text END", local

    if op == "formula":
        left = _number(column(spec.get("left")))
        operator = spec.get("operator")
        if operator not in {"+", "-", "*", "/"}:
            raise ValueError("Operator must be one of ['+', '-', '*', '/']")
        right_raw = spec.get("right")
        try:
            numeric = float(right_raw)
        except (TypeError, ValueError):
            right = _number(column(right_raw))
        else:
            if not math.isfinite(numeric):
                raise ValueError("Formula constants must be finite numbers.")
            right = _bind(local, prefix, "right", numeric)
        if operator == "/":
            right = f"NULLIF(({right}), 0.0)"
        return f"({left}) {operator} ({right})", local

    if op == "map":
        source = column(spec.get("column"))
        source_text = f"CAST({source} AS text)"
        series = frame[spec["column"]]
        null_text = "nan" if pd.api.types.is_float_dtype(series.dtype) else "None"
        source_text = f"COALESCE({source_text}, {_bind(local, prefix, 'null', null_text)})"
        mapping = spec.get("mapping") or {}
        if not mapping:
            raise ValueError("Provide at least one value mapping.")
        clauses = []
        for i, (key, value) in enumerate(mapping.items()):
            k = _bind(local, prefix, f"key{i}", str(key))
            v = _bind(local, prefix, f"value{i}", str(value))
            clauses.append(f"WHEN {source_text} = {k} THEN {v}")
        default = spec.get("default")
        fallback = (_bind(local, prefix, "default", str(default))
                    if default not in (None, "") else source_text)
        return "CASE " + " ".join(clauses) + f" ELSE {fallback} END", local

    raise ValueError(f"Unknown op: {op}")


def build(live_source: dict, frame: pd.DataFrame, spec: dict) -> dict:
    prefix = uuid.uuid4().hex
    expression, new_params = _expression(frame, live_source, spec, prefix)
    columns = dict(live_source["columns"])
    name = spec["name"]
    digest = hashlib.sha1(f"{name}:{prefix}".encode()).hexdigest()[:12]
    alias = f"_studio_{digest}"
    old = columns.pop(name, None)
    physical = list(dict.fromkeys(columns.values()))
    if old and old not in physical:
        physical.append(old)
    projection = [f"src.{_q(col)} AS {_q(col)}" for col in physical if col != old]
    projection.append(f"{expression} AS {_q(alias)}")
    sql = (f"SELECT {', '.join(projection)} FROM ({live_source['sql']}) AS src")
    params = dict(live_source.get("params", {}))
    params.update(new_params)
    columns[name] = alias
    values = {**live_source, "sql": sql, "columns": columns, "params": params}
    if isinstance(live_source, disk_data.CompiledSourceQuery):
        return live_source.with_metadata(sql=sql, columns=columns, params=params)
    return values


def preview(live_source: dict) -> tuple[pd.DataFrame, bool]:
    cap = queries.ROW_CAP
    sql = (f"SELECT * FROM ({live_source['sql']}) AS derived_preview "
           "LIMIT :_studio_preview_limit")
    params = {**live_source.get("params", {}), "_studio_preview_limit": cap + 1}
    with db.get_engine_for_resource(live_source["resource_id"]).begin() as conn:
        if conn.dialect.name == "postgresql":
            conn.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            conn.exec_driver_sql("SET LOCAL search_path = pg_catalog")
            conn.exec_driver_sql("SET LOCAL statement_timeout = 15000")
        frame = pd.read_sql_query(text(sql), conn, params=params)
    frame = frame.rename(columns={physical: logical
                                  for logical, physical in live_source["columns"].items()})
    capped = len(frame) > cap
    if capped:
        frame = frame.head(cap)
    return frame, capped
