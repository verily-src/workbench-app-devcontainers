"""Notebook-style joins (Metabase-like) over open datasets.

A join is a base dataset plus ordered steps. Each step joins one more
dataset onto the result so far, on one or more AND-ed conditions, and
brings in a chosen subset of its columns named `<alias> → <column>`.
Semi/anti joins keep only base rows with / without a match — the cohort
"has a visit" / "has no visit" questions — and add no columns.

plan() checks a pipeline without running it; run(), preview() and
validate() all go through it. When every input is an untouched table
load from one Aurora database, the whole pipeline runs as one Postgres
query over the full tables (CTE s0 = base table, s<i> = step i over
s<i-1>). Anything else runs in DuckDB over the in-memory frames, which
are handed over zero-copy, so a step costs one SQL query.
"""

import hashlib
import re

import duckdb
import pandas as pd

import datasets
import db
import queries

HOWS = {"inner": "INNER JOIN", "left": "LEFT JOIN", "right": "RIGHT JOIN",
        "full": "FULL OUTER JOIN", "semi": "SEMI JOIN", "anti": "ANTI JOIN"}
# The pre-notebook API called a full outer join "outer".
HOW_ALIASES = {"outer": "full"}
OPS = ("=", "!=", "<", "<=", ">", ">=")
MAX_STEPS = 6
PREVIEW_ROWS = 20
ARROW = " → "
SUGGEST_SAMPLE = 5000
# A step that more than doubles the rows almost always joined on a key
# that repeats on the right (one sample, many visits).
FANOUT_RATIO = 2.0
PG_SCHEMA = "public"
PG_IDENT_BYTES = 63
PREVIEW_TIMEOUT_MS = 10_000
# Below the app proxy's ~60 s limit, with room for the in-memory retry.
RUN_TIMEOUT_MS = 40_000
_NO_PARAMS = {"no_parameters": True}  # identifiers may contain '%'


class JoinTimeout(RuntimeError):
    pass


class JoinEngineError(RuntimeError):
    pass


def _q(ident: str) -> str:
    return '"' + str(ident).replace('"', '""') + '"'


