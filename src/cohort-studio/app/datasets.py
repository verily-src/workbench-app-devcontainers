import threading
import time
import uuid

import numpy as np
import pandas as pd

import queries

MAX_DATASETS = 8
DATASET_TTL = 4 * 3600
CATEGORICAL_VALUES_LIMIT = 50
BAR_TOP_N = 12
HIST_BINS = 24
SCATTER_SAMPLE = 2000

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
                 temporary: bool = False) -> dict:

    if live_source is not None or disk_source is not None:
        capped = False
    if capped is None:
        capped = len(df) >= queries.ROW_CAP
    try:
        columns = profile_columns(df)
        if live_source is not None:
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
            "large_warning": bool(estimate_source.get("large_warning"))}

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
            values = (df[col].dropna().astype(str).value_counts()
                      .head(CATEGORICAL_VALUES_LIMIT))
            entry["values"] = list(values.index)
        elif kind == "range":
            entry["min"] = float(df[col].min())
            entry["max"] = float(df[col].max())
        profile.append(entry)
    return profile

def apply_filters(df: pd.DataFrame, filters: list[dict]) -> pd.DataFrame:
    for f in filters:
        col = f.get("column")
        if col not in df.columns:
            raise ValueError(f"Unknown filter column: {col!r}.")
        if f.get("kind") == "categorical" and f.get("values"):
            df = df[df[col].astype(str).isin(f["values"])]
        elif f.get("kind") == "range":
            lo, hi = f.get("min"), f.get("max")
            if lo is not None and hi is not None:
                df = df[df[col].between(lo, hi)]
    return df

def _bar_aggregate(full: pd.DataFrame, filt: pd.DataFrame, x: str) -> dict:
    counts = full[x].dropna().astype(str).value_counts()
    cats = list(counts.head(BAR_TOP_N).index)
    try:
        cats.sort(key=float)
    except ValueError:
        pass
    selected = filt[x].dropna().astype(str).value_counts()
    rows = [{"category": c, "all": int(counts[c]),
             "selected": int(selected.get(c, 0))} for c in cats]
    if len(counts) > BAR_TOP_N:
        rest = counts.index[BAR_TOP_N:]
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

    sub = pd.DataFrame({x: pd.to_numeric(filt[x], errors="coerce"),
                        y: pd.to_numeric(filt[y], errors="coerce")}).dropna()
    if len(sub) > SCATTER_SAMPLE:
        sub = sub.sample(SCATTER_SAMPLE, random_state=7)
    return {"kind": "scatter", "x": x, "y": y,
            "data": sub.values.tolist()}

def _heatmap_aggregate(filt: pd.DataFrame, x: str, y: str) -> dict:
    counts = (filt.dropna(subset=[x, y]).astype({x: str, y: str})
              .groupby([x, y], observed=True).size().reset_index(name="n"))
    counts = counts.nlargest(400, "n")
    return {"kind": "heatmap", "x": x, "y": y,
            "data": counts.values.tolist()}

def chart_aggregate(full: pd.DataFrame, filt: pd.DataFrame,
                    chart: dict) -> dict:
    kind, x, y = chart.get("kind"), chart.get("x"), chart.get("y")
    if x not in full.columns or (y and y not in full.columns):
        return {"kind": kind, "x": x, "data": []}
    if kind == "bar":
        return _bar_aggregate(full, filt, x)
    if kind == "histogram":
        return _histogram_aggregate(full, filt, x)
    if kind == "scatter" and y:
        return _scatter_aggregate(filt, x, y)
    if kind == "heatmap" and y:
        return _heatmap_aggregate(filt, x, y)
    return {"kind": kind, "x": x, "data": []}

def query(dataset_id: str, filters: list[dict], chart_specs: list[dict],
          page: int = 0, page_size: int = 50,
          entity_column: str | None = None, refresh: bool = False) -> dict:
    ds = get(dataset_id)
    full = ds["df"]

    if entity_column is not None and entity_column not in full.columns:
        raise ValueError(f"Unknown entity column: {entity_column!r}.")
    for item in filters:
        if item.get("column") not in full.columns:
            raise ValueError(f"Unknown filter column: {item.get('column')!r}.")
    if ds.get("live_source") is not None:
        import live_query
        import disk_data
        disk_data.guard_live_query(ds["live_source"], chart_specs, entity_column)
        return live_query.query(ds["live_source"], filters, chart_specs,
                                page, page_size, entity_column, refresh=refresh)
    if ds.get("disk_source") is not None:
        if refresh:
            raise ValueError("Refresh is not available for a disk-backed source.")
        import disk_data
        return disk_data.query(ds["disk_source"], filters, chart_specs,
                               page, page_size, entity_column)

    import agg_duck
    if agg_duck.should_use(full):
        try:
            out = agg_duck.query(full, filters, chart_specs, page, page_size)
            out.update(scope="loaded", sampled=bool(ds.get("capped")))
            if entity_column is not None:
                filtered = apply_filters(full, filters)
                out["entity"] = {"column": entity_column,
                                 "total": int(full[entity_column].nunique(dropna=True)),
                                 "filtered": int(filtered[entity_column].nunique(dropna=True))}
            return out
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "DuckDB agg path failed, falling back to pandas: %s", e)
    filt = apply_filters(full, filters)
    start = page * page_size
    rows_page = filt.iloc[start:start + page_size]
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
