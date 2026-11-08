import logging
import math
import sqlite3
import execution
import count_contract
import threading
import time
import uuid

import numpy as np
import pandas as pd

import category_text
import chart_measures
import filter_rules
import queries

logger = logging.getLogger(__name__)

MAX_DATASETS = 8
DATASET_TTL = 4 * 3600
CATEGORICAL_VALUES_LIMIT = 50
BAR_TOP_N = 12
HIST_BINS = 24
SCATTER_SAMPLE = 2000
HEATMAP_LIMIT = 400

_store: dict[str, dict] = {}
_lock = threading.Lock()

class DatasetNotFound(KeyError):
    pass

def _evict():
    now = time.monotonic()
    expired = [k for k, v in _store.items()
               if now - v["created"] > DATASET_TTL]
    for k in expired:
        _drop(k)
    normal = [k for k, v in _store.items() if not v.get("temporary")]
    while len(normal) > MAX_DATASETS:
        oldest = min(normal, key=lambda k: _store[k]["created"])
        _drop(oldest)
        normal.remove(oldest)


def _drop(dataset_id: str):
    dataset = _store.pop(dataset_id, None)
    if dataset and dataset.get("disk_source"):
        import disk_data
        disk_data.remove(dataset["disk_source"])

def open_dataset(df: pd.DataFrame, source: str, origin: dict | None = None,
                 capped: bool | None = None,
                 live_source: dict | None = None,
                 disk_source: dict | None = None,
                 temporary: bool = False, profile_source: bool = True) -> dict:
    """Register a dataset. `profile_source=False` skips the full-source
    database/disk profiling (sample-based profiles only), for inputs whose
    profiles are never shown, such as the tables behind a reopened join."""

    if live_source is not None:
        capped = False
    elif disk_source is not None and capped is None:
        # Disk sources hold every row, unless built from capped inputs
        # (e.g. a cross-source join with a BigQuery view's loaded rows).
        capped = False
    if capped is None:
        capped = len(df) >= queries.ROW_CAP
    try:
        columns = profile_columns(df)
        if not profile_source:
            pass
        elif live_source is not None:
            import live_query
            columns = live_query.profile_columns(live_source, columns)
        elif disk_source is not None:
            import disk_data
            columns = disk_data.profile_columns(disk_source, columns)
    except Exception:
        if disk_source is not None:
            import disk_data
            disk_data.remove(disk_source)
        raise
    with _lock:
        if not temporary:
            _evict()
        dataset_id = uuid.uuid4().hex[:12]
        _store[dataset_id] = {"df": df, "source": source, "origin": origin,
                              "capped": capped, "live_source": live_source,
                              "disk_source": disk_source,
                              "created": time.monotonic(), "temporary": temporary}
    estimate_source = disk_source or live_source or {}
    return {"dataset_id": dataset_id, "source": source,
            "rows": len(df), "columns": columns,
            "query_scope": "database" if live_source else "loaded",
            "database": live_source is not None,
            "sampled": bool(capped),
            "estimated_bytes": estimate_source.get("estimated_bytes"),
            "large_warning": bool(estimate_source.get("large_warning")),
            "source_info": estimate_source.get("source_info")}

def get(dataset_id: str) -> dict:
    try:
        return _store[dataset_id]
    except KeyError:
        raise DatasetNotFound(dataset_id)

def close_dataset(dataset_id: str):
    with _lock:
        _drop(dataset_id)


def clear():
    with _lock:
        for dataset_id in list(_store):
            _drop(dataset_id)

def set_column(dataset_id: str, name: str, series) -> dict:

    with _lock:
        ds = get(dataset_id)
        if ds.get("disk_source"):
            raise ValueError("Derived columns are not available for disk-backed sources.")
        df = ds["df"].copy()
        df[name] = series
        ds["df"] = df
        ds["origin"] = None
        ds["live_source"] = None
        ds.pop("source_ref", None)
        for key in ("settings_base_df", "settings_base_live", "settings_base_origin"):
            ds.pop(key, None)
    return {"name": name, "rows": len(df), "columns": profile_columns(df)}

