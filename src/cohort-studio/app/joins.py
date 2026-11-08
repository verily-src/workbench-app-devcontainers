import datetime
import execution
from decimal import Decimal
import query_cancellation
import hashlib
import re

import duckdb
import pandas as pd
from sql_utils import statement as text

import datasets
import database as db
import queries

HOWS = {"inner": "INNER JOIN", "left": "LEFT JOIN", "right": "RIGHT JOIN",
        "full": "FULL OUTER JOIN", "semi": "SEMI JOIN", "anti": "ANTI JOIN"}

HOW_ALIASES = {"outer": "full"}
OPS = ("=", "!=", "<", "<=", ">", ">=")
MAX_STEPS = 6
PREVIEW_ROWS = 20
ARROW = " → "
SUGGEST_SAMPLE = 5000

FANOUT_RATIO = 2.0
PG_SCHEMA = "public"
PG_IDENT_BYTES = 63
PREVIEW_TIMEOUT_MS = 0
RUN_TIMEOUT_MS = 0
_NO_PARAMS = {"no_parameters": True}

class JoinTimeout(RuntimeError):
    pass

class JoinEngineError(RuntimeError):
    pass

def _q(ident: str) -> str:
    return '"' + str(ident).replace('"', '""') + '"'

_KIND_SAMPLE = 200


