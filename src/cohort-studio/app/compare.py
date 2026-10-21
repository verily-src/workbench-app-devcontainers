import math

import numpy as np
import pandas as pd
from scipy import stats

import datasets

MIN_GROUP_N = 5
CAT_TOP_N = 10
EXPECTED_MIN = 5

def _numeric_test(a: pd.Series, b: pd.Series) -> dict:
    a = pd.to_numeric(a, errors="coerce").dropna()
    b = pd.to_numeric(b, errors="coerce").dropna()
    summary = {
        "a": {"n": int(a.size), "median": _f(a.median()), "mean": _f(a.mean())},
        "b": {"n": int(b.size), "median": _f(b.median()), "mean": _f(b.mean())},
    }
    if a.size < MIN_GROUP_N or b.size < MIN_GROUP_N:
        return {**summary, "p": None,
                "note": f"group too small (n<{MIN_GROUP_N})"}
    if a.nunique() == 1 and b.nunique() == 1 and a.iloc[0] == b.iloc[0]:
        return {**summary, "p": None, "note": "constant in both groups"}
    try:
        u = stats.mannwhitneyu(a, b, alternative="two-sided")
        return {**summary, "p": _p(u.pvalue), "test": "mann-whitney"}
    except ValueError as e:
        return {**summary, "p": None, "note": str(e)[:80]}

def _categorical_test(a: pd.Series, b: pd.Series) -> dict:
    a = a.dropna().astype(str)
    b = b.dropna().astype(str)

    top = (pd.concat([a, b]).value_counts().head(CAT_TOP_N).index.tolist())
    other_key = object()
    def tally(s):
        vc = s.value_counts()
        row = {c: int(vc.get(c, 0)) for c in top}
        row[other_key] = int(vc.drop(labels=top, errors="ignore").sum())
        return row
    a_row, b_row = tally(a), tally(b)
    cats = [c for c in list(top) + [other_key]
            if a_row.get(c, 0) + b_row.get(c, 0) > 0]
    summary = {
        "a": {"n": int(a.size), "top": _top_share(a_row, a.size, other_key)},
        "b": {"n": int(b.size), "top": _top_share(b_row, b.size, other_key)},
    }
    if a.size < MIN_GROUP_N or b.size < MIN_GROUP_N:
        return {**summary, "p": None,
                "note": f"group too small (n<{MIN_GROUP_N})"}
    table = np.array([[a_row[c] for c in cats], [b_row[c] for c in cats]])
    if table.shape[1] < 2 or (table.sum(axis=0) == 0).any():
        return {**summary, "p": None, "note": "not enough categories"}
    try:
        chi = stats.chi2_contingency(table)
        note = None
        if (chi.expected_freq < EXPECTED_MIN).any():
            note = f"low expected counts (<{EXPECTED_MIN}) — chi-square approx."
        return {**summary, "p": _p(chi.pvalue), "test": "chi-square",
                "note": note}
    except ValueError as e:
        return {**summary, "p": None, "note": str(e)[:80]}

def _top_share(row: dict, n: int, other_key=None) -> list:
    if n == 0:
        return []
    ranked = sorted(row.items(), key=lambda kv: kv[1], reverse=True)
    return [{"value": "Other (remaining categories)"
             if c is other_key and other_key is not None else c,
             "pct": round(100 * v / n, 1)}
            for c, v in ranked[:3] if v > 0]

def _profiles(ds: dict) -> list[dict]:
    profiles = datasets.profile_columns(ds["df"])
    settings = {setting["name"]: setting
                for setting in ds.get("column_settings", [])}
    for profile in profiles:
        setting = settings.get(profile["name"], {})
        if setting.get("filter_kind") is not None:
            profile["filter_kind"] = setting["filter_kind"]
    return profiles

def _benjamini_hochberg(pvals: list[float | None]) -> list[float | None]:

    idx = [i for i, p in enumerate(pvals) if p is not None]
    m = len(idx)
    q: list[float | None] = [None] * len(pvals)
    if m == 0:
        return q
    order = sorted(idx, key=lambda i: pvals[i])
    prev = 1.0
    for rank, i in enumerate(reversed(order), start=1):
        k = m - rank + 1
        val = min(prev, pvals[i] * m / k)
        q[i] = _p(val)
        prev = val
    return q

def _f(x) -> float | None:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    return round(float(x), 6)

def _p(x) -> float | None:

    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    x = float(x)
    if x == 0.0:
        return 0.0
    return round(x, -int(math.floor(math.log10(abs(x)))) + 2)

def compare(dataset_id: str, filters_a: list[dict], filters_b: list[dict],
            b_is_rest: bool = False) -> dict:

    ds = datasets.get(dataset_id)
    if ds.get("live_source") is not None:
        import live_compare
        return live_compare.compare(ds["live_source"], _profiles(ds),
                                   filters_a, filters_b, b_is_rest)
    df = ds["df"]
    a = datasets.apply_filters(df, filters_a)
    if b_is_rest:
        b = df.loc[~df.index.isin(a.index)]
    else:
        b = datasets.apply_filters(df, filters_b)

    columns = _profiles(ds)
    results = []
    for col in columns:
        kind = col["filter_kind"]
        name = col["name"]
        if kind == "range":
            r = _numeric_test(a[name], b[name])
        elif kind == "categorical":
            r = _categorical_test(a[name], b[name])
        else:
            continue
        results.append({"column": name, "kind": kind, **r})

    qvals = _benjamini_hochberg([r.get("p") for r in results])
    for r, q in zip(results, qvals):
        r["q"] = q

    results.sort(key=lambda r: (r.get("p") is None,
                                r["p"] if r.get("p") is not None else 1.0))
    return {
        "a_n": int(len(a)), "b_n": int(len(b)),
        "n_overlap": int(len(a.index.intersection(b.index))),
        "results": results,
    }
