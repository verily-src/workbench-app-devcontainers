import re

import numpy as np
import pandas as pd

import datasets
from source_models import DerivedSpec, source_dict

NAME_RE = re.compile(r"^[A-Za-z0-9 _.\-]{1,60}$")
OPERATORS = {"+": np.add, "-": np.subtract, "*": np.multiply, "/": np.divide}

def _valid_name(name: str) -> str:
    name = (name or "").strip()
    if not NAME_RE.match(name):
        raise ValueError(
            "Column name must be 1–60 chars: letters, digits, space, _.-")
    return name

def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        raise ValueError(f"Unknown column: {col}")
    return pd.to_numeric(df[col], errors="coerce")

def _bin(df: pd.DataFrame, spec: dict) -> pd.Series:
    col = spec.get("column")
    breaks = spec.get("breaks") or []
    if len(breaks) < 2:
        raise ValueError("Binning needs at least two break points.")
    breaks = [float(b) for b in breaks]
    if breaks != sorted(breaks):
        raise ValueError("Break points must be ascending.")
    labels = spec.get("labels")
    if labels and len(labels) != len(breaks) - 1:
        raise ValueError(
            f"Expected {len(breaks) - 1} labels for {len(breaks)} breaks.")
    cut = pd.cut(_num(df, col), bins=breaks, labels=labels or None,
                 include_lowest=True)
    return cut.astype(str).where(cut.notna(), None)

def _formula(df: pd.DataFrame, spec: dict) -> pd.Series:
    op = spec.get("operator")
    if op not in OPERATORS:
        raise ValueError(f"Operator must be one of {list(OPERATORS)}")
    left = _num(df, spec.get("left"))
    right_raw = spec.get("right")
    try:
        right = float(right_raw)
    except (TypeError, ValueError):
        right = _num(df, right_raw)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = OPERATORS[op](left, right)
    return pd.Series(out, index=df.index).replace([np.inf, -np.inf], np.nan)

def _map(df: pd.DataFrame, spec: dict) -> pd.Series:
    col = spec.get("column")
    if col not in df.columns:
        raise ValueError(f"Unknown column: {col}")
    mapping = spec.get("mapping") or {}
    if not mapping:
        raise ValueError("Provide at least one value mapping.")
    default = spec.get("default")
    src = df[col].astype(str)
    mapped = src.map({str(k): v for k, v in mapping.items()})

    fill = default if default not in (None, "") else None
    return mapped.where(mapped.notna(), fill if fill is not None else src)


def _group_count(df: pd.DataFrame, spec: dict) -> pd.Series:
    columns = spec.get("group_by") or [spec.get("column")]
    for column in columns:
        if column not in df.columns: raise ValueError(f"Unknown column: {column}")
    return df.groupby(columns, dropna=True)[columns[0]].transform("size").astype("float64")


def _group_measure(df: pd.DataFrame, spec: dict) -> pd.Series:
    columns, measure = spec.get("group_by") or [spec.get("column")], spec.get("measure")
    if any(column not in df.columns for column in columns) or measure not in df.columns:
        raise ValueError("Unknown grouping or measure column.")
    values = pd.to_numeric(df[measure], errors="coerce").replace([np.inf, -np.inf], np.nan)
    grouped = values.groupby([df[column] for column in columns], dropna=True)
    if spec["op"] == "group_sum": return grouped.transform("sum", min_count=1)
    return grouped.transform({"group_mean": "mean", "group_min": "min", "group_max": "max"}[spec["op"]])


def _expression(df: pd.DataFrame, spec: dict) -> pd.Series:
    import calculations
    return calculations.evaluate(calculations.parse(spec["expression"], df.columns), df)

