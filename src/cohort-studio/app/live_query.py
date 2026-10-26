import math
from decimal import Decimal

import pandas as pd
import sqlglot
from sqlglot import exp
from sql_utils import statement as text

import database as db

TIMEOUT_MS = 15_000
PAGE_SIZE_MAX = 1000
CATEGORICAL_VALUES_LIMIT = 50
BAR_TOP_N = 12
HIST_BINS = 24
SCATTER_SAMPLE = 2000
HEATMAP_LIMIT = 400
_NUMERIC = r"^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$"
_INTEGER_TYPE_OIDS = {20, 21, 23}
_FLOAT_TYPE_OIDS = {700, 701, 1700}


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
    numeric_types = numeric_types or {}
    clauses, params = [], {}
    for i, item in enumerate(filters):
        name = item.get("column")
        if name not in columns:
            raise ValueError(f"Unknown filter column: {name!r}.")
        col = _q(columns[name])
        kind = item.get("kind")
        if kind == "categorical" and item.get("values"):
            values = [str(v) for v in item["values"]]
            keys = []
            for j, value in enumerate(values):
                key = f"f{i}_{j}"
                keys.append(f":{key}")
                params[key] = value
            clauses.append(f"CAST({col} AS text) IN ({', '.join(keys)})")
        elif kind == "range" and item.get("min") is not None and item.get("max") is not None:
            lo, hi = float(item["min"]), float(item["max"])
            if not math.isfinite(lo) or not math.isfinite(hi):
                raise ValueError("Range filter values must be finite.")
            clauses.append(f"{_numeric(col, numeric_types.get(name))} BETWEEN :f{i}_lo AND :f{i}_hi")
            params[f"f{i}_lo"] = lo
            params[f"f{i}_hi"] = hi
    return " AND ".join(clauses) if clauses else "TRUE", params


def _query(conn, live_source: dict, sql: str, params: dict):
    return conn.execute(text(sql), {**live_source.get("params", {}), **params})


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
        return {name: column.type_code for name, column in zip(selected, description)
                if getattr(column, "type_code", None) in
                _INTEGER_TYPE_OIDS | _FLOAT_TYPE_OIDS}
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
    if not keys or any(key not in projected or projected[key] not in outputs for key in keys):
        return None
    return ", ".join(f"live.{_q(projected[key])}" for key in keys)


def profile_columns(live_source: dict, profiles: list[dict]) -> list[dict]:
    table = f"({live_source['sql']}) AS live"
    columns = live_source["columns"]
    result = []
    with db.get_engine_for_resource(live_source["resource_id"]).begin() as conn:
        conn.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.exec_driver_sql("SET LOCAL search_path = pg_catalog")
        conn.exec_driver_sql(f"SET LOCAL statement_timeout = {TIMEOUT_MS}")
        numeric_columns = _numeric_columns(
            conn, live_source,
            [p["name"] for p in profiles if p.get("filter_kind") == "range"])
        for profile in profiles:
            entry = dict(profile)
            name = entry["name"]
            col = f"live.{_q(columns[name])}"
            if entry.get("filter_kind") == "range":
                numeric = _numeric(col, numeric_columns.get(name))
                low, high = _query(conn, live_source,
                                   f"SELECT MIN({numeric}), MAX({numeric}) FROM {table}",
                                   {}).one()
                if low is not None and high is not None:
                    entry["min"], entry["max"] = float(low), float(high)
            elif entry.get("filter_kind") == "categorical":
                values = _query(conn, live_source,
                                f"SELECT CAST({col} AS text) AS value FROM {table} "
                                f"WHERE {col} IS NOT NULL GROUP BY 1 "
                                f"ORDER BY COUNT(*) DESC, 1 LIMIT {CATEGORICAL_VALUES_LIMIT}",
                                {}).scalars().all()
                entry["values"] = [str(value) for value in values]
            result.append(entry)
    return result