def _kind(series: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(series):
        return "bool"
    if pd.api.types.is_numeric_dtype(series):
        return "number"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "time"
    if series.dtype == object:
        # Rows fetched from PostgreSQL keep date/datetime and Decimal objects
        # in object columns; classify them by value, not as text, so joins
        # compare dates and numerics natively instead of as strings.
        sample = series.dropna().head(_KIND_SAMPLE)
        if not len(sample):
            # No values loaded (e.g. an all-NULL preview of a numeric or date
            # column): the type is unknown, not text.
            return "unknown"
        if len(sample):
            values = list(sample)
            if all(isinstance(v, (bool,)) for v in values):
                return "bool"
            if all(isinstance(v, (datetime.date, datetime.datetime, pd.Timestamp)) for v in values):
                return "time"
            if all(isinstance(v, (int, float, Decimal)) and not isinstance(v, bool) for v in values):
                return "number"
    return "text"

def aurora_origin(resource_id: str, table: str) -> dict:

    return {"kind": "aurora", "resource_id": resource_id,
            "schema": PG_SCHEMA, "table": table}

def default_alias(source: str) -> str:
    stem = str(source).rstrip("/").split("/")[-1].strip()
    stem = re.sub(r"\.(parquet|csv|tsv|txt|json|ndjson)(\.gz)?$", "", stem, flags=re.I)
    return stem or "joined"

def _output_name(alias: str, col: str, taken: set[str]) -> str:
    name, n = f"{alias}{ARROW}{col}", 2
    while name in taken:
        name, n = f"{alias}{ARROW}{col} ({n})", n + 1
    taken.add(name)
    return name

def _pg_name(name: str, used: set[str]) -> str:

    raw = name.encode()
    if len(raw) <= PG_IDENT_BYTES and name not in used:
        used.add(name)
        return name
    digest, n = hashlib.sha1(raw).hexdigest()[:8], 1
    while True:
        suffix = f"_{digest}" + (str(n) if n > 1 else "")
        candidate = raw[:PG_IDENT_BYTES - len(suffix)].decode("utf-8", "ignore") + suffix
        if candidate not in used:
            used.add(candidate)
            return candidate
        n += 1

def _check_condition(cond: dict, left: dict[str, str], right: dict[str, str],
                     step_no: int) -> tuple[str | None, str | None, dict | None]:

    lcol, rcol, op = cond.get("left"), cond.get("right"), cond.get("op", "=")
    if op not in OPS:
        return f"Step {step_no}: operator must be one of {', '.join(OPS)}.", None, None
    if lcol not in left:
        return f"Step {step_no}: {lcol!r} is not a column of the left side.", None, None
    if rcol not in right:
        return f"Step {step_no}: {rcol!r} is not a column of the joined table.", None, None
    lk, rk = left[lcol], right[rcol]
    checked = {"left": lcol, "op": op, "right": rcol, "kinds": (lk, rk),
               "cast": lk != rk}
    if "unknown" in (lk, rk):
        # Can't tell from the loaded rows (even when both sides are unknown):
        # compare equality as text, as before, and let the engine compare
        # other operators natively.
        checked["cast"] = op in ("=", "!=")
        return None, None, checked
    if lk == rk:
        return None, None, checked
    if op not in ("=", "!="):
        return (f"Step {step_no}: can't compare {lcol!r} ({lk}) "
                f"{op} {rcol!r} ({rk})."), None, None
    return None, f"{lcol} ({lk}) and {rcol} ({rk}) compared as text", checked

FILTER_OPS = ("=", "!=", "<", "<=", ">", ">=", "in", "not in",
              "is null", "is not null", "contains")
MAX_FILTERS = 12
MAX_FILTER_VALUES = 100
_ORDERED_OPS = ("<", "<=", ">", ">=")
_NULL_OPS = ("is null", "is not null")
# ILIKE escape character for "contains". Not a backslash: literal rendering of
# copyable SQL must not depend on standard_conforming_strings.
LIKE_ESCAPE = "!"
_INT_TEXT = re.compile(r"[+-]?\d+")
_TRUE, _FALSE = {"true", "t", "yes", "1"}, {"false", "f", "no", "0"}


def _typed_value(value, kind: str, where: str, column: str):
    """`value` as a bound parameter for a `kind` column, or raise ValueError."""
    if isinstance(value, list):
        raise ValueError(f"{where}: {column!r} takes one value; use 'in' for a list.")
    if kind == "number":
        if isinstance(value, bool):
            raise ValueError(f"{where}: {column!r} is a number column; {value!r} is not a number.")
        if isinstance(value, (int, float)):
            number = value
        else:
            raw = str(value).strip().replace(",", "")
            try:
                number = int(raw) if _INT_TEXT.fullmatch(raw) else float(raw)
            except ValueError:
                raise ValueError(f"{where}: {column!r} is a number column; "
                                 f"{value!r} is not a number.") from None
        if isinstance(number, float) and (number != number or number in (float("inf"), float("-inf"))):
            raise ValueError(f"{where}: {column!r} needs a finite number.")
        return number
    if kind == "bool":
        if isinstance(value, bool):
            return value
        raw = str(value).strip().lower()
        if raw in _TRUE:
            return True
        if raw in _FALSE:
            return False
        raise ValueError(f"{where}: {column!r} is a true/false column; {value!r} is not true or false.")
    if kind == "time":
        if isinstance(value, (bool, int, float)):
            raise ValueError(f"{where}: {column!r} is a date/time column; "
                             f"use a date like 2024-01-31, not {value!r}.")
        raw = str(value).strip()
        try:
            if len(raw) == 10:
                return datetime.date.fromisoformat(raw)
            return datetime.datetime.fromisoformat(raw)
        except ValueError:
            raise ValueError(f"{where}: {column!r} is a date/time column; "
                             f"{value!r} is not a date like 2024-01-31.") from None
    if isinstance(value, bool):
        raise ValueError(f"{where}: {column!r} is a text column; {value!r} is not text.")
    return str(value)


def _ref_value(value):
    """JSON form of a typed filter value, for saved join recipes."""
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return value


def _check_filter(raw: dict, kinds: dict[str, str], where: str) -> dict:
    """Validate one {column, op, value} filter against the table's column kinds."""
    column, op, value = raw.get("column"), raw.get("op", "="), raw.get("value")
    if op not in FILTER_OPS:
        raise ValueError(f"{where}: operator must be one of {', '.join(FILTER_OPS)}.")
    if not column or column not in kinds:
        raise ValueError(f"{where}: {column!r} is not a column of this table.")
    kind = kinds[column]
    text = kind in ("text", "unknown")
    if op in _NULL_OPS:
        values = []
    elif op == "contains":
        if isinstance(value, (list, bool)) or value is None or str(value) == "":
            raise ValueError(f"{where}: 'contains' needs some text to look for in {column!r}.")
        needle = str(value)
        for ch in (LIKE_ESCAPE, "%", "_"):
            needle = needle.replace(ch, LIKE_ESCAPE + ch)
        values, text = [f"%{needle}%"], True
    elif op in ("in", "not in"):
        items = value if isinstance(value, list) else [value] if value not in (None, "") else []
        if not items:
            raise ValueError(f"{where}: '{op}' needs at least one value for {column!r}.")
        if len(items) > MAX_FILTER_VALUES:
            raise ValueError(f"{where}: at most {MAX_FILTER_VALUES} values in one filter.")
        values = [_typed_value(v, kind, where, column) for v in items]
    else:
        if value is None or (isinstance(value, str) and not value.strip() and kind != "text"):
            raise ValueError(f"{where}: enter a value for {column!r}.")
        if op in _ORDERED_OPS and kind == "bool":
            raise ValueError(f"{where}: {column!r} is true/false; use = or !=.")
        values = [_typed_value(value, kind, where, column)]
    ref = {"column": column, "op": op}
    if op in ("in", "not in"):
        ref["value"] = [_ref_value(v) for v in values]
    elif op == "contains":
        ref["value"] = str(value)
    elif values:
        ref["value"] = _ref_value(values[0])
    return {"column": column, "op": op, "kind": kind, "values": values,
            "text": text, "ref": ref}


def _check_filters(raw: list | None, kinds: dict[str, str],
                   label: str) -> tuple[list[dict], list[dict], list[str]]:
    """(checked filters, per-filter {problem}, errors) for one join input."""
    checked, checks, errors = [], [], []
    raw = list(raw or [])
    if len(raw) > MAX_FILTERS:
        errors.append(f"{label}: at most {MAX_FILTERS} filters per table.")
    for i, item in enumerate(raw[:MAX_FILTERS], start=1):
        try:
            checked.append(_check_filter(dict(item), kinds, f"{label} filter {i}"))
            checks.append({"problem": None})
        except ValueError as e:
            checks.append({"problem": str(e)})
            errors.append(str(e))
    return checked, checks, errors


def _filter_where(filters: list[dict], col_ref, prefix: str,
                  pg: bool = True) -> tuple[str, dict]:
    """AND-ed predicate for `filters` with bound placeholders, and its params.

    Values are never interpolated: each becomes its own named parameter
    (`:name` for PostgreSQL, `$name` for DuckDB).
    """
    ph = (lambda n: f":{n}") if pg else (lambda n: f"${n}")
    clauses, params = [], {}
    for i, f in enumerate(filters):
        ref = col_ref(f["column"])
        if f["text"]:
            ref = f"CAST({ref} AS {'TEXT' if pg else 'VARCHAR'})"
        names = [f"{prefix}_{i}_{j}" for j in range(len(f["values"]))]
        params.update(zip(names, f["values"]))
        op = f["op"]
        if op in _NULL_OPS:
            clauses.append(f"{ref} {op.upper()}")
        elif op == "contains":
            clauses.append(f"{ref} ILIKE {ph(names[0])} ESCAPE '{LIKE_ESCAPE}'")
        elif op in ("in", "not in"):
            clauses.append(f"{ref} {op.upper()} ({', '.join(ph(n) for n in names)})")
        else:
            clauses.append(f"{ref} {op} {ph(names[0])}")
    return " AND ".join(clauses), params


def _filter_prefix(step_no: int, p: dict | None = None) -> str:
    ns = (p or {}).get("filter_ns", "jf")
    return f"{ns}_base" if step_no == 0 else f"{ns}_s{step_no}"


def _filter_namespace(inputs: list[dict], filters: list[list[dict]]) -> str:
    """Parameter prefix for this join's filters, distinct per join.

    An input can itself be a filtered join whose live SQL binds its own filter
    parameters, and two such inputs may sit side by side. A digest of the
    inputs and filter values keeps every join's names apart; identical joins
    get identical names (and values), which merge without conflict.
    """
    import json as _json
    content = [[ds.get("source"), (ds.get("live_source") or {}).get("sql"),
                ds.get("origin")] for ds in inputs]
    content.append([[f["ref"] for f in group] for group in filters])
    digest = hashlib.sha1(_json.dumps(content, default=str, sort_keys=True).encode()).hexdigest()
    return f"jf{digest[:8]}"


def _filtered_rel(rel: str, filters: list[dict], prefix: str, pg: bool,
                  names: dict[str, str] | None = None) -> tuple[str, dict]:
    """`rel` restricted by `filters` as a derived table, and the params it binds."""
    if not filters:
        return rel, {}
    get = (names or {}).get
    where, params = _filter_where(filters, lambda c: f"filter_input.{_q(get(c, c))}",
                                  prefix, pg)
    return f"(SELECT * FROM {rel} AS filter_input WHERE {where})", params


def _filter_params(p: dict, pg: bool = True) -> dict:
    params = {}
    inputs = [(0, p.get("base_filters") or [])] + [(s["no"], s.get("filters") or [])
                                                   for s in p["steps"]]
    for no, filters in inputs:
        params.update(_filter_where(filters, lambda c: c, _filter_prefix(no, p), pg)[1])
    return params


def filtered_live(live: dict, filters: list[dict], prefix: str) -> dict:
    """A live source whose SQL already applies `filters` (pushdown for staging
    and size estimates). Compiled sources keep their compiler trust."""
    if not filters:
        return live
    names = live.get("columns") or {}
    where, params = _filter_where(
        filters, lambda c: f"filter_input.{_q(names.get(c, c))}", prefix, True)
    clash = {k for k in params if k in (live.get("params") or {}) and live["params"][k] != params[k]}
    if clash:
        raise ValueError("Filter parameters clash with the source's parameters.")
    patch = {"sql": f"SELECT * FROM ({live['sql']}) AS filter_input WHERE {where}",
             "params": {**(live.get("params") or {}), **params}}
    if hasattr(live, "with_metadata"):
        # Compiled sources keep any estimate of the unfiltered query (an upper bound).
        return live.with_metadata(**patch)
    out = {**live, **patch}
    out.pop("estimated_bytes", None)
    return out


def _plan_step(step: dict, left: dict[str, str], right_ds: dict,
               step_no: int) -> dict:
    right = right_ds["df"]
    rkinds = {c: _kind(right[c]) for c in right.columns}
    errors, problems, checks, conds, notes = [], [], [], [], []
    how = HOW_ALIASES.get(step.get("how", "left"), step.get("how", "left"))
    if how not in HOWS:
        problems.append(f"Join type must be one of {', '.join(HOWS)}.")
        errors += problems
        how = "left"
    raw = step.get("conditions") or []
    if not raw:
        problems.append(f"Step {step_no}: add at least one join condition.")
        errors.append(problems[-1])
    for cond in raw:
        problem, note, checked = _check_condition(cond, left, rkinds, step_no)
        checks.append({"problem": problem, "note": note})
        if problem:
            errors.append(problem)
        if checked:
            conds.append(checked)
        if note:
            notes.append(note)
    cols, out = [], dict(left)
    if how not in ("semi", "anti"):
        wanted = step.get("columns")
        picked = list(right.columns) if wanted is None else list(wanted)
        unknown = [c for c in picked if c not in rkinds]
        if unknown:
            problems.append(f"Step {step_no}: unknown column(s) "
                            f"{', '.join(map(repr, unknown))}.")
            errors.append(problems[-1])
        alias = (step.get("alias") or "").strip() or "joined"
        taken = set(left)
        for c in picked:
            if c in rkinds:
                name = _output_name(alias, c, taken)
                cols.append((c, name))
                out[name] = rkinds[c]
    filters, filter_checks, filter_errors = _check_filters(
        step.get("filters"), rkinds, f"Step {step_no}")
    errors += filter_errors
    if conds and not any(c["op"] == "=" for c in conds):
        notes.append("no equality condition: every row can match many rows, "
                     "close to a cross join; add an = key if possible")
    merged = _merged_keys({"how": how, "conds": conds})
    if merged:
        notes.append(f"{how} join keeps {', '.join(sorted(merged))} from the joined table "
                     "for rows without a match")
    return {"no": step_no, "how": how, "ds": right_ds, "left": list(left),
            "out": out, "conds": conds, "cols": cols, "notes": notes,
            "checks": checks, "problems": problems, "errors": errors,
            "filters": filters, "filter_checks": filter_checks,
            "alias": (step.get("alias") or "").strip() or "joined"}

def plan(base_id: str, steps: list[dict], base_filters: list | None = None) -> dict:

    problems = []
    if not steps:
        problems.append("Add at least one join step.")
    if len(steps) > MAX_STEPS:
        problems.append(f"At most {MAX_STEPS} joins in one pipeline.")
    base = datasets.get(base_id)
    left = {c: _kind(base["df"][c]) for c in base["df"].columns}
    filters, filter_checks, filter_errors = _check_filters(base_filters, left, "Start table")
    planned = []
    for i, step in enumerate(steps[:MAX_STEPS], start=1):
        p = _plan_step(step, left, datasets.get(step.get("right_id", "")), i)
        planned.append(p)
        left = p["out"]
    out = {"base": base, "steps": planned, "problems": problems,
           "base_filters": filters, "base_filter_checks": filter_checks,
           "base_errors": filter_errors, "columns": list(left)}
    out["filter_ns"] = _filter_namespace([base] + [s["ds"] for s in planned],
                                         [filters] + [s["filters"] for s in planned])
    out["engine"], out["engine_reason"] = _engine(out)
    return out

def _first_error(p: dict) -> str | None:
    return next(iter(p["problems"] + p.get("base_errors", [])
                     + [e for s in p["steps"] for e in s["errors"]]), None)

def _engine(p: dict) -> tuple[str, str]:

    inputs = [p["base"]] + [s["ds"] for s in p["steps"]]
    origins = [({"kind": "aurora", "resource_id": ds["live_source"]["resource_id"]}
                if ds.get("live_source") else ds.get("origin") or {})
               for ds in inputs]
    if any(o.get("kind") != "aurora" for o in origins):
        return "duckdb", "Not every table was loaded straight from Aurora."
    if len({o["resource_id"] for o in origins}) > 1:
        return "duckdb", "The tables are in different Aurora databases."
    if any(s["how"] == "full" and any(c["op"] != "=" for c in s["conds"])
           for s in p["steps"]):
        return "duckdb", "Postgres runs full joins on = conditions only."
    return "aurora", f"All tables are in Aurora database {origins[0]['resource_id']}."

def _bound_params(p: dict) -> dict:
    params = {}
    for ds in [p["base"]] + [step["ds"] for step in p["steps"]]:
        for key, value in (ds.get("live_source") or {}).get("params", {}).items():
            if key in params and params[key] != value:
                raise ValueError("Conflicting bound parameters in joined sources.")
            params[key] = value
    for key, value in _filter_params(p).items():
        if key in params and params[key] != value:
            raise ValueError("Conflicting bound parameters in joined sources.")
        params[key] = value
    return params


def _source_ref(p: dict) -> dict | None:
    base = p["base"].get("source_ref")
    if base is None:
        return None
    steps = []
    for step in p["steps"]:
        source = step["ds"].get("source_ref")
        if source is None:
            return None
        columns = [source_name for source_name, _ in step["cols"]]
        all_columns = list(step["ds"]["df"].columns)
        steps.append({
            "source": source,
            "how": step["how"],
            "conditions": [{"left": cond["left"], "op": cond["op"],
                            "right": cond["right"]} for cond in step["conds"]],
            "columns": None if columns == all_columns else columns,
            "alias": step["alias"],
            "filters": [f["ref"] for f in step.get("filters") or []] or None,
        })
    from source_models import source_dict
    return source_dict({"kind": "join", "base": base, "steps": steps,
                        "base_filters": [f["ref"] for f in p.get("base_filters") or []] or None})

def _duckdb_sql(p: dict) -> dict:
    relations = {id(p["base"]): '"source_0"'}
    staged_inputs = ["source_0"]
    ctes, parameters = [], {}
    base_rel, params = _filtered_rel(relations[id(p["base"])], p.get("base_filters") or [],
                                     _filter_prefix(0, p), pg=False)
    parameters.update(params)
    for step in p["steps"]:
        dataset = step["ds"]
        if id(dataset) not in relations:
            alias = f"source_{len(staged_inputs)}"
            relations[id(dataset)] = _q(alias)
            staged_inputs.append(alias)
        name = f"step_{step['no']}"
        left = base_rel if step["no"] == 1 else _q(f"step_{step['no'] - 1}")
        right, params = _filtered_rel(relations[id(dataset)], step.get("filters") or [],
                                      _filter_prefix(step["no"], p), pg=False)
        parameters.update(params)
        sql = _step_sql(step, left, right)
        ctes.append(f"{_q(name)} AS ({sql})")
    final = _q(f"step_{len(p['steps'])}")
    statement = "WITH " + ", ".join(ctes) + f" SELECT * FROM {final}"
    return {"engine": "duckdb", "sql": statement, "parameters": parameters,
            "staged_inputs": staged_inputs}


def _duck_literal(value) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, datetime.datetime):
        return f"TIMESTAMP '{value.isoformat(sep=' ')}'"
    if isinstance(value, datetime.date):
        return f"DATE '{value.isoformat()}'"
    return "'" + str(value).replace("'", "''") + "'"


