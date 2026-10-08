"""Two-cohort group comparison, cBioPortal-style.

Given two filter sets over the same dataset, test every filterable column
for a difference between the groups and rank by significance:
- numeric columns: Mann-Whitney U (nonparametric, no normality assumption)
- categorical columns: chi-square on the contingency table (top categories)

p-values are corrected across columns with Benjamini-Hochberg (FDR), so the
ranked list is honest about multiple testing. Small groups and degenerate
columns report summaries without a test rather than a misleading p-value.
"""

import math

import numpy as np
import pandas as pd
from scipy import stats

import datasets

MIN_GROUP_N = 5          # below this, report n's but skip the test
CAT_TOP_N = 10           # categories kept in the chi-square table (+ Other)
EXPECTED_MIN = 5         # chi-square cells below this are flagged, not dropped


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
    # Keep the most common categories across both groups; fold the rest.
    top = (pd.concat([a, b]).value_counts().head(CAT_TOP_N).index.tolist())
    def tally(s):
        vc = s.value_counts()
        row = {c: int(vc.get(c, 0)) for c in top}
        row["Other"] = int(vc.drop(labels=top, errors="ignore").sum())
        return row
    a_row, b_row = tally(a), tally(b)
    cats = [c for c in list(top) + ["Other"]
            if a_row.get(c, 0) + b_row.get(c, 0) > 0]
    summary = {
        "a": {"n": int(a.size), "top": _top_share(a_row, a.size)},
        "b": {"n": int(b.size), "top": _top_share(b_row, b.size)},
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


def _top_share(row: dict, n: int) -> list:
    if n == 0:
        return []
    ranked = sorted(row.items(), key=lambda kv: kv[1], reverse=True)
    return [{"value": c, "pct": round(100 * v / n, 1)}
            for c, v in ranked[:3] if v > 0]


def _benjamini_hochberg(pvals: list[float | None]) -> list[float | None]:
    """FDR q-values; None p's (untested columns) pass through as None."""
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
    """Round a p/q value to 3 significant figures so tiny values survive
    (round(1e-30, 6) == 0.0, which would both lose the magnitude and break
    an ascending sort)."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    x = float(x)
    if x == 0.0:
        return 0.0
    return round(x, -int(math.floor(math.log10(abs(x)))) + 2)


def compare(dataset_id: str, filters_a: list[dict], filters_b: list[dict],
            b_is_rest: bool = False) -> dict:
    """Compare two cohorts over a dataset. If b_is_rest, group B is the
    complement of group A (selected-vs-rest), ignoring filters_b."""
    ds = datasets.get(dataset_id)
    df = ds["df"]
    a = datasets.apply_filters(df, filters_a)
    if b_is_rest:
        b = df.loc[~df.index.isin(a.index)]
    else:
        b = datasets.apply_filters(df, filters_b)

    columns = datasets.profile_columns(df)
    results = []
    for col in columns:
        kind = col["filter_kind"]
        name = col["name"]
        if kind == "range":
            r = _numeric_test(a[name], b[name])
        elif kind == "categorical":
            r = _categorical_test(a[name], b[name])
        else:
            continue  # free-text / unfilterable columns aren't comparable
        results.append({"column": name, "kind": kind, **r})

    qvals = _benjamini_hochberg([r.get("p") for r in results])
    for r, q in zip(results, qvals):
        r["q"] = q
    # Rank: tested columns by p ascending, untested columns last.
    results.sort(key=lambda r: (r.get("p") is None,
                                r["p"] if r.get("p") is not None else 1.0))
    return {
        "a_n": int(len(a)), "b_n": int(len(b)),
        "n_overlap": int(len(a.index.intersection(b.index))),
        "results": results,
    }
