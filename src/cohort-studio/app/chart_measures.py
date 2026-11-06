"""Chart measures and series, computed the same way on every engine.

pandas works on frames. The SQL engines (in-memory DuckDB, DuckDB on disk and
live PostgreSQL) share one builder and differ only in a small ``Dialect``.
Categories and series are ranked by unfiltered row count, so a filter never
reorders or recolors them; the values are computed over the filtered rows.
"""
import math

import numpy as np
import pandas as pd

AGGS = ("count", "count_distinct", "sum", "mean", "median", "min", "max")
NUMERIC_AGGS = {"sum", "mean", "median", "min", "max"}
TOP_CATEGORIES = 12
TOP_SERIES = 6
OTHER = "Other"


def measure_of(chart: dict) -> dict:
    measure = chart.get("measure") or {}
    return {"agg": measure.get("agg") or "count", "column": measure.get("column")}


def is_measured(chart: dict) -> bool:
    """True when a bar chart needs the measure/series path (not plain counts)."""
    return chart.get("kind") == "bar" and (bool(chart.get("series")) or measure_of(chart)["agg"] != "count")


def columns_used(chart: dict) -> list[str]:
    names = [chart.get("series")] if chart.get("series") else []
    column = measure_of(chart)["column"]
    if column and measure_of(chart)["agg"] != "count":
        names.append(column)
    return names


def validate(chart: dict, columns) -> None:
    measure = measure_of(chart)
    if measure["agg"] not in AGGS:
        raise ValueError(f"Unknown chart measure: {measure['agg']!r}.")
    if measure["agg"] != "count" and not measure["column"]:
        raise ValueError("Choose a field for the chart measure.")
    for name in columns_used(chart):
        if name not in columns:
            raise ValueError(f"Unknown chart field: {name!r}.")


def _clean(value):
    if value is None:
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _sort_categories(cats: list[str]) -> list[str]:
    try:
        return sorted(cats, key=float)
    except ValueError:
        return cats


def _shape(chart: dict, cats: list[str], series: list[str] | None, values: dict, has_other_cat: bool,
           has_other_series: bool) -> dict:
    """values maps (category or None, series or None) -> number; None means Other."""
    x = chart["x"]
    ordered = _sort_categories(list(cats)) + ([OTHER] if has_other_cat else [])
    key = lambda c: None if c == OTHER and has_other_cat else c
    measure = measure_of(chart)
    out = {"kind": "bar", "x": x, "measure": measure}
    if not series:
        out["data"] = [{"category": c, "value": _clean(values.get((key(c), None)))}
                       for c in ordered if (key(c), None) in values or c != OTHER]
        return out
    names = list(series) + ([OTHER] if has_other_series else [])
    skey = lambda s: None if s == OTHER and has_other_series else s
    out["series_column"] = chart["series"]
    out["series"] = names
    count = measure["agg"] in ("count", "count_distinct")
    out["data"] = [{"category": c, "values": [
        _clean(values.get((key(c), skey(s)), 0 if count else None)) for s in names]} for c in ordered]
    return out


# ---- pandas ----

def _top(values: pd.Series, n: int) -> tuple[list[str], bool]:
    counts = values.value_counts()
    frame = counts.rename_axis("v").reset_index(name="n").sort_values(["n", "v"], ascending=[False, True])
    top = list(frame["v"].head(n))
    return top, len(frame) > n


def _frame_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)


def frame_bar(full: pd.DataFrame, filt: pd.DataFrame, chart: dict) -> dict:
    x, s = chart["x"], chart.get("series")
    measure = measure_of(chart)
    keep = full[x].notna() & (full[s].notna() if s else True)
    cats, other_cat = _top(full.loc[keep, x].astype(str), TOP_CATEGORIES)
    series, other_series = _top(full.loc[keep, s].astype(str), TOP_SERIES) if s else (None, False)
    rows = filt[filt[x].notna() & (filt[s].notna() if s else True)]
    cat = rows[x].astype(str)
    work = pd.DataFrame({"c": cat.where(cat.isin(cats), None)}, index=rows.index)
    if s:
        ser = rows[s].astype(str)
        work["s"] = ser.where(ser.isin(series), None)
    else:
        work["s"] = None
    agg = measure["agg"]
    if agg == "count":
        work["v"] = 1
    elif agg == "count_distinct":
        work["v"] = rows[measure["column"]]
    else:
        work["v"] = _frame_numeric(rows[measure["column"]])
    values = {}
    for (c, sv), group in work.groupby(["c", "s"], dropna=False, sort=False)["v"]:
        c = None if pd.isna(c) else c
        sv = None if pd.isna(sv) else sv
        if agg == "count":
            result = len(group)
        elif agg == "count_distinct":
            result = int(group.nunique(dropna=True))
        elif group.notna().sum() == 0:
            result = None
        else:
            result = {"sum": group.sum, "mean": group.mean, "median": group.median,
                      "min": group.min, "max": group.max}[agg]()
        values[(c, sv)] = result
    return _shape(chart, cats, series, values, other_cat, other_series)