def profile_columns(df: pd.DataFrame) -> list[dict]:
    kinds = queries.infer_filter_kinds(df)
    profile = []
    for col in df.columns:
        kind = kinds.get(col, "none")
        entry = {"name": col, "filter_kind": kind,
                 "dtype": str(df[col].dtype)}
        if kind == "categorical":
            entry["values"], _more = chart_measures._top(
                category_text.frame_text(df[col]).dropna(), CATEGORICAL_VALUES_LIMIT)
        elif kind == "range":
            entry["min"] = float(df[col].min())
            entry["max"] = float(df[col].max())
        elif kind == "date":
            values = datetimes(df[col]).dropna()
            if len(values):
                entry["min_date"] = values.min().date().isoformat()
                entry["max_date"] = values.max().date().isoformat()
        profile.append(entry)
    return profile

def apply_filters(df: pd.DataFrame, filters: list[dict]) -> pd.DataFrame:
    """Rows matching every filter; a criteria group keeps rows matching any of its groups."""
    plain = [f for f in filters if f.get("kind") != "any"]
    df = _apply_flat(df, plain)
    for item in filters:
        if item.get("kind") != "any":
            continue
        # Track rows by position (a RangeIndex copy), so no marker column can
        # collide with the data and duplicate index labels don't matter.
        positional = df.reset_index(drop=True)
        keep = np.zeros(len(df), dtype=bool)
        for group in filter_rules.validate_groups(item):
            keep[_apply_flat(positional, group).index.to_numpy()] = True
        df = df[keep]
    return df


def datetimes(series: pd.Series) -> pd.Series:
    """Naive UTC timestamps; text is read as ISO 8601 (no offset means UTC)."""
    if pd.api.types.is_datetime64_any_dtype(series.dtype):
        values = series
    else:
        values = pd.to_datetime(series, errors="coerce", format="ISO8601", utc=True)
    if getattr(values.dt, "tz", None) is not None:
        values = values.dt.tz_convert("UTC").dt.tz_localize(None)
    return values


def _range_mask(series: pd.Series, name: str, item: dict) -> np.ndarray:
    low, high = filter_rules.range_bounds(item)
    category_text.check_range_dtype(name, series)
    if pd.api.types.is_integer_dtype(series.dtype):
        dtype = series.dtype.pyarrow_dtype.to_pandas_dtype() if isinstance(series.dtype, pd.ArrowDtype) else getattr(series.dtype, "numpy_dtype", series.dtype)
        domain = np.iinfo(dtype)
        keep = series.notna()
        if low is not None:
            threshold = math.ceil(low)
            keep &= series.ge(threshold) if domain.min <= threshold <= domain.max else threshold < domain.min
        if high is not None:
            threshold = math.floor(high)
            keep &= series.le(threshold) if domain.min <= threshold <= domain.max else threshold > domain.max
        return keep.to_numpy(dtype=bool, na_value=False)
    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype="float64", na_value=np.nan)
    keep = np.isfinite(values)
    if low is not None:
        keep &= values >= low
    if high is not None:
        keep &= values <= high
    return keep


def _apply_flat(df: pd.DataFrame, filters: list[dict]) -> pd.DataFrame:
    for f in filters:
        col = f.get("column")
        if col not in df.columns:
            raise ValueError(f"Unknown filter column: {col!r}.")
        if f.get("kind") == "categorical" and f.get("values"):
            if pd.api.types.is_float_dtype(df[col].dtype):
                values = pd.to_numeric(pd.Series(f["values"]), errors="coerce").dropna()
                values = values.astype(df[col].dtype)
                df = df[df[col].notna() & df[col].isin(values)]
                continue
            values = category_text.filter_values(f["values"], category_text.series_value_kind(df[col]))
            df = df[category_text.frame_text(df[col]).isin(values).to_numpy(dtype=bool)]
        elif f.get("kind") == "range" and filter_rules.is_active(f):
            df = df[_range_mask(df[col], col, f)]
        elif f.get("kind") == "date" and filter_rules.is_active(f):
            start, end = filter_rules.date_bounds(f)
            values = datetimes(df[col])
            keep = values.notna()
            if start:
                keep &= values >= pd.Timestamp(start)
            if end:
                keep &= values < pd.Timestamp(end)
            df = df[keep]
    return df

