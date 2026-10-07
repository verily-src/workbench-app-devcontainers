"""In-memory dataset store and server-side cross-filter aggregation.

The frontend is thin: it sends the current filter set and the list of
charts it is showing, and gets back everything it needs to render in a
single round trip — counts, per-chart aggregates (full cohort and
filtered cohort), and a page of rows. All statistics stay server-side.
"""

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
        del _store[k]
    while len(_store) > MAX_DATASETS:
        oldest = min(_store, key=lambda k: _store[k]["created"])
        del _store[oldest]


def open_dataset(df: pd.DataFrame, source: str) -> dict:
    with _lock:
        _evict()
        dataset_id = uuid.uuid4().hex[:12]
        _store[dataset_id] = {"df": df, "source": source,
                              "created": time.monotonic()}
    return {"dataset_id": dataset_id, "source": source,
            "rows": len(df), "columns": profile_columns(df)}


def get(dataset_id: str) -> dict:
    try:
        return _store[dataset_id]
    except KeyError:
        raise DatasetNotFound(dataset_id)


def close_dataset(dataset_id: str):
    with _lock:
        _store.pop(dataset_id, None)


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
            continue
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
    values = full[x].dropna().astype(float)
    if values.empty:
        return {"kind": "histogram", "x": x, "data": []}
    counts, edges = np.histogram(values, bins=HIST_BINS)
    filt_counts, _ = np.histogram(filt[x].dropna().astype(float), bins=edges)
    data = [{"lo": float(edges[i]), "hi": float(edges[i + 1]),
             "all": int(counts[i]), "selected": int(filt_counts[i])}
            for i in range(len(counts))]
    return {"kind": "histogram", "x": x, "data": data}


def _scatter_aggregate(filt: pd.DataFrame, x: str, y: str) -> dict:
    sub = filt[[x, y]].dropna()
    if len(sub) > SCATTER_SAMPLE:
        sub = sub.sample(SCATTER_SAMPLE, random_state=7)
    return {"kind": "scatter", "x": x, "y": y,
            "data": sub.astype(float).values.tolist()}


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
          page: int = 0, page_size: int = 50) -> dict:
    ds = get(dataset_id)
    full = ds["df"]
    filt = apply_filters(full, filters)
    start = page * page_size
    rows_page = filt.iloc[start:start + page_size]
    return {
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
    }