def duck_inline(sql: str, params: dict) -> str:
    """DuckDB SQL with `$name` filter parameters rendered as literals (display only)."""
    if not params:
        return sql
    names = sorted(params, key=len, reverse=True)
    pattern = re.compile(r"\$(" + "|".join(map(re.escape, names)) + r")\b")
    return pattern.sub(lambda m: _duck_literal(params[m.group(1)]), sql)

def _generated_sql(p: dict) -> dict:
    if p["engine"] == "aurora":
        sql = aurora_sql(p)["unlimited"]()
        parameters = _bound_params(p)
        generated = {"engine": "aurora", "sql": sql,
                     "parameters": parameters}
        try:
            import sql_source
            generated["copyable_sql"] = sql_source.inline_parameters(sql, parameters)
        except ValueError:
            generated["copyable_sql"] = None
            generated["copyable_sql_error"] = (
                "Some generated values cannot be inlined safely. Use the join preview "
                "or remove unsupported source parameters.")
        return generated
    return _duckdb_sql(p)

def full_reader_kind(ds: dict) -> str | None:
    """How a cross-source (DuckDB) join reads every row of a capped,
    in-memory input: "aurora" (its origin table) or "bq" (BigQuery Storage
    Read API), or None when only the loaded rows exist."""
    if not ds.get("capped") or ds.get("live_source") or ds.get("disk_source"):
        return None
    if (ds.get("origin") or {}).get("kind") == "aurora" and ds["origin"].get("table"):
        return "aurora"
    try:
        import bq
        return "bq" if bq.full_source(ds) else None
    except Exception:
        return None


