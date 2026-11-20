"""Classical baselines for the same forecast, on features built by rule from the schema, trained on
the same labeled history Kumo reads in context (all of it, not a sample). For each cutoff:

- per dated table, the number of rows in the year before;
- per split table (a table of one frequent code), the last value and its change over two years;
- per static table, its numeric columns as they are, and a one-hot of each categorical column's
  four most common values (the first row per entity when a static table has several);
- the cutoff's year, so a birth year or an enrolment year can be read as an age or a tenure.

Two models: logistic regression and gradient-boosted trees. No feature is chosen for an outcome.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from . import schema
from .dataset import TARGET, Dataset

CATEGORICAL_VALUES = 4


def static_features(ds: Dataset) -> pd.DataFrame:
    """One row per entity from the static tables: numeric columns as they are, categorical columns
    one-hot over their most common values."""
    out = None
    for name in ds.static:
        df = ds.raw[name].drop_duplicates(ds.key).set_index(ds.key)
        cols = {}
        for c, ty in ds.schemas[name]["columns"]:
            if c == ds.key or c not in df:
                continue
            if c in ds.pk.values() and c == f"{name}_id":
                continue
            categorical = ty == "STRING" or (ty in schema.INTEGER_TYPES and schema.CODE_NAME.search(c.lower()))
            if categorical:
                for v in df[c].value_counts().head(CATEGORICAL_VALUES).index:
                    cols[f"{name}.{c}={v}"] = (df[c] == v).astype(int)
            elif ty in schema.NUMBER_TYPES and not c.endswith("_id"):
                cols[f"{name}.{c}"] = pd.to_numeric(df[c], errors="coerce")
        part = pd.DataFrame(cols, index=df.index)
        out = part if out is None else out.join(part, how="outer")
    return out if out is not None else pd.DataFrame(index=pd.Index([], name=ds.key))


def _features(ds: Dataset, static: pd.DataFrame, rows: pd.DataFrame) -> pd.DataFrame:
    key = ds.key
    out = []
    dated = [n for n in ds.dated]
    for cut, grp in rows.groupby("cutoff"):
        ids = pd.Index(grp[key].unique())
        f = pd.DataFrame(index=pd.Index(ids, name=key))
        for name in dated:
            col = ds.raw_time[name]
            d = ds.raw[name]
            d = d[(d[col] <= cut) & (d[col] > cut - pd.DateOffset(years=1)) & d[key].isin(ids)]
            # An entity with no rows in the year had none: 0, not a missing value to impute.
            f[f"rows_last_year.{name}"] = d.groupby(key).size().reindex(f.index, fill_value=0)
        for sname, info in ds.split.items():
            col = ds.time[sname]
            value = schema.value_column(ds.schemas[info["source"]]["columns"], key, info["code_column"])
            d = ds.splits[sname]
            d = d[(d[col] <= cut) & d[key].isin(ids)].sort_values(col)
            last = d.groupby(key)[value].last()
            prev = d[d[col] <= cut - pd.DateOffset(years=2)].groupby(key)[value].last()
            f[f"last.{sname}"] = last
            f[f"change.{sname}"] = last - prev
        f = f.join(static.reindex(ids))
        f["cutoff_year"] = cut.year
        f["cutoff"] = cut
        out.append(f.reset_index())
    feats = pd.concat(out, ignore_index=True)
    return rows.merge(feats, on=[key, "cutoff"], how="left")


def compare(ds: Dataset, pool: pd.DataFrame, query: pd.DataFrame) -> pd.DataFrame:
    """The query rows with a ``logistic_regression`` and a ``gradient_boosting`` score added."""
    key = ds.key
    static = static_features(ds)
    tr = _features(ds, static, pool)
    te = _features(ds, static, query)
    cols = [c for c in tr.columns if c not in (key, "cutoff", TARGET, "risk")]
    cols = [c for c in cols if tr[c].notna().any()]
    te = te.reindex(columns=list(te.columns) + [c for c in cols if c not in te.columns])
    y = tr[TARGET].astype(int)
    lr = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                       LogisticRegression(max_iter=2000, class_weight="balanced")).fit(tr[cols], y)
    gb = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, random_state=0).fit(tr[cols], y)
    out = query.copy()
    out["logistic_regression"] = lr.predict_proba(te[cols])[:, 1]
    out["gradient_boosting"] = gb.predict_proba(te[cols])[:, 1]
    return out


def auroc(y: np.ndarray, s: np.ndarray) -> float | None:
    from sklearn.metrics import roc_auc_score
    return round(float(roc_auc_score(y, s)), 3) if 0 < y.sum() < len(y) else None
