import os
import math

import duckdb
import numpy as np

import category_text
import chart_measures
import filter_rules

DUCKDB_AGG_ROWS = int(os.environ.get("STUDIO_DUCKDB_AGG_ROWS", "50000"))

BAR_TOP_N = 12
HIST_BINS = 24
SCATTER_SAMPLE = 2000
HEATMAP_LIMIT = 400

def _q(col: str) -> str:

    return '"' + col.replace('"', '""') + '"'

def _where(filters: list[dict], columns) -> tuple[str, list]:
    """WHERE clause for Explore filters, including AND/OR criteria groups.

    ``columns`` maps names to DuckDB types (a plain set of names when unknown)."""
    return filter_rules.combine(filters, lambda flat: where_flat(flat, columns))


def where_flat(filters: list[dict], columns, qualifier: str = "") -> tuple[str, list]:
    """AND of ordinary filters for DuckDB, shared by in-memory and disk data."""
    types = columns if isinstance(columns, dict) else {}
    clauses, params = [], []
    for f in filters:
        name = f.get("column")
        if name not in columns:
            raise ValueError(f"Unknown filter column: {name!r}.")
        col = qualifier + _q(name)
        if f.get("kind") == "categorical" and f.get("values"):
            kind = (types.get(name) or "").upper()
            if kind in ("DOUBLE", "FLOAT", "REAL", "FLOAT4", "FLOAT8"):
                clauses.append(f"{col} IN (SELECT TRY_CAST(unnest(?) AS {kind}))")
                params.append([str(v) for v in f["values"]])
                continue
            vals = category_text.filter_values(f["values"], category_text.value_kind(types.get(name) or ""))
            if kind in ("BOOLEAN", "BOOL"):
                vals = [value.lower() for value in vals]
            placeholders = ", ".join(["?"] * len(vals))
            clauses.append(f"{category_text.duck_text(col, types.get(name))} IN ({placeholders})")
            params.extend(vals)
        elif f.get("kind") == "range" and filter_rules.is_active(f):
            low, high = filter_rules.range_bounds(f)
            category_text.check_range_duck(name, types.get(name))
            kind = (types.get(name) or "").upper()
            if kind in ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT"):
                lower = -(2**127) if low is None else math.ceil(low)
                upper = 2**127 - 1 if high is None else math.floor(high)
                if lower > upper or lower > 2**127 - 1 or upper < -(2**127):
                    clauses.append("FALSE")
                else:
                    clauses.append(f"{col} BETWEEN CAST(? AS HUGEINT) AND CAST(? AS HUGEINT)")
                    params.extend([str(max(lower, -(2**127))), str(min(upper, 2**127 - 1))])
                continue
            target = chart_measures.duck_number(col)
            if low is not None:
                clauses.append(f"{target} >= ?")
                params.append(low)
            if high is not None:
                clauses.append(f"{target} <= ?")
                params.append(high)
        elif f.get("kind") == "date" and filter_rules.is_active(f):
            # TIMESTAMPTZ reads ISO text with or without an offset; sessions run in UTC.
            start, end = filter_rules.date_bounds(f)
            target = f"TRY_CAST({col} AS TIMESTAMPTZ)"
            if start:
                clauses.append(f"{target} >= ?")
                params.append(start)
            if end:
                clauses.append(f"{target} < ?")
                params.append(end)
    return (" AND ".join(clauses) if clauses else "TRUE"), params

class _Agg:
    def __init__(self, con, where: str, params: list, types: dict):
        self.con = con
        self.where = where
        self.params = params
        self.types = types

    def text(self, name: str) -> str:
        return category_text.duck_text(_q(name), self.types.get(name))

    def one(self, sql: str, params: list):
        return self.con.execute(sql, params).fetchall()[0]

    def all(self, sql: str, params: list):
        return self.con.execute(sql, params).fetchall()

