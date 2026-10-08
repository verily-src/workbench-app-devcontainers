"""DuckDB-backed cross-filter aggregation — a faster path for large frames.

pandas stays the backbone (datasets.py); this mirrors its aggregation in
DuckDB SQL over the in-memory frame (zero-copy via DuckDB's pandas scan)
so the O(n) work — filtering, group/count, binning, paging — runs in a
vectorised columnar engine. It kicks in only above DUCKDB_AGG_ROWS; below
that pandas is already sub-100ms and simpler.

Output is byte-for-byte identical to datasets.py for the deterministic
aggregates (counts, bar, histogram, heatmap, rows) — enforced by parity
tests. Scatter uses DuckDB reservoir sampling, so only its shape matches.
The small tail work (top-N float sort, "Other" bucket) stays in Python to
match pandas exactly.
"""

import os

import duckdb
import numpy as np

import queries

# Hand large frames to DuckDB; keep small ones on the (simpler) pandas path.
DUCKDB_AGG_ROWS = int(os.environ.get("STUDIO_DUCKDB_AGG_ROWS", "50000"))

BAR_TOP_N = 12
HIST_BINS = 24
SCATTER_SAMPLE = 2000


def _q(col: str) -> str:
    """Quote an identifier for DuckDB (double-quotes, escaped)."""
    return '"' + col.replace('"', '""') + '"'


def _where(filters: list[dict], columns: set) -> tuple[str, list]:
    """Build a WHERE clause + params mirroring datasets.apply_filters."""
    clauses, params = [], []
    for f in filters:
        col = f.get("column")
        if col not in columns:
            continue
        if f.get("kind") == "categorical" and f.get("values"):
            vals = [str(v) for v in f["values"]]
            placeholders = ", ".join(["?"] * len(vals))
            clauses.append(f"CAST({_q(col)} AS VARCHAR) IN ({placeholders})")
            params.extend(vals)
        elif f.get("kind") == "range":
            lo, hi = f.get("min"), f.get("max")
            if lo is not None and hi is not None:
                clauses.append(f"TRY_CAST({_q(col)} AS DOUBLE) BETWEEN ? AND ?")
                params.extend([float(lo), float(hi)])
    return (" AND ".join(clauses) if clauses else "TRUE"), params


class _Agg:
    def __init__(self, con, where: str, params: list):
        self.con = con
        self.where = where
        self.params = params

    def one(self, sql: str, params: list):
        return self.con.execute(sql, params).fetchone()

    def all(self, sql: str, params: list):
        return self.con.execute(sql, params).fetchall()


def _bar(agg: _Agg, x: str) -> dict:
    qx = _q(x)
    # Full (unfiltered) top categories + non-null total.
    full_top = agg.all(
        f"SELECT CAST({qx} AS VARCHAR) v, COUNT(*) c FROM t "
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

    # Selected (filtered) counts for the same categories + filtered total.
    sel_total = agg.one(
        f"SELECT COUNT(*) FROM t WHERE ({agg.where}) AND {qx} IS NOT NULL",
        agg.params)[0]
    sel_counts = {}
    if cats:
        ph = ", ".join(["?"] * len(cats))
        rows = agg.all(
            f"SELECT CAST({qx} AS VARCHAR) v, COUNT(*) c FROM t "
            f"WHERE ({agg.where}) AND CAST({qx} AS VARCHAR) IN ({ph}) "
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
    # bucket = floor((v - min) / width), clamped to [0, BINS-1]
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
    if n > SCATTER_SAMPLE:
        rows = agg.all(
            f"{val} USING SAMPLE {SCATTER_SAMPLE} ROWS (reservoir, 7)",
            agg.params)
    else:
        rows = agg.all(val, agg.params)
    return {"kind": "scatter", "x": x, "y": y,
            "data": [[float(a), float(b)] for a, b in rows]}


def _heatmap(agg: _Agg, x: str, y: str) -> dict:
    qx, qy = _q(x), _q(y)
    rows = agg.all(
        f"SELECT CAST({qx} AS VARCHAR) a, CAST({qy} AS VARCHAR) b, COUNT(*) c "
        f"FROM t WHERE ({agg.where}) AND {qx} IS NOT NULL AND {qy} IS NOT NULL "
        f"GROUP BY a, b ORDER BY c DESC, a, b LIMIT 400", agg.params)
    return {"kind": "heatmap", "x": x, "y": y,
            "data": [[a, b, int(c)] for a, b, c in rows]}


def _chart(agg: _Agg, chart: dict, columns: set) -> dict:
    kind, x, y = chart.get("kind"), chart.get("x"), chart.get("y")
    if x not in columns or (y and y not in columns):
        return {"kind": kind, "x": x, "data": []}
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
    return len(df) >= DUCKDB_AGG_ROWS


def query(df, filters: list[dict], chart_specs: list[dict],
          page: int, page_size: int) -> dict:
    """DuckDB equivalent of datasets.query — identical response shape."""
    columns = set(df.columns)
    where, params = _where(filters, columns)
    # Add a positional column so the rows page has a deterministic ORDER BY —
    # SQL row order is undefined without one once DuckDB parallelises a scan.
    pos_df = df.reset_index(drop=True).rename_axis("__pos__").reset_index()
    sel = ", ".join(_q(c) for c in df.columns)
    con = duckdb.connect()
    try:
        con.register("t", pos_df)
        agg = _Agg(con, where, params)
        total = len(df)
        filtered = agg.one(f"SELECT COUNT(*) FROM t WHERE {where}", params)[0]
        charts = [_chart(agg, c, columns) for c in chart_specs]
        start = page * page_size
        page_rows = con.execute(
            f"SELECT {sel} FROM t WHERE {where} "
            f"ORDER BY __pos__ LIMIT {page_size} OFFSET {start}",
            params).df()
        rows = {
            "page": page, "page_size": page_size,
            "columns": list(page_rows.columns),
            "data": page_rows.astype(object)
                             .where(page_rows.notna(), None).values.tolist(),
        }
    finally:
        con.close()
    return {"total": int(total), "filtered": int(filtered),
            "charts": charts, "rows": rows}