def capped_inputs(inputs: list[dict], full: set[int] = frozenset()) -> list[str]:
    """Incomplete inputs, except those (by id) read in full from their source."""
    return list(dict.fromkeys(ds["source"] for ds in inputs
                              if ds.get("capped") and not ds.get("live_source")
                              and id(ds) not in full))


def _capped_inputs(p: dict, readers: bool = False) -> list[str]:
    """Capped inputs of a join; with `readers`, those a DuckDB-staged join
    still cannot read in full (the in-memory fallback reads none in full)."""
    inputs = [p["base"]] + [s["ds"] for s in p["steps"]]
    full = {id(ds) for ds in inputs if full_reader_kind(ds)} if readers else set()
    return capped_inputs(inputs, full)

def validate(base_id: str, steps: list[dict], base_filters: list | None = None) -> dict:

    p = plan(base_id, steps, base_filters)
    # Static: a BigQuery view found at run time still falls back to loaded rows.
    capped = _capped_inputs(p, readers=True) if p["engine"] == "duckdb" else []
    error = _first_error(p)
    generated = None
    if error is None:
        try:
            generated = _generated_sql(p)
            try:
                import sqlglot
                source = generated.get("copyable_sql") or (
                    duck_inline(generated["sql"], generated["parameters"])
                    if generated["engine"] == "duckdb" else generated["sql"])
                if len(source) <= 200_000:
                    dialect = "postgres" if generated["engine"] == "aurora" else "duckdb"
                    generated["display_sql"] = sqlglot.parse_one(source, read=dialect).sql(dialect=dialect, pretty=True)
            except (ValueError, RecursionError, sqlglot.errors.SqlglotError):
                pass
        except ValueError as exc:
            p["problems"].append(str(exc))
            error = str(exc)
    return {"ok": error is None, "engine": p["engine"],
            "engine_reason": p["engine_reason"], "capped_inputs": capped,
            "generated_sql": generated,
            "problems": p["problems"],
            "base_filters": p["base_filter_checks"],
            "steps": [{"problems": s["problems"], "notes": s["notes"],
                       "conditions": s["checks"], "filters": s["filter_checks"]}
                      for s in p["steps"]]}