def _bar_aggregate(full: pd.DataFrame, filt: pd.DataFrame, x: str) -> dict:
    values = category_text.frame_text(full[x]).dropna()
    counts = values.value_counts()
    cats, _more = chart_measures._top(values, BAR_TOP_N)
    try:
        cats.sort(key=float)
    except ValueError:
        pass
    selected = category_text.frame_text(filt[x]).dropna().value_counts()
    rows = [{"category": c, "all": int(counts[c]),
             "selected": int(selected.get(c, 0))} for c in cats]
    if len(counts) > BAR_TOP_N:
        rest = counts.index.difference(cats)
        rows.append({"category": "Other", "all": int(counts[rest].sum()),
                     "selected": int(selected.reindex(rest).fillna(0).sum())})
    return {"kind": "bar", "x": x, "data": rows}

def _histogram_aggregate(full: pd.DataFrame, filt: pd.DataFrame,
                         x: str) -> dict:

    values = pd.to_numeric(full[x], errors="coerce").dropna()
    if values.empty:
        return {"kind": "histogram", "x": x, "data": []}
    counts, edges = np.histogram(values, bins=HIST_BINS)
    filt_values = pd.to_numeric(filt[x], errors="coerce").dropna()
    filt_counts, _ = np.histogram(filt_values, bins=edges)
    data = [{"lo": float(edges[i]), "hi": float(edges[i + 1]),
             "all": int(counts[i]), "selected": int(filt_counts[i])}
            for i in range(len(counts))]
    return {"kind": "histogram", "x": x, "data": data}

def _scatter_aggregate(filt: pd.DataFrame, x: str, y: str) -> dict:

    sub = pd.DataFrame({"a": pd.to_numeric(filt[x], errors="coerce"),
                        "b": pd.to_numeric(filt[y], errors="coerce")}).dropna()
    sampled = len(sub) > SCATTER_SAMPLE
    if sampled:
        sub = sub.sample(SCATTER_SAMPLE, random_state=7)
    return {"kind": "scatter", "x": x, "y": y,
            "data": sub.values.tolist(), "sampled": sampled}

def _heatmap_aggregate(filt: pd.DataFrame, x: str, y: str) -> dict:
    cells = pd.DataFrame({"a": category_text.frame_text(filt[x]),
                          "b": category_text.frame_text(filt[y])}).dropna()
    counts = (cells.groupby(["a", "b"]).size().reset_index(name="n")
              .sort_values(["n", "a", "b"], ascending=[False, True, True], kind="stable"))
    sampled = len(counts) > HEATMAP_LIMIT
    return {"kind": "heatmap", "x": x, "y": y, "sampled": sampled,
            "data": [[a, b, int(n)] for a, b, n in
                     counts.head(HEATMAP_LIMIT).itertuples(index=False)]}

def chart_aggregate(full: pd.DataFrame, filt: pd.DataFrame,
                    chart: dict) -> dict:
    kind, x, y = chart.get("kind"), chart.get("x"), chart.get("y")
    if x not in full.columns or (y and y not in full.columns):
        return {"kind": kind, "x": x, "data": []}
    if chart_measures.is_measured(chart):
        return chart_measures.frame_bar(full, filt, chart)
    if kind == "box":
        return chart_measures.frame_box(full, filt, chart)
    if kind == "bar":
        return _bar_aggregate(full, filt, x)
    if kind == "histogram":
        return _histogram_aggregate(full, filt, x)
    if kind == "scatter" and y:
        return _scatter_aggregate(filt, x, y)
    if kind == "map" and y:
        longitude = pd.to_numeric(filt[x], errors="coerce")
        latitude = pd.to_numeric(filt[y], errors="coerce")
        valid = longitude.between(-180, 180) & latitude.between(-90, 90)
        points = pd.DataFrame({"longitude": longitude[valid], "latitude": latitude[valid]})
        sampled = len(points) > SCATTER_SAMPLE
        if sampled:
            points = points.sample(SCATTER_SAMPLE, random_state=7)
        return {"kind": "map", "x": x, "y": y, "data": points.values.tolist(), "sampled": sampled}
    if kind == "heatmap" and y:
        return _heatmap_aggregate(filt, x, y)
    return {"kind": kind, "x": x, "data": []}