def _bar(agg: _Agg, x: str) -> dict:
    qx, tx = _q(x), agg.text(x)

    full_top = agg.all(
        f"SELECT {tx} v, COUNT(*) c FROM t "
        f"WHERE {qx} IS NOT NULL GROUP BY v ORDER BY c DESC, v LIMIT {BAR_TOP_N}",
        [])
    full_total = agg.one(
        f"SELECT COUNT(*) FROM t WHERE {qx} IS NOT NULL", [])[0]
    cats = [r[0] for r in full_top]
    try:
        cats_sorted = sorted(cats, key=float)
    except ValueError:
        cats_sorted = cats
    full_counts = {r[0]: int(r[1]) for r in full_top}

    sel_total = agg.one(
        f"SELECT COUNT(*) FROM t WHERE ({agg.where}) AND {qx} IS NOT NULL",
        agg.params)[0]
    sel_counts = {}
    if cats:
        ph = ", ".join(["?"] * len(cats))
        rows = agg.all(
            f"SELECT {tx} v, COUNT(*) c FROM t "
            f"WHERE ({agg.where}) AND {tx} IN ({ph}) "
            f"GROUP BY v", agg.params + cats)
        sel_counts = {r[0]: int(r[1]) for r in rows}

    data = [{"category": c, "all": full_counts.get(c, 0),
             "selected": sel_counts.get(c, 0)} for c in cats_sorted]
    if full_total > sum(full_counts.values()):
        other_all = full_total - sum(full_counts.values())
        other_sel = sel_total - sum(sel_counts.values())
        data.append({"category": "Other", "all": int(other_all),
                     "selected": int(other_sel)})
    return {"kind": "bar", "x": x, "data": data}

def _histogram(agg: _Agg, x: str) -> dict:
    qx = _q(x)
    mn, mx = agg.one(
        f"SELECT MIN(TRY_CAST({qx} AS DOUBLE)), MAX(TRY_CAST({qx} AS DOUBLE)) "
        f"FROM t", [])
    if mn is None or mx is None:
        return {"kind": "histogram", "x": x, "data": []}
    edges = np.histogram_bin_edges([mn, mx], bins=HIST_BINS, range=(mn, mx))
    mn_e, mx_e = float(edges[0]), float(edges[-1])
    width = (mx_e - mn_e) / HIST_BINS or 1.0

    bucket = (f"LEAST({HIST_BINS - 1}, GREATEST(0, "
              f"CAST(FLOOR((TRY_CAST({qx} AS DOUBLE) - {mn_e}) / {width}) "
              f"AS BIGINT)))")
    val_ok = f"TRY_CAST({qx} AS DOUBLE) IS NOT NULL"

    def counts(extra_where: str, params: list) -> dict:
        rows = agg.all(
            f"SELECT {bucket} b, COUNT(*) c FROM t "
            f"WHERE {val_ok} AND ({extra_where}) GROUP BY b", params)
        return {int(r[0]): int(r[1]) for r in rows}

    full = counts("TRUE", [])
    sel = counts(agg.where, agg.params)
    data = [{"lo": float(edges[i]), "hi": float(edges[i + 1]),
             "all": full.get(i, 0), "selected": sel.get(i, 0)}
            for i in range(HIST_BINS)]
    return {"kind": "histogram", "x": x, "data": data}

def _scatter(agg: _Agg, x: str, y: str) -> dict:
    qx, qy = _q(x), _q(y)
    val = (f"SELECT TRY_CAST({qx} AS DOUBLE) a, TRY_CAST({qy} AS DOUBLE) b "
           f"FROM t WHERE ({agg.where}) AND TRY_CAST({qx} AS DOUBLE) IS NOT NULL "
           f"AND TRY_CAST({qy} AS DOUBLE) IS NOT NULL")
    n = agg.one(f"SELECT COUNT(*) FROM ({val})", agg.params)[0]
    sampled = n > SCATTER_SAMPLE
    if sampled:
        rows = agg.all(
            f"{val} USING SAMPLE {SCATTER_SAMPLE} ROWS (reservoir, 7)",
            agg.params)
    else:
        rows = agg.all(val, agg.params)
    return {"kind": "scatter", "x": x, "y": y, "sampled": sampled,
            "data": [[float(a), float(b)] for a, b in rows]}

