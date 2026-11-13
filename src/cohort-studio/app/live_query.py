import logging
import math
import os
import threading
import time
from decimal import Decimal

import pandas as pd
import sqlglot
from sqlglot import exp
from sql_utils import statement as text

import category_text
import chart_measures
import database as db
import filter_rules

logger = logging.getLogger(__name__)

TIMEOUT_MS = 15_000
# Above this many estimated rows an unfiltered open must not scan the whole table: totals come
# from the planner's estimate and charts are drawn from the first CHART_SAMPLE_ROWS rows.
LARGE_ROWS = 5_000_000
# A filter on an unindexed column of a very large table is one full scan. The default limit is
# too short for that, so large sources get a longer one. The app proxy has been seen to allow
# at least a minute, so stay under that.
LARGE_TIMEOUT_MS = int(os.environ.get("STUDIO_LARGE_QUERY_TIMEOUT_MS", "55000"))
CHART_SAMPLE_ROWS = 200_000
JOIN_PROFILE_BUDGET_S = 3.0
PAGE_SIZE_MAX = 1000
CATEGORICAL_VALUES_LIMIT = 50
BAR_TOP_N = 12
HIST_BINS = 24
SCATTER_SAMPLE = 2000
HEATMAP_LIMIT = 400
_NUMERIC = r"^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$"
_INTEGER_TYPE_OIDS = {20, 21, 23}
_INT64_MIN, _INT64_MAX = -(2 ** 63), 2 ** 63 - 1
ORDER_CACHE_TTL = 300
# Unfiltered histogram aggregates are cached at least this long (seconds);
# Refresh invalidates them along with everything else for the resource.
BASE_CACHE_TTL = 600
_FLOAT_TYPE_OIDS = {700, 701, 1700}
# bool, date, time, timestamp, timestamptz, interval, timetz
_NON_NUMERIC_TYPE_OIDS = {16, 1082, 1083, 1114, 1184, 1186, 1266}
_VALUE_KINDS = {16: "bool", 700: "float", 701: "float"}


