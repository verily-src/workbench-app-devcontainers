import math

import numpy as np
from scipy import stats

import db
import live_query
from sql_utils import statement as text

MIN_GROUP_N = 5
CAT_TOP_N = 10
EXPECTED_MIN = 5
TIMEOUT_MS = 15_000


def _q(value):
    return '"' + value.replace('"', '""') + '"'


def _where(filters, columns, prefix):
    clauses, params = [], {}
    for i, item in enumerate(filters):
        name = item.get("column")
        if name not in columns:
            raise ValueError(f"Unknown filter column: {name!r}.")
        col = f"src.{_q(columns[name])}"
        kind = item.get("kind")
        if kind == "categorical" and item.get("values"):
            keys = []
            for j, value in enumerate(item["values"]):
                key = f"{prefix}{i}_{j}"
                keys.append(f":{key}")
                params[key] = str(value)
            clauses.append(f"CAST({col} AS text) IN ({', '.join(keys)})")
        elif kind == "range" and item.get("min") is not None and item.get("max") is not None:
            lo, hi = float(item["min"]), float(item["max"])
            if not math.isfinite(lo) or not math.isfinite(hi):
                raise ValueError("Range filter values must be finite.")
            clauses.append(f"{live_query._numeric(col)} BETWEEN :{prefix}{i}_lo AND :{prefix}{i}_hi")
            params[f"{prefix}{i}_lo"] = lo
            params[f"{prefix}{i}_hi"] = hi
    return " AND ".join(clauses) if clauses else "TRUE", params


def _numeric(conn, table, column, a_where, b_where, params):
    x = live_query._numeric(f"src.{_q(column)}")
    samples = (f"SELECT {x} AS x, 'a' AS grp FROM {table} WHERE ({a_where}) "
               f"UNION ALL SELECT {x} AS x, 'b' AS grp FROM {table} WHERE ({b_where})")
    row = conn.execute(text(
        f"WITH samples AS ({samples}), stats AS ("
        "SELECT grp, COUNT(x) AS n, AVG(x) AS mean, "
        "PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY x) AS median, "
        "MIN(x) AS min, MAX(x) AS max FROM samples GROUP BY grp), "
        "groups AS (SELECT x, COUNT(*) FILTER (WHERE grp='a') AS a, "
        "COUNT(*) FILTER (WHERE grp='b') AS b FROM samples WHERE x IS NOT NULL "
        "GROUP BY x), ranked AS (SELECT x, a, b, "
        "COALESCE(SUM(b) OVER (ORDER BY x ROWS BETWEEN UNBOUNDED PRECEDING "
        "AND 1 PRECEDING), 0) AS b_less, (a+b) AS tied FROM groups), "
        "u AS (SELECT COALESCE(SUM(a * (b_less + b * 0.5)), 0) AS value "
        "FROM ranked), ties AS (SELECT COALESCE(SUM(tied::numeric*tied*tied-tied),0) AS value "
        "FROM ranked) SELECT stats.grp, stats.n, stats.mean, stats.median, "
        "stats.min, stats.max, u.value, ties.value FROM stats CROSS JOIN u CROSS JOIN ties"),
        params).all()
    by_group = {r[0]: r[1:] for r in row}
    a, b = by_group.get("a"), by_group.get("b")
    summary = {
        "a": {"n": int(a[0]) if a else 0,
              "median": _f(a[2]) if a else None, "mean": _f(a[1]) if a else None},
        "b": {"n": int(b[0]) if b else 0,
              "median": _f(b[2]) if b else None, "mean": _f(b[1]) if b else None},
    }
    n1, n2 = summary["a"]["n"], summary["b"]["n"]
    if n1 < MIN_GROUP_N or n2 < MIN_GROUP_N:
        return {**summary, "p": None, "note": f"group too small (n<{MIN_GROUP_N})"}
    if a[3] == a[4] and b[3] == b[4] and a[3] == b[3]:
        return {**summary, "p": None, "note": "constant in both groups"}
    n = n1 + n2
    tie_sum = float(a[6] if a[6] is not None else b[6])
    if min(n1, n2) <= 8 and n <= 10_000 and tie_sum == 0:
        values = conn.execute(text(
            f"WITH samples AS ({samples}) SELECT x, grp FROM samples WHERE x IS NOT NULL"),
            params).all()
        values_a = [x for x, group in values if group == "a"]
        values_b = [x for x, group in values if group == "b"]
        test = stats.mannwhitneyu(values_a, values_b, alternative="two-sided")
        return {**summary, "p": _p(test.pvalue), "test": "mann-whitney"}
    variance = n1 * n2 / 12 * ((n + 1) - tie_sum / (n * (n - 1)))
    if variance <= 0:
        return {**summary, "p": None, "note": "constant in both groups"}
    u = float(a[5])
    z = abs(u - n1 * n2 / 2)
    z = max(0.0, z - 0.5) / math.sqrt(variance)
    p = 2 * stats.norm.sf(z)
    note = ("asymptotic mann-whitney used for large, unbalanced groups"
            if min(n1, n2) <= 8 and n > 10_000 and tie_sum == 0 else None)
    return {**summary, "p": _p(p), "test": "mann-whitney", "note": note}