def _chart(conn, live_source: dict, chart: dict, where: str,
           params: dict, columns: dict, numeric_types: dict[str, int],
           has_filters: bool) -> dict:
    kind, x, y = chart.get("kind"), chart.get("x"), chart.get("y")
    if x not in columns or (y and y not in columns):
        raise ValueError("Unknown chart column.")
    table = f"({live_source['sql']}) AS live"
    qx = f"live.{_q(columns[x])}"
    qy = f"live.{_q(columns[y])}" if y else None
    source = live_source["sql"]
    if kind == "bar":
        all_rows = _query(conn, live_source,
                          f"SELECT CAST({qx} AS text), COUNT(*) FROM {table} "
                          f"WHERE {qx} IS NOT NULL GROUP BY 1 "
                          f"ORDER BY COUNT(*) DESC, 1 LIMIT {BAR_TOP_N}", {})
        top = [(str(v), int(n)) for v, n in all_rows]
        selected = {}
        if top and has_filters:
            cat_params = dict(params)
            keys = []
            for i, (value, _) in enumerate(top):
                key = f"c{i}"
                keys.append(f":{key}")
                cat_params[key] = value
            rows = _query(conn, live_source,
                          f"SELECT CAST({qx} AS text), COUNT(*) FROM {table} "
                          f"WHERE ({where}) AND CAST({qx} AS text) IN ({', '.join(keys)}) "
                          "GROUP BY 1", cat_params)
            selected = {str(v): int(n) for v, n in rows}
        total = int(_query(conn, live_source,
                           f"SELECT COUNT(*) FROM {table} WHERE {qx} IS NOT NULL", {}).scalar_one())
        selected_total = (int(_query(conn, live_source,
                                     f"SELECT COUNT(*) FROM {table} "
                                     f"WHERE ({where}) AND {qx} IS NOT NULL", params).scalar_one())
                          if has_filters else total)
        if not has_filters:
            selected = dict(top)
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
        mn, mx = _query(conn, live_source,
                        f"SELECT MIN({num}), MAX({num}) FROM {table}", {}).one()
        if mn is None or mx is None:
            return {"kind": kind, "x": x, "data": []}
        mn, mx = float(mn), float(mx)
        if mn == mx:
            delta = abs(mn) * 0.05 or 0.5
            low, high = mn - delta, mx + delta
        else:
            low, high = mn, mx
        width = (high - low) / HIST_BINS
        bucket = f"LEAST({HIST_BINS - 1}, GREATEST(0, FLOOR(({num} - {low}) / {width})::int))"
        full = {int(i): int(n) for i, n in _query(
            conn, live_source, f"SELECT {bucket}, COUNT(*) FROM {table} "
            f"WHERE {num} IS NOT NULL GROUP BY 1", {}).all()}
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
    if kind == "heatmap" and y:
        rows = _query(conn, live_source,
                      f"SELECT CAST({qx} AS text), CAST({qy} AS text), COUNT(*) "
                      f"FROM {table} WHERE ({where}) AND {qx} IS NOT NULL "
                      f"AND {qy} IS NOT NULL GROUP BY 1, 2 "
                      f"ORDER BY COUNT(*) DESC, 1, 2 LIMIT {HEATMAP_LIMIT}", params).all()
        return {"kind": kind, "x": x, "y": y,
                "data": [[a, b, int(n)] for a, b, n in rows],
                "sampled": len(rows) == HEATMAP_LIMIT}
    return {"kind": kind, "x": x, "data": []}