def _q(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _numeric(col: str, type_oid: int | None = None) -> str:
    if type_oid in _INTEGER_TYPE_OIDS:
        return f"({col})::double precision"
    if type_oid in _FLOAT_TYPE_OIDS:
        return (f"CASE WHEN ({col})::text IN ('NaN', 'Infinity', '-Infinity') "
                f"THEN NULL ELSE ({col})::double precision END")
    value = f"TRIM(({col})::text)"
    return (f"CASE WHEN {value} ~ '{_NUMERIC}' "
            f"THEN ({value})::double precision END")


def _json_value(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Decimal) and not value.is_finite():
        return None
    return value


def _where(filters: list[dict], columns: dict[str, str],
           numeric_types: dict[str, int] | None = None):
    """WHERE clause for Explore filters, including AND/OR criteria groups."""
    return filter_rules.combine_named(
        filters, lambda flat, prefix: _where_flat(flat, columns, numeric_types, prefix))


def _where_flat(filters: list[dict], columns: dict[str, str],
                numeric_types: dict[str, int] | None = None, prefix: str = ""):
    numeric_types = numeric_types or {}
    clauses, params = [], {}
    for i, item in enumerate(filters):
        name = item.get("column")
        if name not in columns:
            raise ValueError(f"Unknown filter column: {name!r}.")
        col = _q(columns[name])
        kind = item.get("kind")
        integer = numeric_types.get(name) in _INTEGER_TYPE_OIDS
        if kind == "categorical" and item.get("values"):
            values = category_text.filter_values(item["values"], _VALUE_KINDS.get(numeric_types.get(name)))
            if numeric_types.get(name) == 16:
                values = [value.lower() for value in values]
            if numeric_types.get(name) in (700, 701):
                numbers = []
                for value in values:
                    try:
                        number = float(value)
                    except (TypeError, ValueError):
                        continue
                    numbers.append(number)
                if not numbers:
                    clauses.append("FALSE")
                    continue
                cast = "real" if numeric_types[name] == 700 else "double precision"
                keys = []
                for j, number in enumerate(numbers):
                    key = f"{prefix}f{i}_{j}"
                    keys.append(f"CAST(:{key} AS {cast})")
                    params[key] = number
                clauses.append(f"{col} IN ({', '.join(keys)})")
                continue
            ints = _as_ints(values) if integer else None
            keys = []
            for j, value in enumerate(values):
                key = f"{prefix}f{i}_{j}"
                keys.append(f":{key}")
                params[key] = ints[j] if ints is not None else value
            # Native comparison on integer columns keeps btree indexes usable.
            target = col if ints is not None else f"CAST({col} AS text)"
            clauses.append(f"{target} IN ({', '.join(keys)})")
        elif kind == "range" and filter_rules.is_active(item):
            lo, hi = filter_rules.range_bounds(item)
            if numeric_types.get(name) in _NON_NUMERIC_TYPE_OIDS:
                raise ValueError(f"Range filters require a numeric column: {name}")
            if integer:
                # Intersect with the bigint domain; an empty intersection
                # matches nothing rather than snapping to a boundary value.
                raw_lo, raw_hi = item.get("min"), item.get("max")
                exact = lambda v: isinstance(v, int) and not isinstance(v, bool)
                # JSON integers stay exact; float() would round 2**63-1 up to 2**63.
                lo_i = _INT64_MIN if lo is None else max(_INT64_MIN, raw_lo if exact(raw_lo) else math.ceil(lo))
                hi_i = _INT64_MAX if hi is None else min(_INT64_MAX, raw_hi if exact(raw_hi) else math.floor(hi))
                if lo_i > hi_i:
                    clauses.append("FALSE")
                    continue
                clauses.append(f"{col} BETWEEN :{prefix}f{i}_lo AND :{prefix}f{i}_hi")
                params[f"{prefix}f{i}_lo"], params[f"{prefix}f{i}_hi"] = lo_i, hi_i
                continue
            target = _numeric(col, numeric_types.get(name))
            if lo is not None:
                clauses.append(f"{target} >= :{prefix}f{i}_lo")
                params[f"{prefix}f{i}_lo"] = lo
            if hi is not None:
                clauses.append(f"{target} <= :{prefix}f{i}_hi")
                params[f"{prefix}f{i}_hi"] = hi
        elif kind == "date" and filter_rules.is_active(item):
            # Compare the column itself with date parameters (PostgreSQL widens a
            # date to a timestamp), so indexes on date/timestamp columns still apply.
            start, end = filter_rules.date_bounds(item)
            if start:
                clauses.append(f"{col} >= :{prefix}f{i}_start")
                params[f"{prefix}f{i}_start"] = start
            if end:
                clauses.append(f"{col} < :{prefix}f{i}_end")
                params[f"{prefix}f{i}_end"] = end
    return " AND ".join(clauses) if clauses else "TRUE", params


def _as_ints(values: list[str]) -> list[int] | None:
    """Integer values for a native IN list, or None if any value isn't an int64."""
    out = []
    for value in values:
        text_value = value.strip()
        if not text_value or not (text_value.lstrip("+-").isdigit()):
            return None
        number = int(text_value)
        if not _INT64_MIN <= number <= _INT64_MAX:
            return None
        out.append(number)
    return out


def _query(conn, live_source: dict, sql: str, params: dict):
    try:
        return conn.execute(text(sql), {**live_source.get("params", {}), **params})
    except Exception as exc:
        if "statement timeout" in str(exc) or "canceling statement" in str(exc):
            # Name the query that ran too long; the browser only sees a bare 504.
            logger.warning("Live query timed out after %d ms (%s): %.300s",
                           TIMEOUT_MS, live_source.get("resource_id"), " ".join(str(sql).split()))
        raise


def _estimated_rows(conn, live_source: dict) -> int | None:
    """Planner row estimate for the source; instant, no scan. None when unavailable."""
    savepoint = conn.begin_nested()
    try:
        plan = _query(conn, live_source,
                      f"EXPLAIN (FORMAT JSON) SELECT 1 FROM ({live_source['sql']}) AS live", {}).scalar()
        savepoint.commit()
        if isinstance(plan, str):
            import json
            plan = json.loads(plan)
        return int(plan[0]["Plan"]["Plan Rows"])
    except Exception:
        savepoint.rollback()
        return None


def _numeric_columns(conn, live_source: dict, names) -> dict[str, int]:
    selected = list(dict.fromkeys(name for name in names if name in live_source["columns"]))
    if not selected:
        return {}
    columns = live_source["columns"]
    projection = ", ".join(
        f"live.{_q(columns[name])} AS {_q(name)}" for name in selected)
    result = _query(conn, live_source,
                    f"SELECT {projection} FROM ({live_source['sql']}) AS live LIMIT 0", {})
    try:
        description = result.cursor.description
        # Every column's type OID; _numeric treats non-numeric OIDs as text.
        return {name: column.type_code for name, column in zip(selected, description)
                if getattr(column, "type_code", None) is not None}
    finally:
        result.close()


def _requested_order(live_source: dict) -> str | None:
    try:
        query = sqlglot.parse_one(live_source["sql"], read="postgres")
    except Exception:
        return None
    order = query.args.get("order")
    if order is None:
        return None
    columns = live_source["columns"]
    physical_names = set(columns.values())
    output_names = list(columns.values())
    for term in order.expressions:
        target = term.this
        if isinstance(target, exp.Literal) and not target.is_string:
            try:
                position = int(target.this)
            except (TypeError, ValueError):
                return None
            if not 1 <= position <= len(output_names):
                return None
            term.set("this", exp.column(output_names[position - 1], table="live"))
        for column in term.find_all(exp.Column):
            if column.name in columns:
                physical = columns[column.name]
            elif column.name in physical_names:
                physical = column.name
            else:
                return None
            column.set("this", exp.to_identifier(physical, quoted=True))
            column.set("table", exp.to_identifier("live", quoted=True))
            column.set("db", None)
            column.set("catalog", None)
    return ", ".join(term.sql(dialect="postgres") for term in order.expressions)


def _primary_key_order(conn, live_source: dict) -> str | None:
    try:
        query = sqlglot.parse_one(live_source["sql"], read="postgres")
    except Exception:
        return None
    if not isinstance(query, exp.Select) or any(query.args.get(key) for key in
            ("joins", "group", "distinct", "with_")):
        return None
    tables = list(query.find_all(exp.Table))
    if len(tables) != 1 or not isinstance(query.args.get("from_"), exp.From):
        return None
    table = tables[0]
    if query.args["from_"].this is not table or not table.db or table.catalog:
        return None
    projected = {}
    sole = query.expressions[0] if len(query.expressions) == 1 else None
    star = sole if isinstance(sole, exp.Star) else sole.this if isinstance(sole, exp.Column) and sole.is_star else None
    if isinstance(star, exp.Star):
        if any(star.args.values()) or isinstance(sole, exp.Column) and sole.table != table.alias_or_name:
            return None
        projected = {name: name for name in live_source["columns"].values()}
    else:
        for item in query.expressions:
            value = item.this if isinstance(item, exp.Alias) else item
            if not isinstance(value, exp.Column) or value.is_star:
                return None
            if value.table and value.table != table.alias_or_name:
                return None
            projected[value.name] = item.alias_or_name
    keys = conn.execute(text("""
        SELECT a.attname FROM pg_catalog.pg_index i
        JOIN pg_catalog.pg_class c ON c.oid = i.indrelid
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS k(attnum, position)
        JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid AND a.attnum = k.attnum
        WHERE n.nspname = :schema AND c.relname = :table AND i.indisprimary
          AND i.indisvalid AND k.position <= i.indnkeyatts
        ORDER BY k.position
        """), {"schema": table.db, "table": table.name}).scalars().all()
    outputs = set(live_source["columns"].values())
    if not keys:
        candidates = conn.execute(text("""
            SELECT a.attname FROM pg_catalog.pg_index i
            JOIN pg_catalog.pg_class c ON c.oid = i.indrelid
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_catalog.pg_class idx ON idx.oid = i.indexrelid
            JOIN pg_catalog.pg_am am ON am.oid = idx.relam
            JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid AND a.attnum = i.indkey[0]
            LEFT JOIN pg_catalog.pg_stats s ON s.schemaname = n.nspname
              AND s.tablename = c.relname AND s.attname = a.attname
            WHERE n.nspname = :schema AND c.relname = :table
              AND i.indisvalid AND i.indisready AND i.indpred IS NULL
              AND am.amname = 'btree' AND i.indkey[0] > 0 AND i.indoption[0] = 0
            ORDER BY CASE WHEN s.n_distinct < 0 THEN -s.n_distinct * c.reltuples
                          ELSE COALESCE(s.n_distinct, 0) END DESC, idx.relname
            """), {"schema": table.db, "table": table.name}).scalars().all()
        for key in candidates:
            if key in projected and projected[key] in outputs:
                return ", ".join([f'live.{_q(projected[key])}', *_tie_breakers(
                    conn, table, projected, outputs, skip=projected[key])])
        return None
    if any(key not in projected or projected[key] not in outputs for key in keys):
        return None
    return ", ".join(f"live.{_q(projected[key])}" for key in keys)


def _tie_breakers(conn, table, projected: dict, outputs: set, skip: str) -> list[str]:
    """Every projected column, natively where btree-orderable, else as text.

    Replaces to_jsonb(live)::text, which serialized whole rows for every
    sorted row (about 40x slower on the fixture) while giving the same total
    order over the projected values.
    """
    rows = conn.execute(text("""
        SELECT a.attname,
               EXISTS (SELECT 1 FROM pg_catalog.pg_opclass oc
                       JOIN pg_catalog.pg_am am ON am.oid = oc.opcmethod
                       WHERE am.amname = 'btree' AND oc.opcdefault
                         AND oc.opcintype = a.atttypid) AS orderable
        FROM pg_catalog.pg_attribute a
        JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = :schema AND c.relname = :table
          AND a.attnum > 0 AND NOT a.attisdropped
        ORDER BY a.attnum
        """), {"schema": table.db, "table": table.name}).all()
    terms = []
    for name, orderable in rows:
        out = projected.get(name)
        if out is None or out not in outputs or out == skip:
            continue
        terms.append(f"live.{_q(out)}" if orderable else f"(live.{_q(out)})::text")
    return terms


_order_cache: dict[tuple, tuple[float, str | None]] = {}
_order_lock = threading.Lock()


def _cached_primary_key_order(conn, live_source: dict) -> str | None:
    """Memoize the default order per source; it costs 3 catalog queries."""
    key = (live_source.get("resource_id"), live_source.get("sql"),
           tuple(sorted(live_source.get("columns", {}).items())))
    now = time.monotonic()
    with _order_lock:
        hit = _order_cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
    order = _primary_key_order(conn, live_source)
    with _order_lock:
        if len(_order_cache) > 256:
            _order_cache.clear()
        _order_cache[key] = (now + ORDER_CACHE_TTL, order)
    return order


class _ProfileBudgetExceeded(Exception):
    pass


def profile_columns(live_source: dict, profiles: list[dict], *, bounded_join: bool = False) -> list[dict]:
    import query_cancellation
    try:
        return _profile_columns(live_source, profiles, bounded_join=bounded_join)
    except Exception as exc:
        query_cancellation.check()
        if not bounded_join or (not isinstance(exc, _ProfileBudgetExceeded) and "statement timeout" not in str(exc)):
            raise
        return [{**profile, "profile_sampled": True} for profile in profiles]


def _profile_columns(live_source: dict, profiles: list[dict], *, bounded_join: bool) -> list[dict]:
    import query_cancellation
    table = f"({live_source['sql']}) AS live"
    columns = live_source["columns"]
    result = [dict(profile) for profile in profiles]
    deadline = time.monotonic() + JOIN_PROFILE_BUDGET_S if bounded_join else None
    def check_budget():
        query_cancellation.check()
        if deadline is not None and time.monotonic() >= deadline:
            raise _ProfileBudgetExceeded()
    engine = db.get_engine_for_resource(live_source["resource_id"])
    with engine.begin() as conn, query_cancellation.postgres_connection(conn):
        conn.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.exec_driver_sql("SET LOCAL search_path = pg_catalog")
        conn.exec_driver_sql("SET LOCAL TimeZone = 'UTC'")
        conn.exec_driver_sql(f"SET LOCAL statement_timeout = {min(TIMEOUT_MS, 2000) if bounded_join else TIMEOUT_MS}")
        dates = [entry for entry in result if entry.get("filter_kind") == "date"]
        if dates:
            parts = []
            for entry in dates:
                col = f"live.{_q(columns[entry['name']])}"
                parts += [f"MIN({col})::date", f"MAX({col})::date"]
            check_budget()
            savepoint = conn.begin_nested()
            try:
                values = _query(conn, live_source, f"SELECT {', '.join(parts)} FROM {table}", {}).one()
                savepoint.commit()
                for i, entry in enumerate(dates):
                    low, high = values[2 * i], values[2 * i + 1]
                    if low is not None and high is not None:
                        entry["min_date"], entry["max_date"] = low.isoformat(), high.isoformat()
            except Exception as exc:
                savepoint.rollback()
                query_cancellation.check()
                if bounded_join:
                    raise
                if "statement timeout" not in str(exc) and "canceling statement" not in str(exc):
                    raise
        ranges = [entry for entry in result if entry.get("filter_kind") == "range"]
        check_budget()
        numeric_columns = _numeric_columns(conn, live_source, [e["name"] for e in result
                                                               if e.get("filter_kind") in ("range", "categorical")])
        if ranges:
            # One scan for every range column instead of one scan each.
            parts = []
            for entry in ranges:
                numeric = _numeric(f"live.{_q(columns[entry['name']])}",
                                   numeric_columns.get(entry["name"]))
                parts += [f"MIN({numeric})", f"MAX({numeric})"]
            check_budget()
            savepoint = conn.begin_nested()
            try:
                values = _query(conn, live_source,
                                f"SELECT {', '.join(parts)} FROM {table}", {}).one()
                savepoint.commit()
            except Exception as exc:
                savepoint.rollback()
                query_cancellation.check()
                if bounded_join:
                    raise
                if "statement timeout" not in str(exc) and "canceling statement" not in str(exc):
                    raise
                # On a very large table the full-scan MIN/MAX can exceed the time limit. The
                # columns keep the min/max from the loaded sample instead of failing the open.
                logger.warning("Range profile timed out after %d ms for %s; "
                               "keeping sample bounds for %d column(s).",
                               TIMEOUT_MS, live_source.get("resource_id"), len(ranges))
                values = None
            for i, entry in enumerate(ranges if values is not None else ()):
                low, high = values[2 * i], values[2 * i + 1]
                if low is not None and high is not None:
                    entry["min"], entry["max"] = float(low), float(high)
        for entry in result:
            if entry.get("filter_kind") != "categorical":
                continue
            col = f"live.{_q(columns[entry['name']])}"
            check_budget()
            savepoint = conn.begin_nested()
            try:
                values = _query(conn, live_source,
                                f"SELECT CAST({col} AS text) AS value FROM {table} "
                                f"WHERE {col} IS NOT NULL GROUP BY 1 "
                                f"ORDER BY COUNT(*) DESC, 1 LIMIT {CATEGORICAL_VALUES_LIMIT}",
                                {}).scalars().all()
                savepoint.commit()
            except Exception as exc:
                savepoint.rollback()
                query_cancellation.check()
                if bounded_join:
                    raise
                if "statement timeout" not in str(exc) and "canceling statement" not in str(exc):
                    raise
                # A slow column keeps its loaded-sample values instead of failing the open.
                continue
            entry["values"] = [category_text.normalize_label(str(value), numeric_columns.get(entry["name"]))
                               for value in values]
    return result


def _chart(conn, live_source: dict, chart: dict, where: str,
           params: dict, columns: dict, numeric_types: dict[str, int],
           has_filters: bool, base_cache=None) -> dict:
    kind, x, y = chart.get("kind"), chart.get("x"), chart.get("y")
    if x not in columns or (y and y not in columns):
        raise ValueError("Unknown chart column.")
    table = f"({live_source['sql']}) AS live"
    qx = f"live.{_q(columns[x])}"
    qy = f"live.{_q(columns[y])}" if y else None
    source = live_source["sql"]
    if chart_measures.is_measured(chart) or kind == "box":
        dialect = chart_measures.Dialect(
            rel=table, col=lambda name: f"live.{_q(columns[name])}",
            number=lambda name: _numeric(f"live.{_q(columns[name])}", numeric_types.get(name)),
            text_type="text", named=True, where=where, where_params=params,
            run=lambda sql, values: _query(conn, live_source, sql, values).all(), postgres=True)
        return (chart_measures.sql_box if kind == "box" else chart_measures.sql_bar)(dialect, chart)
    if kind == "bar":
        integer = numeric_types.get(x) in _INTEGER_TYPE_OIDS
        # One statement: top-N groups with their filtered counts plus both totals
        # (window sums run before LIMIT, so they cover every group).
        selected_expr = (f"COUNT(*) FILTER (WHERE {where})" if has_filters else "COUNT(*)")
        group = qx if integer else f"CAST({qx} AS text)"
        rows = _query(conn, live_source,
                      f"SELECT CAST({qx} AS text), COUNT(*), {selected_expr}, "
                      f"SUM(COUNT(*)) OVER (), SUM({selected_expr}) OVER () "
                      f"FROM {table} WHERE {qx} IS NOT NULL GROUP BY {group} "
                      f"ORDER BY COUNT(*) DESC, CAST({qx} AS text) LIMIT {BAR_TOP_N}",
                      params if has_filters else {}).all()
        top = [(str(v), int(n)) for v, n, *_ in rows]
        selected = {str(v): int(sel) for v, _n, sel, *_ in rows}
        total = int(rows[0][3]) if rows else 0
        selected_total = int(rows[0][4]) if rows else 0
        try:
            top.sort(key=lambda v: float(v[0]))
        except ValueError:
            pass
        data = [{"category": v, "all": n, "selected": selected.get(v, 0)}
                for v, n in top]
        other_all = total - sum(n for _, n in top)
        other_selected = selected_total - sum(selected.values())
        if other_all:
            data.append({"category": "Other", "all": other_all,
                         "selected": other_selected})
        return {"kind": kind, "x": x, "data": data}
    if kind == "histogram":
        num = _numeric(qx, numeric_types.get(x))
        # The unfiltered part (bounds + full buckets) doesn't depend on
        # filters, so it is cached per source and column across filter changes.
        base = base_cache.get(("histogram", x)) if base_cache else None
        if base is None:
            mn, mx = _query(conn, live_source,
                            f"SELECT MIN({num}), MAX({num}) FROM {table}", {}).one()
            if mn is None or mx is None:
                base = {"empty": True}
            else:
                mn, mx = float(mn), float(mx)
                if mn == mx:
                    delta = abs(mn) * 0.05 or 0.5
                    low, high = mn - delta, mx + delta
                else:
                    low, high = mn, mx
                width = (high - low) / HIST_BINS
                bucket = f"LEAST({HIST_BINS - 1}, GREATEST(0, FLOOR(({num} - {low}) / {width})::int))"
                base = {"low": low, "width": width, "full": [[int(i), int(n)] for i, n in _query(
                    conn, live_source, f"SELECT {bucket}, COUNT(*) FROM {table} "
                    f"WHERE {num} IS NOT NULL GROUP BY 1", {}).all()]}
            if base_cache is not None:
                base_cache.put(("histogram", x), base)
        if base.get("empty"):
            return {"kind": kind, "x": x, "data": []}
        low, width = base["low"], base["width"]
        bucket = f"LEAST({HIST_BINS - 1}, GREATEST(0, FLOOR(({num} - {low}) / {width})::int))"
        full = {int(i): int(n) for i, n in base["full"]}
        selected = (full if not has_filters else {int(i): int(n) for i, n in _query(
            conn, live_source, f"SELECT {bucket}, COUNT(*) FROM {table} "
            f"WHERE ({where}) AND {num} IS NOT NULL GROUP BY 1", params).all()})
        return {"kind": kind, "x": x, "data": [
            {"lo": low + i * width, "hi": low + (i + 1) * width,
             "all": full.get(i, 0), "selected": selected.get(i, 0)}
            for i in range(HIST_BINS)]}
    if kind == "scatter" and y:
        nx, ny = _numeric(qx), _numeric(qy)
        rows = _query(conn, live_source,
                      f"SELECT {nx}, {ny} FROM {table} WHERE ({where}) "
                      f"AND {nx} IS NOT NULL AND {ny} IS NOT NULL "
                      f"ORDER BY random() LIMIT {SCATTER_SAMPLE}", params).all()
        return {"kind": kind, "x": x, "y": y,
                "data": [[float(a), float(b)] for a, b in rows],
                "sampled": True}
    if kind == "map" and y:
        nx, ny = _numeric(qx), _numeric(qy)
        rows = _query(conn, live_source,
                      f"SELECT {nx}, {ny} FROM {table} WHERE ({where}) "
                      f"AND {nx} BETWEEN -180 AND 180 AND {ny} BETWEEN -90 AND 90 "
                      f"ORDER BY random() LIMIT {SCATTER_SAMPLE}", params).all()
        return {"kind": kind, "x": x, "y": y,
                "data": [[float(a), float(b)] for a, b in rows], "sampled": True}
    if kind == "heatmap" and y:
        rows = _query(conn, live_source,
                      f"SELECT CAST({qx} AS text), CAST({qy} AS text), COUNT(*) "
                      f"FROM {table} WHERE ({where}) AND {qx} IS NOT NULL "
                      f"AND {qy} IS NOT NULL GROUP BY 1, 2 "
                      f"ORDER BY COUNT(*) DESC, 1, 2 LIMIT {HEATMAP_LIMIT + 1}", params).all()
        return {"kind": kind, "x": x, "y": y,
                "data": [[a, b, int(n)] for a, b, n in rows[:HEATMAP_LIMIT]],
                "sampled": len(rows) > HEATMAP_LIMIT}
    return {"kind": kind, "x": x, "data": []}


def _execute_query(live_source: dict, filters: list[dict], chart_specs: list[dict],
                   page: int, page_size: int,
                   entity_column: str | None = None, sort: dict | None = None,
                   summary: bool = True, rows: bool = True, base_cache=None) -> dict:
    columns = live_source["columns"]
    if entity_column is not None and entity_column not in columns:
        raise ValueError(f"Unknown entity column: {entity_column!r}.")
    if page < 0 or page_size < 1:
        raise ValueError("Page must be non-negative and page size must be positive.")
    page_size = min(int(page_size), PAGE_SIZE_MAX)
    page = int(page)
    select = ", ".join(
        f"live.{_q(pg_name)} AS {_q(logical)}"
        for logical, pg_name in columns.items())
    table = f"({live_source['sql']}) AS live"
    import query_cancellation
    engine = db.get_engine_for_resource(live_source["resource_id"])
    with engine.begin() as conn, query_cancellation.postgres_connection(conn):
        conn.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.exec_driver_sql("SET LOCAL search_path = pg_catalog")
        conn.exec_driver_sql("SET LOCAL TimeZone = 'UTC'")
        conn.exec_driver_sql(f"SET LOCAL statement_timeout = {TIMEOUT_MS}")
        order = ((_requested_order(live_source) or _cached_primary_key_order(conn, live_source)
                  or "to_jsonb(live)::text") if rows else "")
        if sort and rows:
            if sort.get("column") not in columns or sort.get("direction") not in ("asc", "desc"):
                raise ValueError("Invalid sort column or direction.")
            order = f"live.{_q(columns[sort['column']])} {sort['direction'].upper()} NULLS LAST, {order}"
        needed_numeric = [f["column"] for f in filter_rules.leaves(filters) if f.get("kind") in ("range", "categorical")]
        if summary:
            needed_numeric.extend(c["x"] for c in chart_specs if c.get("kind") in ("histogram", "bar", "box"))
            needed_numeric.extend(name for c in chart_specs for name in chart_measures.columns_used(c))
        numeric_types = _numeric_columns(conn, live_source, needed_numeric)
        where, params = _where(filters, columns, numeric_types)
        has_filters = where != "TRUE"
        out = {"scope": "database", "sampled": False}
        estimate = _estimated_rows(conn, live_source) if summary else None
        large = estimate is not None and estimate >= LARGE_ROWS
        if large:
            conn.exec_driver_sql(f"SET LOCAL statement_timeout = {LARGE_TIMEOUT_MS}")
        if summary and large:
            # Counting every row (and distinct entities) of a very large table cannot finish
            # inside the time limit. Show the planner's estimate for the total; only an
            # applied filter gets an exact count, which an index on the filtered column can serve.
            filtered = estimate
            if has_filters:
                filtered = int(_query(conn, live_source,
                                      f"SELECT COUNT(*) FROM {table} WHERE {where}", params).scalar_one())
            out.update(total=estimate, filtered=filtered, estimated=True)
            if entity_column is not None and has_filters:
                col = f"live.{_q(columns[entity_column])}"
                distinct = int(_query(conn, live_source,
                                      f"SELECT COUNT(DISTINCT {col}) FROM {table} WHERE {where}",
                                      params).scalar_one())
                out["entity"] = {"column": entity_column, "total": None,
                                 "filtered": distinct}
            chart_source = live_source
            if not has_filters:
                # An unfiltered chart over the whole table is a full scan per chart. Draw it from
                # a bounded slice and say so.
                chart_source = {**live_source,
                                "sql": f"SELECT * FROM ({live_source['sql']}) AS s "
                                       f"LIMIT {CHART_SAMPLE_ROWS}"}
            charts = []
            for chart in chart_specs:
                drawn = category_text.normalize_chart(
                    _chart(conn, chart_source, chart, where, params, columns, numeric_types,
                           has_filters, None if chart_source is not live_source else base_cache),
                    numeric_types)
                if chart_source is not live_source and isinstance(drawn, dict):
                    drawn["sampled"] = True
                charts.append(drawn)
            out["charts"] = charts
        elif summary:
            aggregates = ["COUNT(*)"]
            if has_filters:
                aggregates.append(f"COUNT(*) FILTER (WHERE {where})")
            if entity_column is not None:
                col = f"live.{_q(columns[entity_column])}"
                aggregates.append(f"COUNT(DISTINCT {col})")
                if has_filters:
                    aggregates.append(f"COUNT(DISTINCT {col}) FILTER (WHERE {where})")
            counts = _query(conn, live_source,
                            f"SELECT {', '.join(aggregates)} FROM {table}", params).one()
            total = int(counts[0])
            filtered = int(counts[1]) if has_filters else total
            out.update(total=total, filtered=filtered)
            if entity_column is not None:
                index = 2 if has_filters else 1
                entity_total = int(counts[index])
                entity_filtered = int(counts[index + 1]) if has_filters else entity_total
                out["entity"] = {"column": entity_column, "total": entity_total,
                                 "filtered": entity_filtered}
            out["charts"] = [category_text.normalize_chart(
                                 _chart(conn, live_source, chart, where, params, columns,
                                        numeric_types, has_filters, base_cache), numeric_types)
                             for chart in chart_specs]
        if rows:
            fetched = _query(conn, live_source,
                             f"SELECT {select} FROM {table} WHERE {where} "
                             f"ORDER BY {order} LIMIT :limit OFFSET :offset",
                             {**params, "limit": page_size, "offset": page * page_size}).all()
            out["rows"] = {"page": page, "page_size": page_size, "columns": list(columns),
                           "data": [[_json_value(value) for value in row] for row in fetched]}
    return out


class _BaseCache:
    """Unfiltered aggregates (histogram bounds and buckets) per source."""

    def __init__(self, query_cache, resource_id, live_source, generation, ttl):
        self.qc, self.resource_id, self.generation = query_cache, resource_id, generation
        self.source = live_source
        self.ttl = 0 if ttl <= 0 else max(ttl, BASE_CACHE_TTL)
        self.oldest = None          # as_of of the oldest base used in this result

    def _seen(self, as_of):
        if as_of and (self.oldest is None or as_of < self.oldest):
            self.oldest = as_of

    def _key(self, part):
        return "base:" + self.qc.make_key(
            self.resource_id, self.source["sql"], self.source["columns"], [], [list(part)],
            None, None, None, self.generation, self.source.get("params", {}))

    def get(self, part):
        hit = self.qc.cache.get(self._key(part), self.ttl)
        if not hit:
            return None
        self._seen(hit[1])
        return hit[0]

    def put(self, part, value):
        self._seen(self.qc.cache.put(self._key(part), self.resource_id, value,
                                     self.ttl, self.generation))


def query(live_source: dict, filters: list[dict], chart_specs: list[dict],
          page: int, page_size: int, entity_column: str | None = None,
          refresh: bool = False, sort: dict | None = None) -> dict:
    """Dashboard result for a live source, cached in two parts.

    The summary (counts, entity counts, charts) doesn't depend on page or
    sort, and the row page doesn't depend on charts or the entity column, so
    paging or re-sorting reruns only the row query, and changing charts
    reruns only the summary.
    """
    import query_cache

    ttl = query_cache._ttl()
    resource_id = live_source["resource_id"]
    if refresh:
        query_cache.invalidate_resource(resource_id)
    generation = query_cache.cache.generation(resource_id)
    common = (resource_id, live_source["sql"], live_source["columns"])
    params = live_source.get("params", {})
    summary_key = "summary:" + query_cache.make_key(
        *common, filters, chart_specs, None, None, entity_column, generation, params)
    rows_key = "rows:" + query_cache.make_key(
        *common, filters, [], page, page_size, None, generation, params, sort=sort)
    summary = rows = None
    as_of = []
    if not refresh and ttl > 0:
        for key, slot in ((summary_key, "summary"), (rows_key, "rows")):
            cached = query_cache.cache.get(key, ttl)
            if cached is not None:
                if slot == "summary":
                    summary = cached[0]
                else:
                    rows = cached[0]
                as_of.append(cached[1])
    hit = summary is not None and rows is not None
    if not hit:
        base_cache = _BaseCache(query_cache, resource_id, live_source, generation, ttl)
        fresh = _execute_query(
            live_source, filters, chart_specs, page, page_size, entity_column, sort=sort,
            summary=summary is None, rows=rows is None, base_cache=base_cache)
        if summary is None:
            summary = {k: v for k, v in fresh.items() if k != "rows"}
            if base_cache.oldest:
                # Charts may reuse older cached bases; keep their age with the summary.
                summary["_data_as_of"] = base_cache.oldest
            stamp = query_cache.cache.put(summary_key, resource_id, summary, ttl, generation)
            as_of.append(stamp)
        if rows is None:
            rows = {"rows": fresh["rows"]}
            stamp = query_cache.cache.put(rows_key, resource_id, rows, ttl, generation)
            as_of.append(stamp)
    stamps = [stamp for stamp in as_of if stamp]
    if summary.get("_data_as_of"):
        stamps.append(summary["_data_as_of"])
    if not stamps:
        from datetime import datetime, timezone
        stamps = [datetime.now(timezone.utc).isoformat()]
    value = {k: v for k, v in summary.items() if k != "_data_as_of"}
    value.update(rows)
    # Oldest part decides how fresh the combined result is.
    value["cache"] = {"hit": hit, "as_of": min(stamps), "ttl_seconds": ttl}
    return value


def fetch_frame(live_source: dict, filters: list[dict] | None = None,
                max_rows: int = 100_000) -> pd.DataFrame:
    filters = filters or []
    if max_rows < 0:
        raise ValueError("Row limit must be non-negative.")
    columns = live_source["columns"]
    select = ", ".join(
        f"live.{_q(pg_name)} AS {_q(logical)}"
        for logical, pg_name in columns.items())
    table = f"({live_source['sql']}) AS live"
    with db.get_engine_for_resource(live_source["resource_id"]).begin() as conn:
        conn.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.exec_driver_sql("SET LOCAL search_path = pg_catalog")
        conn.exec_driver_sql("SET LOCAL TimeZone = 'UTC'")
        conn.exec_driver_sql(f"SET LOCAL statement_timeout = {TIMEOUT_MS}")
        numeric_types = _numeric_columns(
            conn, live_source,
            [f["column"] for f in filter_rules.leaves(filters) if f.get("kind") in ("range", "categorical")])
        where, params = _where(filters, live_source["columns"], numeric_types)
        rows = _query(conn, live_source,
                      f"SELECT {select} FROM {table} WHERE {where} LIMIT :limit",
                      {**params, "limit": max_rows + 1}).all()
    if len(rows) > max_rows:
        raise ValueError(f"Filtered live join has more than {max_rows:,} rows; "
                         "use query paging or narrow the filters.")
    return pd.DataFrame.from_records(rows, columns=list(columns))