@execution.workload("interactive")
def query(dataset_id: str, filters: list[dict], chart_specs: list[dict],
          page: int = 0, page_size: int = 50,
          entity_column: str | None = None, refresh: bool = False, sort: dict | None = None) -> dict:
    result = _query(dataset_id, filters, chart_specs, page, page_size, entity_column, refresh, sort)
    result["count_contract"] = count_contract.describe(entity_column, result)
    import grain
    try:
        result["count_contract"]["declared_grain"] = grain.get(dataset_id)
    except (OSError, sqlite3.Error):
        result["count_contract"]["declared_grain"] = {"definition": None, "available": False}
    return result

def _query(dataset_id: str, filters: list[dict], chart_specs: list[dict],
          page: int = 0, page_size: int = 50,
          entity_column: str | None = None, refresh: bool = False, sort: dict | None = None) -> dict:
    ds = get(dataset_id)
    full = ds["df"]
    if sort is not None:
        if not isinstance(sort, dict) or set(sort) != {"column", "direction"} or sort["column"] not in full.columns or sort["direction"] not in {"asc", "desc"}:
            raise ValueError("Invalid sort column or direction.")

    if entity_column is not None and entity_column not in full.columns:
        raise ValueError(f"Unknown entity column: {entity_column!r}.")
    for item in filter_rules.leaves(filters):
        if item.get("column") not in full.columns:
            raise ValueError(f"Unknown filter column: {item.get('column')!r}.")
    for chart in chart_specs:
        chart_measures.validate(chart, full.columns)
    if ds.get("live_source") is not None:
        import live_query
        import disk_data
        disk_data.guard_live_query(ds["live_source"], chart_specs, entity_column)
        return live_query.query(ds["live_source"], filters, chart_specs,
                                page, page_size, entity_column, refresh=refresh, sort=sort)
    if ds.get("disk_source") is not None:
        if refresh:
            raise ValueError("Refresh is not available for a disk-backed source.")
        import disk_data
        result = disk_data.query(ds["disk_source"], filters, chart_specs,
                                 page, page_size, entity_column, sort=sort)
        result["sampled"] = bool(result.get("sampled") or ds.get("capped"))
        return result

    import agg_duck
    if agg_duck.should_use(full):
        try:
            out = agg_duck.query(full, filters, chart_specs, page, page_size,
                                 entity_column=entity_column, sort=sort)
            out.update(scope="loaded", sampled=bool(ds.get("capped")))
            return out
        except ValueError:
            raise
        except Exception:
            # Both engines share one filter and category semantics, so pandas
            # returns the same result; the failure is still an engine defect.
            logger.exception("DuckDB aggregation failed for dataset %s (%d rows); "
                             "this query ran on pandas instead.", dataset_id, len(full))
    filt = apply_filters(full, filters)
    start = page * page_size
    ordered = filt.sort_values(sort["column"], ascending=sort["direction"] == "asc", na_position="last", kind="stable") if sort else filt
    rows_page = ordered.iloc[start:start + page_size]
    out = {
        "total": len(full),
        "filtered": len(filt),
        "charts": [chart_aggregate(full, filt, c) for c in chart_specs],
        "rows": {
            "page": page,
            "page_size": page_size,
            "columns": list(filt.columns),
            "data": rows_page.astype(object).where(rows_page.notna(), None)
                             .values.tolist(),
        },
        "scope": "loaded",
        "sampled": bool(ds.get("capped")),
    }
    if entity_column is not None:
        out["entity"] = {"column": entity_column,
                         "total": int(full[entity_column].nunique(dropna=True)),
                         "filtered": int(filt[entity_column].nunique(dropna=True))}
    return out