def _execute_query(live_source: dict, filters: list[dict], chart_specs: list[dict],
                   page: int, page_size: int,
                   entity_column: str | None = None) -> dict:
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
    with db.get_engine_for_resource(live_source["resource_id"]).begin() as conn:
        conn.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.exec_driver_sql("SET LOCAL search_path = pg_catalog")
        conn.exec_driver_sql(f"SET LOCAL statement_timeout = {TIMEOUT_MS}")
        order = (_requested_order(live_source) or _primary_key_order(conn, live_source)
                 or "to_jsonb(live)::text")
        needed_numeric = [f["column"] for f in filters if f.get("kind") == "range"]
        needed_numeric.extend(c["x"] for c in chart_specs if c.get("kind") == "histogram")
        numeric_types = _numeric_columns(conn, live_source, needed_numeric)
        where, params = _where(filters, columns, numeric_types)
        total = int(_query(conn, live_source,
                           f"SELECT COUNT(*) FROM {table}", {}).scalar_one())
        has_filters = where != "TRUE"
        filtered = (int(_query(conn, live_source,
                               f"SELECT COUNT(*) FROM {table} WHERE {where}", params).scalar_one())
                    if has_filters else total)
        charts = [_chart(conn, live_source, chart, where, params, columns,
                         numeric_types, has_filters)
                  for chart in chart_specs]
        rows = _query(conn, live_source,
                      f"SELECT {select} FROM {table} WHERE {where} "
                      f"ORDER BY {order} LIMIT :limit OFFSET :offset",
                      {**params, "limit": page_size, "offset": page * page_size}).all()
        names = list(columns)
        row_data = [[_json_value(value) for value in row] for row in rows]
        entity = None
        if entity_column is not None:
            col = f"live.{_q(columns[entity_column])}"
            entity_total = int(_query(conn, live_source,
                                      f"SELECT COUNT(DISTINCT {col}) FROM {table}",
                                      {}).scalar_one())
            entity_filtered = int(_query(conn, live_source,
                                         f"SELECT COUNT(DISTINCT {col}) FROM {table} "
                                         f"WHERE {where}", params).scalar_one())
            entity = {"column": entity_column, "total": entity_total,
                      "filtered": entity_filtered}
    return {"total": total, "filtered": filtered, "charts": charts,
            "rows": {"page": page, "page_size": page_size,
                     "columns": names, "data": row_data},
            "scope": "database", "sampled": False,
            **({"entity": entity} if entity is not None else {})}


def query(live_source: dict, filters: list[dict], chart_specs: list[dict],
          page: int, page_size: int, entity_column: str | None = None,
          refresh: bool = False) -> dict:
    import query_cache

    ttl = query_cache._ttl()
    resource_id = live_source["resource_id"]
    if refresh:
        query_cache.invalidate_resource(resource_id)
    generation = query_cache.cache.generation(resource_id)
    key = query_cache.make_key(resource_id, live_source["sql"],
                               live_source["columns"], filters, chart_specs,
                               page, page_size, entity_column, generation, live_source.get("params", {}))
    if not refresh and ttl > 0:
        cached = query_cache.cache.get(key, ttl)
        if cached is not None:
            value, as_of = cached
            value["cache"] = {"hit": True, "as_of": as_of,
                              "ttl_seconds": ttl}
            return value
    value = _execute_query(live_source, filters, chart_specs,
                           page, page_size, entity_column)
    as_of = query_cache.cache.put(key, resource_id, value, ttl, generation)
    if as_of is None:
        from datetime import datetime, timezone
        as_of = datetime.now(timezone.utc).isoformat()
    value["cache"] = {"hit": False, "as_of": as_of,
                      "ttl_seconds": ttl}
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
        conn.exec_driver_sql(f"SET LOCAL statement_timeout = {TIMEOUT_MS}")
        numeric_types = _numeric_columns(
            conn, live_source,
            [f["column"] for f in filters if f.get("kind") == "range"])
        where, params = _where(filters, live_source["columns"], numeric_types)
        rows = _query(conn, live_source,
                      f"SELECT {select} FROM {table} WHERE {where} LIMIT :limit",
                      {**params, "limit": max_rows + 1}).all()
    if len(rows) > max_rows:
        raise ValueError(f"Filtered live join has more than {max_rows:,} rows; "
                         "use query paging or narrow the filters.")
    return pd.DataFrame.from_records(rows, columns=list(columns))