def _heatmap(agg: _Agg, x: str, y: str) -> dict:
    qx, qy = _q(x), _q(y)
    rows = agg.all(
        f"SELECT {agg.text(x)} a, {agg.text(y)} b, COUNT(*) c "
        f"FROM t WHERE ({agg.where}) AND {qx} IS NOT NULL AND {qy} IS NOT NULL "
        f"GROUP BY a, b ORDER BY c DESC, a, b LIMIT {HEATMAP_LIMIT + 1}", agg.params)
    return {"kind": "heatmap", "x": x, "y": y, "sampled": len(rows) > HEATMAP_LIMIT,
            "data": [[a, b, int(c)] for a, b, c in rows[:HEATMAP_LIMIT]]}

def _dialect(agg: _Agg) -> chart_measures.Dialect:
    return chart_measures.Dialect(
        rel="t", col=_q, number=lambda name: chart_measures.duck_number(_q(name)),
        text_type="VARCHAR", named=False, where=agg.where, where_params=agg.params,
        run=agg.all, postgres=False, text=agg.text)

def _chart(agg: _Agg, chart: dict, columns) -> dict:
    kind, x, y = chart.get("kind"), chart.get("x"), chart.get("y")
    if x not in columns or (y and y not in columns):
        return {"kind": kind, "x": x, "data": []}
    if chart_measures.is_measured(chart):
        return chart_measures.sql_bar(_dialect(agg), chart)
    if kind == "box":
        return chart_measures.sql_box(_dialect(agg), chart)
    if kind == "bar":
        return _bar(agg, x)
    if kind == "histogram":
        return _histogram(agg, x)
    if kind == "scatter" and y:
        return _scatter(agg, x, y)
    if kind == "heatmap" and y:
        return _heatmap(agg, x, y)
    return {"kind": kind, "x": x, "data": []}

def should_use(df) -> bool:
    names = [str(name).casefold() for name in df.columns]
    return len(df) >= DUCKDB_AGG_ROWS and len(names) == len(set(names))

def connect():
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    return con

def query(df, filters: list[dict], chart_specs: list[dict],
          page: int, page_size: int, entity_column: str | None = None,
          sort: dict | None = None) -> dict:

    pos = "__pos__"
    names = {str(name).casefold() for name in df.columns}
    while pos.casefold() in names:
        pos += "_"
    pos_df = df.copy(deep=False)
    pos_df[pos] = np.arange(len(df))
    sel = ", ".join(_q(c) for c in df.columns)
    con = connect()
    try:
        con.register("t", pos_df)
        described = {row[0]: row[1] for row in con.execute("DESCRIBE t").fetchall()}
        types = {name: described.get(name) for name in df.columns}
        where, params = _where(filters, types)
        agg = _Agg(con, where, params, types)
        total = len(df)
        filtered = agg.one(f"SELECT COUNT(*) FROM t WHERE {where}", params)[0]
        entity = None
        if entity_column is not None:
            qe = _q(entity_column)
            entity_total, entity_filtered = agg.one(
                f"SELECT COUNT(DISTINCT {qe}), COUNT(DISTINCT {qe}) FILTER (WHERE {where}) FROM t",
                params)
            entity = {"column": entity_column, "total": int(entity_total),
                      "filtered": int(entity_filtered)}
        charts = [category_text.normalize_chart(_chart(agg, c, types), types) for c in chart_specs]
        start = page * page_size
        order = _q(pos)
        if sort:
            order = f"{_q(sort['column'])} {sort['direction'].upper()} NULLS LAST, {order}"
        page_rows = con.execute(
            f"SELECT {sel} FROM t WHERE {where} "
            f"ORDER BY {order} LIMIT {int(page_size)} OFFSET {int(start)}",
            params).df()
        rows = {
            "page": page, "page_size": page_size,
            "columns": list(page_rows.columns),
            "data": page_rows.astype(object)
                             .where(page_rows.notna(), None).values.tolist(),
        }
    finally:
        con.close()
    out = {"total": int(total), "filtered": int(filtered),
           "charts": charts, "rows": rows}
    if entity is not None:
        out["entity"] = entity
    return out