def _step_sql(step: dict, l_from: str, r_from: str,
              names: dict[str, str] | None = None,
              right_names: dict[str, str] | None = None) -> str:

    pg = names is not None
    n = names.__getitem__ if pg else (lambda c: c)
    rn = (right_names or {}).get
    on = []
    for c in step["conds"]:
        lref, rref = f"l.{_q(n(c['left']))}", f"r.{_q(rn(c['right'], c['right']))}"

        if c["cast"] or (pg and c["kinds"] == ("text", "text")):
            t = "TEXT" if pg else "VARCHAR"
            lref, rref = f"CAST({lref} AS {t})", f"CAST({rref} AS {t})"
        on.append(f"{lref} {c['op']} {rref}")
    filled = _merged_keys(step)
    select = [(f"COALESCE(l.{_q(n(c))}, r.{_q(rn(filled[c], filled[c]))}) AS {_q(n(c))}"
               if c in filled else f"l.{_q(n(c))}") for c in step["left"]]
    select += [f"r.{_q(rn(src, src))} AS {_q(n(out))}" for src, out in step["cols"]]
    cols, cond = ", ".join(select), " AND ".join(on)
    if pg and step["how"] in ("semi", "anti"):
        neg = "NOT " if step["how"] == "anti" else ""
        return (f"SELECT {cols} FROM {l_from} AS l WHERE {neg}EXISTS "
                f"(SELECT 1 FROM {r_from} AS r WHERE {cond})")
    return f"SELECT {cols} FROM {l_from} AS l {HOWS[step['how']]} {r_from} AS r ON {cond}"

def _merged_keys(step: dict) -> dict[str, str]:
    """Left key -> right key to merge after a right/full join.

    Rows that exist only on the joined side have NULL left columns, so the
    shared equality key is filled from the joined side; later steps joining
    on that key would otherwise match nothing for those rows.
    """
    if step["how"] not in ("right", "full"):
        return {}
    merged = {}
    for c in step["conds"]:
        if c["op"] == "=" and not c["cast"] and c["left"] not in merged:
            merged[c["left"]] = c["right"]
    return merged

def _table_ref(ds: dict) -> str:
    live = ds.get("live_source")
    if live:
        return f"({live['sql']})"
    o = ds["origin"]
    return f"{_q(o.get('schema') or PG_SCHEMA)}.{_q(o['table'])}"

def _inputs(p: dict) -> list[tuple[int, dict, list[dict]]]:
    """(step number, dataset, pre-join filters) for the base (0) and each step."""
    return [(0, p["base"], p.get("base_filters") or [])] + [
        (s["no"], s["ds"], s.get("filters") or []) for s in p["steps"]]


def _input_rel(ds: dict, no: int, filters: list[dict], p: dict | None = None) -> str:
    """PostgreSQL relation for one join input with its filters applied."""
    names = (ds.get("live_source") or {}).get("columns", {})
    ref = _table_ref(ds)
    if not filters:
        return ref if ds.get("live_source") else f"(SELECT * FROM {ref} AS filter_input)"
    return _filtered_rel(ref, filters, _filter_prefix(no, p), True, names)[0]


def aurora_sql(p: dict) -> dict:

    used: set[str] = set()
    names = {c: _pg_name(c, used) for c in p["steps"][0]["left"]}
    base_names = (p["base"].get("live_source") or {}).get("columns", {})
    base_cols = ", ".join(
        f"{_q(base_names.get(c, c))} AS {_q(names[c])}"
                          for c in p["steps"][0]["left"])
    base_where = ""
    if p.get("base_filters"):
        where, _ = _filter_where(p["base_filters"],
                                 lambda c: f"base_input.{_q(base_names.get(c, c))}",
                                 _filter_prefix(0, p))
        base_where = f" WHERE {where}"
    ctes = [f"s0 AS (SELECT {base_cols} FROM {_table_ref(p['base'])} AS base_input{base_where})"]
    for s in p["steps"]:
        for _, out in s["cols"]:
            names[out] = _pg_name(out, used)
        right_names = (s["ds"].get("live_source") or {}).get("columns", {})
        right_rel, _ = _filtered_rel(_table_ref(s["ds"]), s.get("filters") or [],
                                     _filter_prefix(s["no"], p), True, right_names)
        body = _step_sql(s, f"s{s['no'] - 1}", right_rel,
                         names, right_names)
        ctes.append(f"s{s['no']} AS ({body})")
    last = len(p["steps"])

    def with_(i: int) -> str:
        return "WITH " + ", ".join(ctes[:i + 1])

    return {"ctes": ctes, "names": names,
            "count": lambda i: f"{with_(i)} SELECT count(*) FROM s{i}",
            "rows": lambda i: f"{with_(i)} SELECT 1 FROM s{i}",
            "select": lambda limit: f"{with_(last)} SELECT * FROM s{last} LIMIT {int(limit)}",
            "unlimited": lambda: f"{with_(last)} SELECT * FROM s{last}"}

# Above this many estimated rows, report PostgreSQL's estimate instead of
# running an exact count(*) (each exact step count re-runs the join chain).
EXACT_COUNT_MAX_ROWS = 1_000_000


def _plan_rows(conn, rows_sql: str, params: dict) -> int | None:
    """PostgreSQL's row estimate for `rows_sql` (an uncounted SELECT).

    Estimating the plain query rather than its count(*) matters: under a
    parallel count the node below the aggregate reports partial results per
    worker, while the top node of the plain query (a Gather when parallel)
    reports the total.
    """
    import json as _json
    raw = conn.execute(text(f"EXPLAIN (FORMAT JSON) {rows_sql}"), params).scalar()
    plan = (_json.loads(raw) if isinstance(raw, str) else raw)[0]["Plan"]
    rows = plan.get("Plan Rows")
    return int(rows) if rows is not None else None