def _categorical(conn, table, column, a_where, b_where, params):
    col = f"CAST(src.{_q(column)} AS text)"
    samples = (f"SELECT {col} AS value, 'a' AS grp FROM {table} WHERE ({a_where}) "
               f"AND src.{_q(column)} IS NOT NULL UNION ALL "
               f"SELECT {col} AS value, 'b' AS grp FROM {table} WHERE ({b_where}) "
               f"AND src.{_q(column)} IS NOT NULL")
    result = conn.execute(text(
        f"WITH samples AS ({samples}), counts AS (SELECT value, grp, COUNT(*) AS n "
        "FROM samples GROUP BY value, grp), top AS (SELECT value, SUM(n) AS n "
        "FROM counts GROUP BY value ORDER BY SUM(n) DESC, value LIMIT "
        f"{CAT_TOP_N}), buckets AS (SELECT (top.value IS NULL) AS other_bucket, "
        "top.value, counts.grp, SUM(counts.n) AS n FROM counts "
        "LEFT JOIN top USING (value) GROUP BY 1, 2, 3) "
        "SELECT other_bucket, value, grp, n FROM buckets ORDER BY other_bucket, value, grp"),
        params).all()
    counts = {"a": {}, "b": {}}
    other_key = object()
    for is_other, value, group, n in result:
        counts[group][other_key if is_other else value] = int(n)
    na, nb = sum(counts["a"].values()), sum(counts["b"].values())
    cats = list(dict.fromkeys(other_key if is_other else value
                              for is_other, value, _, _ in result))
    def top_share(group, n):
        return [{"value": "Other (remaining categories)"
                 if value is other_key else value,
                 "pct": round(100 * count / n, 1)}
                for value, count in sorted(counts[group].items(),
                                           key=lambda item: item[1], reverse=True)[:3]
                if count and n]
    summary = {"a": {"n": na, "top": top_share("a", na)},
               "b": {"n": nb, "top": top_share("b", nb)}}
    if na < MIN_GROUP_N or nb < MIN_GROUP_N:
        return {**summary, "p": None, "note": f"group too small (n<{MIN_GROUP_N})"}
    if len(cats) < 2:
        return {**summary, "p": None, "note": "not enough categories"}
    table_counts = np.array([[counts["a"].get(c, 0) for c in cats],
                             [counts["b"].get(c, 0) for c in cats]])
    try:
        chi = stats.chi2_contingency(table_counts)
        note = (f"low expected counts (<{EXPECTED_MIN}) — chi-square approx."
                if (chi.expected_freq < EXPECTED_MIN).any() else None)
        return {**summary, "p": _p(chi.pvalue), "test": "chi-square", "note": note}
    except ValueError as e:
        return {**summary, "p": None, "note": str(e)[:80]}


def _f(value):
    if value is None:
        return None
    value = float(value)
    return round(value, 6) if math.isfinite(value) else None


def _p(value):
    if value is None or not math.isfinite(float(value)):
        return None
    value = float(value)
    return 0.0 if value == 0 else round(value, -int(math.floor(math.log10(abs(value)))) + 2)


def _benjamini_hochberg(pvals):
    indexes = [i for i, p in enumerate(pvals) if p is not None]
    qvals = [None] * len(pvals)
    m = len(indexes)
    previous = 1.0
    for rank, i in enumerate(reversed(sorted(indexes, key=lambda j: pvals[j])), 1):
        k = m - rank + 1
        previous = min(previous, pvals[i] * m / k)
        qvals[i] = _p(previous)
    return qvals


def compare(live_source, profiles, filters_a, filters_b, b_is_rest=False):
    columns = live_source["columns"]
    a_where, a_params = _where(filters_a, columns, "a")
    b_where, b_params = _where(filters_b, columns, "b")
    source_params = live_source.get("params", {})
    params = {**source_params, **a_params, **b_params}
    if b_is_rest:
        b_where = f"NOT COALESCE(({a_where}), FALSE)"
        params = {**source_params, **a_params}
    table = f"({live_source['sql']}) AS src"
    results = []
    with db.get_engine_for_resource(live_source["resource_id"]).begin() as conn:
        conn.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.exec_driver_sql(f"SET LOCAL statement_timeout = {TIMEOUT_MS}")
        a_n = int(conn.execute(text(f"SELECT COUNT(*) FROM {table} WHERE ({a_where})"),
                               {**source_params, **a_params}).scalar_one())
        b_n = int(conn.execute(text(f"SELECT COUNT(*) FROM {table} WHERE ({b_where})"),
                               params).scalar_one())
        if b_is_rest:
            overlap = 0
        else:
            overlap = int(conn.execute(text(
                f"SELECT COUNT(*) FROM {table} WHERE ({a_where}) AND ({b_where})"),
                params).scalar_one())
        for profile in profiles:
            kind = profile.get("filter_kind")
            name = profile.get("name")
            if name not in columns:
                continue
            pg_name = columns[name]
            if kind == "range":
                result = _numeric(conn, table, pg_name, a_where, b_where, params)
            elif kind == "categorical":
                result = _categorical(conn, table, pg_name, a_where, b_where, params)
            else:
                continue
            results.append({"column": name, "kind": kind, **result})
    qvals = _benjamini_hochberg([r.get("p") for r in results])
    for result, q in zip(results, qvals):
        result["q"] = q
    results.sort(key=lambda r: (r.get("p") is None,
                               r["p"] if r.get("p") is not None else 1.0))
    return {"a_n": a_n, "b_n": b_n, "n_overlap": overlap,
            "results": results, "scope": "database"}