_GROUP_OPS = {"group_count", "group_sum", "group_mean", "group_min", "group_max"}
_OPS = {"bin": _bin, "formula": _formula, "map": _map, "group_count": _group_count,
        "group_sum": _group_measure, "group_mean": _group_measure, "group_min": _group_measure,
        "group_max": _group_measure, "expression": _expression}


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def derive(dataset_id: str, spec: dict) -> dict:
    normalized = DerivedSpec.model_validate(spec).model_dump(exclude_none=True)
    name = _valid_name(normalized.get("name", ""))
    op = normalized.get("op")
    if op not in _OPS:
        raise ValueError(f"Unknown op: {op}")
    ds = datasets.get(dataset_id)
    df = ds["df"]
    if op in _GROUP_OPS | {"expression"} and name in df.columns:
        raise ValueError("Choose a new name for the calculated column.")
    if ds.get("disk_source"):
        import column_settings
        import disk_data

        preview, disk = disk_data.derive(ds["disk_source"], normalized)
        remaining_settings = [s for s in ds.get("column_settings", [])
                              if s.get("name") != name]
        if op in _GROUP_OPS | {"expression"}:
            remaining_settings.append({"name": name, "logical_type": "number", "filter_kind": "range"})
        source_ref = None
        if ds.get("source_ref"):
            source_ref = source_dict({"kind": "derived", "base": ds["source_ref"],
                                      "spec": normalized,
                                      "settings": remaining_settings})
        baseline = {**ds, "df": preview, "disk_source": disk,
                    "column_settings": remaining_settings}
        columns = column_settings.profiles(baseline)
        old_disk = ds["disk_source"]
        ds["df"] = preview
        ds["disk_source"] = disk
        ds["source_ref"] = source_ref
        ds["column_settings"] = remaining_settings
        ds.pop("settings_base_df", None)
        ds.pop("settings_base_live", None)
        ds.pop("settings_base_origin", None)
        disk_data.remove(old_disk)
        return {"dataset_id": dataset_id, "source": ds["source"], "name": name,
                "rows": len(preview), "columns": columns, "source_ref": source_ref,
                "query_scope": "loaded", "sampled": False,
                "estimated_bytes": disk.get("estimated_bytes"),
                "large_warning": disk.get("large_warning", False)}
    series = _OPS[op](df, normalized)
    live_source = ds.get("live_source")
    if not live_source and (ds.get("origin") or {}).get("kind") == "aurora":
        origin = ds["origin"]
        names = list(df.columns)
        live_source = {
            "resource_id": origin["resource_id"],
            "sql": f"SELECT {', '.join(_q(n) for n in names)} FROM "
                   f"{_q(origin.get('schema') or 'public')}.{_q(origin['table'])}",
            "columns": {n: n for n in names},
            "params": {},
        }
    if live_source:
        import column_settings
        import disk_data
        import live_derive

        live = live_derive.build(live_source, df, {**normalized, "name": name})
        preview, _preview_capped = live_derive.preview(live)
        if name not in preview.columns:
            raise ValueError("The derived column could not be created in the database.")
        remaining_settings = [s for s in ds.get("column_settings", [])
                              if s.get("name") != name]
        if op in _GROUP_OPS | {"expression"}:
            remaining_settings.append({"name": name, "logical_type": "number", "filter_kind": "range"})
        baseline = {**ds, "df": preview, "live_source": live,
                    "column_settings": remaining_settings}
        columns = column_settings.profiles(baseline)
        source_ref = None
        if ds.get("source_ref"):
            source_ref = source_dict({"kind": "derived", "base": ds["source_ref"],
                                      "spec": normalized,
                                      "settings": remaining_settings})
            if disk_data._requires_compiler_trust(source_ref):
                live = disk_data._compiled_source_query(source_ref, live)
        ds["df"] = preview
        ds["live_source"] = live
        ds["origin"] = None
        ds["capped"] = False
        ds["source_ref"] = source_ref
        ds["column_settings"] = remaining_settings
        ds["settings_base_df"] = preview
        ds["settings_base_live"] = live
        ds["settings_base_origin"] = None
        return {"dataset_id": dataset_id, "source": ds["source"], "name": name,
                "rows": len(preview), "columns": columns, "source_ref": source_ref,
                "query_scope": "database", "sampled": False}
    result = datasets.set_column(dataset_id, name, series)
    if op in _GROUP_OPS | {"expression"}:
        import column_settings
        ds["column_settings"] = [*ds.get("column_settings", []),
                                 {"name": name, "logical_type": "number", "filter_kind": "range"}]
        result["columns"] = column_settings.profiles(ds)
    return result