def _step_stats(before: int, right_rows: int, total: int, cap: int) -> dict:
    growth = round(total / before, 2) if before else None
    return {"right_rows": int(right_rows), "rows": int(total),
            "truncated": total > cap, "rows_before": int(before),
            "growth": growth,
            "fanout": growth is not None and growth > FANOUT_RATIO}

GROWTH_WARNING = 10.0


def _flag_growth(stats: dict) -> None:
    """Add overall growth across all steps, and a warning when it explodes."""
    steps = stats.get("steps") or []
    base = stats.get("base_rows")
    if not steps or not base:
        return
    final = steps[-1].get("rows")
    if final is None:
        return
    growth = round(final / base, 2)
    stats["growth_total"] = growth
    if growth >= GROWTH_WARNING:
        approx = "~" if any(s.get("estimated") for s in steps) else ""
        stats["large_growth"] = True
        stats.setdefault("notes", []).insert(0, (
            f"This join produces {approx}{final:,} rows, {growth:g}× the {base:,}-row base. "
            "Joining several one-to-many tables on the same key multiplies rows; "
            "consider filtering, aggregating, or joining fewer tables at once."))


def _finish(stats: dict, rows: int) -> dict:
    last = stats["steps"][-1]
    stats.update(rows=rows, total_rows=last["rows"],
                 truncated=any(s["truncated"] for s in stats["steps"]))
    return stats

def _run_duckdb(p: dict, cap: int) -> dict:
    frame = p["base"]["df"]
    con = duckdb.connect()
    try:
        if p.get("base_filters"):
            con.register("b", frame)
            rel, params = _filtered_rel("b", p["base_filters"], _filter_prefix(0, p), pg=False)
            frame = con.execute(f"SELECT * FROM {rel}", params).df()
            con.unregister("b")
        stats = {"engine": "duckdb", "base_rows": len(frame), "steps": [], "notes": []}
        for s in p["steps"]:
            right = s["ds"]["df"]
            con.register("l", frame)
            con.register("r", right)
            r_rel, params = _filtered_rel("r", s.get("filters") or [],
                                          _filter_prefix(s["no"], p), pg=False)
            right_rows = (con.execute(f"SELECT count(*) FROM {r_rel}", params).fetchone()[0]
                          if params or s.get("filters") else len(right))
            sql = _step_sql(s, "l", r_rel)
            total = con.execute(f"SELECT count(*) FROM ({sql})", params).fetchone()[0]
            before, frame = len(frame), con.execute(f"{sql} LIMIT {int(cap)}", params).df()
            con.unregister("l")
            con.unregister("r")
            stats["steps"].append(_step_stats(before, right_rows, total, cap))
            stats["notes"] += [f"step {s['no']}: {n}" for n in s["notes"]]
    finally:
        con.close()
    stats["capped_inputs"] = _capped_inputs(p)
    if stats["capped_inputs"]:
        stats["notes"].append(
            f"Ran in memory on the loaded rows of {', '.join(stats['capped_inputs'])} "
            f"(capped at {queries.ROW_CAP:,}) — results may be incomplete.")
    return {"df": frame, "stats": _finish(stats, len(frame))}

def _aurora_error(e: Exception, timeout_ms: int) -> Exception:
    orig = getattr(e, "orig", None) or e
    if getattr(orig, "sqlstate", None) == "57014":
        return JoinTimeout(f"The join exceeded its {timeout_ms / 1000:g} s limit." if timeout_ms else "The database cancelled the join.")
    return JoinEngineError("Aurora: " + str(orig).split("\n")[0][:300])