def _kind(series: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(series):
        return "bool"
    if pd.api.types.is_numeric_dtype(series):
        return "number"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "time"
    return "text"


def aurora_origin(resource_id: str, table: str) -> dict:
    """Origin of a dataset read with queries.fetch_table (public schema)."""
    return {"kind": "aurora", "resource_id": resource_id,
            "schema": PG_SCHEMA, "table": table}


def default_alias(source: str) -> str:
    stem = str(source).split("/")[-1].strip()
    stem = re.sub(r"\.(parquet|csv|tsv|txt|json|ndjson)$", "", stem, flags=re.I)
    return stem or "joined"


def _output_name(alias: str, col: str, taken: set[str]) -> str:
    name, n = f"{alias}{ARROW}{col}", 2
    while name in taken:
        name, n = f"{alias}{ARROW}{col} ({n})", n + 1
    taken.add(name)
    return name


def _pg_name(name: str, used: set[str]) -> str:
    """Postgres silently cuts identifiers at 63 bytes, which can merge two
    long `alias → column` names. Cut them here instead, with a hash suffix."""
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


# ------------------------------------------------------------------ plan

def _check_condition(cond: dict, left: dict[str, str], right: dict[str, str],
                     step_no: int) -> tuple[str | None, str | None, dict | None]:
    """(problem, note, checked condition) for one condition."""
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
    if lk == rk:
        return None, None, checked
    if op not in ("=", "!="):
        return (f"Step {step_no}: can't compare {lcol!r} ({lk}) "
                f"{op} {rcol!r} ({rk})."), None, None
    return None, f"{lcol} ({lk}) and {rcol} ({rk}) compared as text", checked


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
    return {"no": step_no, "how": how, "ds": right_ds, "left": list(left),
            "out": out, "conds": conds, "cols": cols, "notes": notes,
            "checks": checks, "problems": problems, "errors": errors}


def plan(base_id: str, steps: list[dict]) -> dict:
    """Check a pipeline without running it. Every problem is collected
    (validate() reports them all); run() raises the first one."""
    problems = []
    if not steps:
        problems.append("Add at least one join step.")
    if len(steps) > MAX_STEPS:
        problems.append(f"At most {MAX_STEPS} joins in one pipeline.")
    base = datasets.get(base_id)
    left = {c: _kind(base["df"][c]) for c in base["df"].columns}
    planned = []
    for i, step in enumerate(steps[:MAX_STEPS], start=1):
        p = _plan_step(step, left, datasets.get(step.get("right_id", "")), i)
        planned.append(p)
        left = p["out"]
    out = {"base": base, "steps": planned, "problems": problems,
           "columns": list(left)}
    out["engine"], out["engine_reason"] = _engine(out)
    return out


def _first_error(p: dict) -> str | None:
    return next(iter(p["problems"] + [e for s in p["steps"] for e in s["errors"]]),
                None)


def _engine(p: dict) -> tuple[str, str]:
    """("aurora" | "duckdb", why). Pushdown needs every input to be an
    untouched table load from the same Aurora database."""
    origins = [ds.get("origin") or {} for ds in
               [p["base"]] + [s["ds"] for s in p["steps"]]]
    if any(o.get("kind") != "aurora" for o in origins):
        return "duckdb", "Not every table was loaded straight from Aurora."
    if len({o["resource_id"] for o in origins}) > 1:
        return "duckdb", "The tables are in different Aurora databases."
    if any(s["how"] == "full" and any(c["op"] != "=" for c in s["conds"])
           for s in p["steps"]):
        return "duckdb", "Postgres runs full joins on = conditions only."
    return "aurora", f"All tables are in Aurora database {origins[0]['resource_id']}."


def _capped_inputs(p: dict) -> list[str]:
    inputs = [p["base"]] + [s["ds"] for s in p["steps"]]
    return list(dict.fromkeys(ds["source"] for ds in inputs if ds.get("capped")))


def validate(base_id: str, steps: list[dict]) -> dict:
    """Problems per step and per condition, and the engine that would run,
    without executing anything."""
    p = plan(base_id, steps)
    capped = _capped_inputs(p) if p["engine"] == "duckdb" else []
    return {"ok": _first_error(p) is None, "engine": p["engine"],
            "engine_reason": p["engine_reason"], "capped_inputs": capped,
            "problems": p["problems"],
            "steps": [{"problems": s["problems"], "notes": s["notes"],
                       "conditions": s["checks"]} for s in p["steps"]]}


# ------------------------------------------------------------------- SQL

def _step_sql(step: dict, l_from: str, r_from: str,
              names: dict[str, str] | None = None) -> str:
    """One step as a SELECT over l (result so far) and r (joined table).
    `names` maps logical column names to Postgres-safe ones; without it
    the SQL is DuckDB's."""
    pg = names is not None
    n = names.__getitem__ if pg else (lambda c: c)
    on = []
    for c in step["conds"]:
        lref, rref = f"l.{_q(n(c['left']))}", f"r.{_q(c['right'])}"
        # Postgres has no implicit uuid/date = text: "text"-kind pairs are
        # compared as text too (a no-op for real text columns).
        if c["cast"] or (pg and c["kinds"] == ("text", "text")):
            t = "TEXT" if pg else "VARCHAR"
            lref, rref = f"CAST({lref} AS {t})", f"CAST({rref} AS {t})"
        on.append(f"{lref} {c['op']} {rref}")
    select = [f"l.{_q(n(c))}" for c in step["left"]]
    select += [f"r.{_q(src)} AS {_q(n(out))}" for src, out in step["cols"]]
    cols, cond = ", ".join(select), " AND ".join(on)
    if pg and step["how"] in ("semi", "anti"):
        neg = "NOT " if step["how"] == "anti" else ""
        return (f"SELECT {cols} FROM {l_from} AS l WHERE {neg}EXISTS "
                f"(SELECT 1 FROM {r_from} AS r WHERE {cond})")
    return f"SELECT {cols} FROM {l_from} AS l {HOWS[step['how']]} {r_from} AS r ON {cond}"


def _table_ref(ds: dict) -> str:
    o = ds["origin"]
    return f"{_q(o.get('schema') or PG_SCHEMA)}.{_q(o['table'])}"


def aurora_sql(p: dict) -> dict:
    """The pipeline as Postgres CTEs. Returns the CTEs, the logical → SQL
    column name map, and count/select builders."""
    used: set[str] = set()
    names = {c: _pg_name(c, used) for c in p["steps"][0]["left"]}
    base_cols = ", ".join(_q(c) if names[c] == c else f"{_q(c)} AS {_q(names[c])}"
                          for c in p["steps"][0]["left"])
    ctes = [f"s0 AS (SELECT {base_cols} FROM {_table_ref(p['base'])})"]
    for s in p["steps"]:
        for _, out in s["cols"]:
            names[out] = _pg_name(out, used)
        body = _step_sql(s, f"s{s['no'] - 1}", _table_ref(s["ds"]), names)
        ctes.append(f"s{s['no']} AS ({body})")
    last = len(p["steps"])

    def with_(i: int) -> str:
        return "WITH " + ", ".join(ctes[:i + 1])

    return {"ctes": ctes, "names": names,
            "count": lambda i: f"{with_(i)} SELECT count(*) FROM s{i}",
            "select": lambda limit: f"{with_(last)} SELECT * FROM s{last} LIMIT {int(limit)}"}


# ------------------------------------------------------------------- run

def _step_stats(before: int, right_rows: int, total: int, cap: int) -> dict:
    growth = round(total / before, 2) if before else None
    return {"right_rows": int(right_rows), "rows": int(total),
            "truncated": total > cap, "rows_before": int(before),
            "growth": growth,
            "fanout": growth is not None and growth > FANOUT_RATIO}


def _finish(stats: dict, rows: int) -> dict:
    last = stats["steps"][-1]
    stats.update(rows=rows, total_rows=last["rows"],
                 truncated=any(s["truncated"] for s in stats["steps"]))
    return stats


def _run_duckdb(p: dict, cap: int) -> dict:
    frame = p["base"]["df"]
    stats = {"engine": "duckdb", "base_rows": len(frame), "steps": [], "notes": []}
    con = duckdb.connect()
    try:
        for s in p["steps"]:
            right = s["ds"]["df"]
            sql = _step_sql(s, "l", "r")
            con.register("l", frame)
            con.register("r", right)
            total = con.execute(f"SELECT count(*) FROM ({sql})").fetchone()[0]
            before, frame = len(frame), con.execute(f"{sql} LIMIT {int(cap)}").df()
            con.unregister("l")
            con.unregister("r")
            stats["steps"].append(_step_stats(before, len(right), total, cap))
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
        return JoinTimeout(f"The join took longer than {timeout_ms // 1000} s in Aurora.")
    return JoinEngineError("Aurora: " + str(orig).split("\n")[0][:300])


def _run_aurora(p: dict, cap: int, timeout_ms: int,
                fetch: int | None = None) -> dict:
    """Run the pipeline in Postgres. `fetch` limits the rows read back
    (preview) without changing the counts."""
    sql = aurora_sql(p)
    engine = db.get_engine_for_resource(p["base"]["origin"]["resource_id"])
    try:
        with engine.begin() as conn:
            if conn.dialect.name == "postgresql":
                conn.exec_driver_sql(f"SET LOCAL statement_timeout = {int(timeout_ms)}")

            def scalar(q: str) -> int:
                return int(conn.exec_driver_sql(q, execution_options=_NO_PARAMS).scalar())

            def table_rows(ds: dict) -> int:
                if not ds.get("capped"):
                    return len(ds["df"])
                return scalar(f"SELECT count(*) FROM {_table_ref(ds)}")

            before = base_rows = table_rows(p["base"])
            steps = []
            for s in p["steps"]:
                total = scalar(sql["count"](s["no"]))
                steps.append(_step_stats(before, table_rows(s["ds"]), total, cap))
                before = total
            res = conn.exec_driver_sql(sql["select"](min(cap, fetch or cap)),
                                       execution_options=_NO_PARAMS)
            df = pd.DataFrame.from_records([tuple(r) for r in res.fetchall()],
                                           columns=p["columns"], coerce_float=True)
    except Exception as e:
        raise _aurora_error(e, timeout_ms) from e
    notes = [f"step {s['no']}: {n}" for s in p["steps"] for n in s["notes"]]
    stats = {"engine": "aurora", "base_rows": base_rows, "steps": steps,
             "notes": notes, "capped_inputs": []}
    return {"df": df, "stats": _finish(stats, min(before, cap))}


def _checked_plan(base_id: str, steps: list[dict]) -> dict:
    if not steps:
        raise ValueError("Add at least one join step.")
    if len(steps) > MAX_STEPS:
        raise ValueError(f"At most {MAX_STEPS} joins in one pipeline.")
    p = plan(base_id, steps)
    error = _first_error(p)
    if error:
        raise ValueError(error)
    return p


def run(base_id: str, steps: list[dict], cap: int = queries.ROW_CAP) -> dict:
    """Execute the join pipeline. Returns the (capped) frame and stats.
    An Aurora failure falls back to the in-memory path, with a note."""
    p = _checked_plan(base_id, steps)
    if p["engine"] == "aurora":
        try:
            return _run_aurora(p, cap, RUN_TIMEOUT_MS)
        except (JoinTimeout, JoinEngineError) as e:
            out = _run_duckdb(p, cap)
            out["stats"]["notes"].insert(0, f"{e} Ran in memory instead.")
            return out
    return _run_duckdb(p, cap)


def preview(base_id: str, steps: list[dict]) -> dict:
    """Stats plus a sample. On Aurora the counts run under a statement
    timeout; JoinTimeout is raised when they don't finish."""
    p = _checked_plan(base_id, steps)
    if p["engine"] == "aurora":
        try:
            out = _run_aurora(p, queries.ROW_CAP, PREVIEW_TIMEOUT_MS, fetch=PREVIEW_ROWS)
        except JoinTimeout as e:
            raise JoinTimeout(f"{e} The preview stops at {PREVIEW_TIMEOUT_MS // 1000} s; "
                              "joining into a new tab allows longer.") from e
        except JoinEngineError as e:
            out = _run_duckdb(p, queries.ROW_CAP)
            out["stats"]["notes"].insert(0, f"{e} Previewed in memory instead.")
    else:
        out = _run_duckdb(p, queries.ROW_CAP)
    df = out["df"].head(PREVIEW_ROWS)
    return {**out["stats"], "columns": list(df.columns),
            "sample": df.astype(object).where(df.notna(), None).values.tolist()}


def suggest(left_id: str, right_id: str, limit: int = 5) -> list[dict]:
    """Likely key pairs: matching names (incl. `id` ↔ `<table>_id`),
    compatible types, scored by how many left values appear on the right."""
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