# ---- SQL ----

class Dialect:
    """What differs between DuckDB and PostgreSQL for these queries.

    ``rel`` is the FROM item; ``col(name)`` a column reference valid against it;
    ``where``/``where_params`` the engine's own filter clause."""

    def __init__(self, *, rel: str, col, number, text_type: str, named: bool, where: str,
                 where_params, run, postgres: bool):
        self.rel, self.col, self.number = rel, col, number
        self.text_type, self.named, self.postgres = text_type, named, postgres
        self.where, self.where_params, self.run = where, where_params, run

    def text(self, name: str) -> str:
        return f"CAST({self.col(name)} AS {self.text_type})"

    def quantile(self, expr: str, p: float) -> str:
        if self.postgres:
            return f"percentile_cont({p}) WITHIN GROUP (ORDER BY {expr})"
        return f"quantile_cont({expr}, {p})"


class _Binder:
    """Placeholders in textual order: positional lists for DuckDB, named for PostgreSQL."""

    def __init__(self, dialect: Dialect):
        self.d = dialect
        self.params = {} if dialect.named else []
        self.n = 0

    def values(self, items) -> str:
        marks = []
        for item in items:
            if self.d.named:
                key = f"chart_v{self.n}"
                self.n += 1
                self.params[key] = item
                marks.append(f":{key}")
            else:
                self.params.append(item)
                marks.append("?")
        return ", ".join(marks)

    def where(self) -> str:
        if self.d.named:
            self.params.update(self.d.where_params)
        else:
            self.params.extend(self.d.where_params)
        return self.d.where


def _sql_top(d: Dialect, name: str, also_not_null: str | None, n: int) -> tuple[list[str], bool]:
    extra = f" AND {d.col(also_not_null)} IS NOT NULL" if also_not_null else ""
    rows = d.run(f"SELECT {d.text(name)} AS v, COUNT(*) AS n FROM {d.rel} "
                 f"WHERE {d.col(name)} IS NOT NULL{extra} GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT {n + 1}",
                 {} if d.named else [])
    values = [str(r[0]) for r in rows]
    return values[:n], len(values) > n


def sql_bar(d: Dialect, chart: dict) -> dict:
    x, s = chart["x"], chart.get("series")
    measure = measure_of(chart)
    cats, other_cat = _sql_top(d, x, s, TOP_CATEGORIES)
    series, other_series = _sql_top(d, s, x, TOP_SERIES) if s else (None, False)
    if not cats or (s and not series):
        return _shape(chart, [], series or [], {}, False, False)
    agg = measure["agg"]
    if agg == "count":
        value = "COUNT(*)"
    elif agg == "count_distinct":
        value = f"COUNT(DISTINCT {d.col(measure['column'])})"
    else:
        number = d.number(measure["column"])
        functions = {"sum": "SUM", "mean": "AVG", "min": "MIN", "max": "MAX"}
        value = d.quantile(number, 0.5) if agg == "median" else f"{functions[agg]}({number})"
    b = _Binder(d)
    cat_case = f"CASE WHEN {d.text(x)} IN ({b.values(cats)}) THEN {d.text(x)} END"
    ser_case = f"CASE WHEN {d.text(s)} IN ({b.values(series)}) THEN {d.text(s)} END" if s else f"CAST(NULL AS {d.text_type})"
    not_null = f"{d.col(x)} IS NOT NULL" + (f" AND {d.col(s)} IS NOT NULL" if s else "")
    where = b.where()
    rows = d.run(f"SELECT {cat_case} AS c, {ser_case} AS s, {value} AS v FROM {d.rel} "
                 f"WHERE {not_null} AND ({where}) GROUP BY 1, 2", b.params)
    values = {(r[0], r[1]): r[2] for r in rows}
    return _shape(chart, cats, series, values, other_cat, other_series)


def duck_number(col: str) -> str:
    value = f"TRY_CAST({col} AS DOUBLE)"
    return f"CASE WHEN ISFINITE({value}) THEN {value} END"