def _run_aurora(p: dict, cap: int, timeout_ms: int,
                fetch: int | None = None, preview_only: bool = False) -> dict:

    sql = aurora_sql(p)
    resource_id = ((p["base"].get("live_source") or {}).get("resource_id")
                   or (p["base"].get("origin") or {}).get("resource_id"))
    engine = db.get_engine_for_resource(resource_id)
    params = _bound_params(p)
    import disk_data
    live_sources = []
    for no, ds, filters in _inputs(p):
        live = ds.get("live_source")
        if live:
            live_sources.append(filtered_live(live, filters, _filter_prefix(no, p)))
        elif ds.get("origin"):
            origin = ds["origin"]
            columns = list(ds["df"].columns)
            live_sources.append(filtered_live({
                "resource_id": origin["resource_id"], "params": {},
                "sql": (f"SELECT * FROM {_q(origin.get('schema') or PG_SCHEMA)}."
                        f"{_q(origin['table'])}"),
                "columns": {name: name for name in columns},
            }, filters, _filter_prefix(no, p)))
    output_source = {
        "resource_id": resource_id, "params": params,
        "sql": sql["unlimited"](),
        "columns": {name: name for name in p["columns"]},
    }
    source_ref = _source_ref(p)
    if source_ref and disk_data._requires_compiler_trust(source_ref):
        output_source = disk_data._compiled_source_query(source_ref, output_source)
    source_estimate = disk_data.guard_live_join(live_sources, output_source)
    try:
        with engine.begin() as conn, query_cancellation.postgres_connection(conn):
            if conn.dialect.name == "postgresql":
                conn.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                conn.exec_driver_sql("SET LOCAL search_path = pg_catalog")
                query_cancellation.check()
                conn.exec_driver_sql(f"SET LOCAL statement_timeout = {int(timeout_ms)}")

            def scalar(q: str) -> int:
                query_cancellation.check()
                return int(conn.execute(text(q), params).scalar())

            estimated = []

            def counted(q: str, rows_q: str) -> int:
                """Exact count when small; PostgreSQL's estimate when large."""
                query_cancellation.check()
                guess = _plan_rows(conn, rows_q, params) if conn.dialect.name == "postgresql" else None
                if guess is not None and guess > EXACT_COUNT_MAX_ROWS:
                    estimated.append(True)
                    return guess
                estimated.append(False)
                return scalar(q)

            def table_rows(ds: dict, no: int, filters: list[dict]) -> int:
                # Rows of the input after its pre-join filters.
                if not filters and not ds.get("live_source") and not ds.get("capped"):
                    estimated.append(False)
                    return len(ds["df"])
                ref = _input_rel(ds, no, filters, p)
                return counted(f"SELECT count(*) FROM {ref} AS live_input",
                               f"SELECT 1 FROM {ref} AS live_input")

            query_cancellation.check()
            if preview_only:
                base_rows = None
                steps = []
                if conn.dialect.name == "postgresql":
                    # Planner estimates cost no scans and let the preview show
                    # each step's growth before anyone runs the full join.
                    savepoint = conn.begin_nested()
                    try:
                        def guess(ds, no, filters):
                            if not filters and not ds.get("live_source") and not ds.get("capped"):
                                return len(ds["df"])
                            q = f"SELECT 1 FROM {_input_rel(ds, no, filters, p)} AS live_input"
                            return _plan_rows(conn, q, params)
                        before = base_rows = guess(p["base"], 0, p.get("base_filters") or [])
                        for step in p["steps"]:
                            total = _plan_rows(conn, sql["rows"](step["no"]), params)
                            stat = _step_stats(before or 0, guess(step["ds"], step["no"], step.get("filters") or []) or 0,
                                               total or 0, cap)
                            stat.update(truncated=False, estimated=True)
                            steps.append(stat)
                            before = total
                        savepoint.commit()
                    except Exception:
                        savepoint.rollback()
                        query_cancellation.check()
                        base_rows, steps = None, []
                res = conn.execute(text(sql["select"](PREVIEW_ROWS + 1)), params)
            else:
                before = base_rows = table_rows(p["base"], 0, p.get("base_filters") or [])
                steps = []
                last_no = p["steps"][-1]["no"]
                for step in p["steps"]:
                    mark = len(estimated)
                    # The final total stays exact (one run of the whole chain);
                    # intermediate steps use estimates when large, because each
                    # exact step count re-runs every join before it.
                    total = (scalar(sql["count"](step["no"])) if step["no"] == last_no
                             else counted(sql["count"](step["no"]), sql["rows"](step["no"])))
                    step_stats = _step_stats(before, table_rows(step["ds"], step["no"], step.get("filters") or []),
                                             total, cap)
                    step_stats["truncated"] = False
                    step_stats["preview_rows"] = min(total, cap)
                    if any(estimated[mark:]):
                        step_stats["estimated"] = True
                    steps.append(step_stats)
                    before = total
                res = conn.execute(text(sql["select"](min(cap, fetch or cap))), params)
            df = pd.DataFrame.from_records([tuple(r) for r in res.fetchall()],
                                           columns=p["columns"], coerce_float=True)
    except Exception as e:
        query_cancellation.check()
        raise _aurora_error(e, timeout_ms) from e
    notes = [f"step {s['no']}: {n}" for s in p["steps"] for n in s["notes"]]
    stats = {"engine": "aurora", "base_rows": base_rows, "steps": steps,
             "notes": notes, "capped_inputs": [], **source_estimate}
    columns = {name: sql["names"][name] for name in p["columns"]}
    live_source = {
        "resource_id": (p["base"].get("live_source") or {}).get("resource_id")
        or p["base"]["origin"]["resource_id"],
        "sql": sql["unlimited"](),
        "params": params,
        "columns": columns,
    }
    if source_ref and disk_data._requires_compiler_trust(source_ref):
        live_source = disk_data._compiled_source_query(source_ref, live_source)
    if preview_only:
        stats.update(rows=None, total_rows=None, truncated=False, sample_only=True,
                     sample_truncated=len(df) > PREVIEW_ROWS)
        return {"df": df, "stats": stats, "live_source": live_source}
    stats = _finish(stats, min(before, cap))
    if any(s.get("estimated") for s in steps) or (estimated and estimated[0]):
        stats["estimated"] = True               # some step or input sizes are estimates
    return {"df": df, "stats": stats, "live_source": live_source}

def _checked_plan(base_id: str, steps: list[dict], allow_loaded: bool = False,
                  base_filters: list | None = None, full_reads: bool = True) -> dict:
    if not steps:
        raise ValueError("Add at least one join step.")
    if len(steps) > MAX_STEPS:
        raise ValueError(f"At most {MAX_STEPS} joins in one pipeline.")
    p = plan(base_id, steps, base_filters)
    has_live = any(ds.get("live_source") for ds in
                   [p["base"]] + [s["ds"] for s in p["steps"]])
    if has_live and p["engine"] != "aurora" and not allow_loaded:
        raise ValueError("Cross-source joins require explicit approval to read each full source.")
    # A full join reads capped BigQuery inputs completely (BigQuery bills per
    # bytes scanned), so it needs the same approval; previews use loaded rows.
    if (full_reads and p["engine"] != "aurora" and not allow_loaded
            and any(full_reader_kind(ds) == "bq" for ds in [p["base"]] + [s["ds"] for s in p["steps"]])):
        raise ValueError("Joining BigQuery tables reads each one in full, which BigQuery bills by "
                         "bytes scanned. Approve the full-source join to continue.")
    error = _first_error(p)
    if error:
        raise ValueError(error)
    return p

def _report(phase: str, **detail) -> None:
    import data_jobs
    data_jobs.report(phase, **detail)


def _report_engine(p: dict) -> None:
    n = len(p["steps"]) + 1
    if p["engine"] == "aurora":
        _report(f"Joining {n} tables inside the database (PostgreSQL)", engine="aurora", sources=n)
    else:
        _report(f"Joining {n} sources in DuckDB", engine="duckdb", sources=n)


def project_output(out: dict, output: dict | None) -> dict:
    """Drop and rename fields of a finished join (any engine).

    In-memory frames are projected directly, live (SQL) sources remap their
    logical column names, and DuckDB results get a view over the join table.
    """
    if not output or not (output.get("exclude") or output.get("rename")):
        return out
    import copy
    exclude = set(output.get("exclude") or [])
    rename = {k: v.strip() for k, v in (output.get("rename") or {}).items()}
    columns = list(out["df"].columns)
    unknown = sorted((exclude | set(rename)) - set(columns))
    if unknown:
        raise ValueError(f"Unknown field(s) in the join result: {', '.join(unknown[:5])}.")
    keep = [c for c in columns if c not in exclude]
    if not keep:
        raise ValueError("Keep at least one field in the joined result.")
    final = [rename.get(c, c) for c in keep]
    # Case-insensitive: DuckDB (and exports) treat "a" and "A" as one name.
    folded = [n.casefold() for n in final]
    dupes = sorted({n for n, f in zip(final, folded) if folded.count(f) > 1})
    if dupes:
        raise ValueError(f"Field names must be unique: {', '.join(dupes[:5])}.")
    out = {**out, "df": out["df"][keep].rename(columns=rename)}
    live = out.get("live_source")
    if live:
        projected = copy.copy(live)
        projected["columns"] = {rename.get(c, c): live["columns"][c] for c in keep}
        out["live_source"] = projected
    disk = out.get("disk_source")
    if disk:
        import uuid
        import disk_data
        view = f"fields_{uuid.uuid4().hex[:12]}"
        con = disk_data._connect(disk["path"])
        try:
            con.execute(f"CREATE VIEW {disk_data._q(view)} AS SELECT " + ", ".join(
                f"{disk_data._q(c)} AS {disk_data._q(rename.get(c, c))}" for c in keep)
                + f" FROM {disk_data._q(disk['table'])}")
        finally:
            con.close()
        out["disk_source"] = {**disk, "table": view, "columns": final}
    return out


@execution.workload("bulk")
def run(base_id: str, steps: list[dict], cap: int = queries.ROW_CAP,
        allow_loaded: bool = False, base_filters: list | None = None,
        output: dict | None = None) -> dict:
    out = _run(base_id, steps, cap, allow_loaded, base_filters)
    try:
        return project_output(out, output)
    except Exception:
        # Nothing owns the staged result yet, so remove it here.
        if out.get("disk_source"):
            import disk_data
            disk_data.remove(out["disk_source"])
        raise


def _run(base_id: str, steps: list[dict], cap: int = queries.ROW_CAP,
         allow_loaded: bool = False, base_filters: list | None = None) -> dict:

    p = (_checked_plan(base_id, steps, allow_loaded, base_filters) if base_filters
         else _checked_plan(base_id, steps, allow_loaded))
    _report_engine(p)
    if p["engine"] == "aurora":
        try:
            return _run_aurora(p, cap, query_cancellation.join_timeout_ms(RUN_TIMEOUT_MS))
        except (JoinTimeout, JoinEngineError) as e:
            query_cancellation.check()
            if any(ds.get("live_source") for ds in
                   [p["base"]] + [s["ds"] for s in p["steps"]]):
                raise
            _report("Database join unavailable; joining in memory (DuckDB)", engine="duckdb")
            out = _run_duckdb(p, cap)
            out["stats"]["notes"].insert(0, f"{e} Ran in memory instead.")
            return out
    import disk_data
    return disk_data.run_join(p)

def preview(base_id: str, steps: list[dict], allow_loaded: bool = False,
            base_filters: list | None = None, output: dict | None = None) -> dict:

    p = _checked_plan(base_id, steps, allow_loaded, base_filters, full_reads=False)
    _report_engine(p)
    if p["engine"] == "aurora":
        try:
            out = _run_aurora(p, queries.ROW_CAP, query_cancellation.join_timeout_ms(PREVIEW_TIMEOUT_MS), preview_only=True)
        except JoinTimeout as e:
            raise
        except JoinEngineError as e:
            query_cancellation.check()
            if any(ds.get("live_source") for ds in
                   [p["base"]] + [s["ds"] for s in p["steps"]]):
                raise
            out = _run_duckdb(p, queries.ROW_CAP)
            out["stats"]["notes"].insert(0, f"{e} Previewed in memory instead.")
    else:
        import disk_data
        # BigQuery inputs preview on their loaded rows (the notes say so);
        # running the join reads them in full.
        out = disk_data.run_join(p, full_readers=False)
    try:
        out = project_output(out, output)
    except Exception:
        if out.get("disk_source"):
            import disk_data
            disk_data.remove(out["disk_source"])
        raise
    df = out["df"].head(PREVIEW_ROWS)
    _flag_growth(out["stats"])
    result = {**out["stats"], "columns": list(df.columns),
              "sample": df.astype(object).where(df.notna(), None).values.tolist(),
              "sample_truncated": out["stats"].get("sample_truncated", False) if out["stats"].get("sample_only") else int(out["stats"].get("total_rows", 0)) > len(df)}
    if out.get("disk_source"):
        import disk_data
        disk_data.remove(out["disk_source"])
    return result

def suggest(left_id: str, right_id: str, limit: int = 5) -> list[dict]:

    left_ds, right_ds = datasets.get(left_id), datasets.get(right_id)
    left, right = left_ds["df"], right_ds["df"]
    rname = re.sub(r"[^a-z0-9]", "", default_alias(right_ds["source"]).lower()).removesuffix("s")
    lname = re.sub(r"[^a-z0-9]", "", default_alias(left_ds["source"]).lower()).removesuffix("s")

    def norm(c: str) -> str:
        return re.sub(r"[^a-z0-9]", "", str(c).lower())

    cands = []
    for lc in left.columns:
        for rc in right.columns:
            ln, rn = norm(lc), norm(rc)
            if ln == rn:
                name_score = 1.0
            elif (ln == "id" and rn == f"{lname}id") or (rn == "id" and ln == f"{rname}id"):
                name_score = 0.9
            elif ln.endswith("id") and rn.endswith("id") and (ln in rn or rn in ln):
                name_score = 0.6
            else:
                continue
            lk, rk = _kind(left[lc]), _kind(right[rc])
            if {lk, rk} not in ({"number"}, {"text"}, {"time"}, {"number", "text"}):
                continue
            lv = left[lc].dropna().astype(str).head(SUGGEST_SAMPLE).unique()
            rv = set(right[rc].dropna().astype(str).unique())
            overlap = float(sum(v in rv for v in lv) / len(lv)) if len(lv) else 0.0
            if overlap == 0:
                continue
            cands.append({"left": lc, "right": rc, "overlap": round(overlap, 3),
                          "score": round(name_score * 0.4 + overlap * 0.6, 3)})
    return sorted(cands, key=lambda c: -c["score"])[:limit]
