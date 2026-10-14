"""Notebook-style joins (Metabase-like) over open datasets, run in DuckDB.

A join is a base dataset plus ordered steps. Each step joins one more
dataset onto the result so far, on one or more AND-ed conditions, and
brings in a chosen subset of its columns named `<alias> → <column>`.
Semi/anti joins keep only base rows with / without a match — the cohort
"has a visit" / "has no visit" questions — and add no columns.

Frames are handed to DuckDB zero-copy, so a step costs one SQL query.
"""

import re

import duckdb
import pandas as pd

import datasets
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


def default_alias(source: str) -> str:
    stem = str(source).split("/")[-1].strip()
    stem = re.sub(r"\.(parquet|csv|tsv|txt|json|ndjson)$", "", stem, flags=re.I)
    return stem or "joined"


def _normalize_how(how: str) -> str:
    how = HOW_ALIASES.get(how, how)
    if how not in HOWS:
        raise ValueError(f"Join type must be one of {', '.join(HOWS)}.")
    return how


def _condition_sql(cond: dict, left: pd.DataFrame, right: pd.DataFrame,
                   step_no: int) -> tuple[str, str | None]:
    lcol, rcol, op = cond.get("left"), cond.get("right"), cond.get("op", "=")
    if op not in OPS:
        raise ValueError(f"Step {step_no}: operator must be one of {', '.join(OPS)}.")
    if lcol not in left.columns:
        raise ValueError(f"Step {step_no}: {lcol!r} is not a column of the left side.")
    if rcol not in right.columns:
        raise ValueError(f"Step {step_no}: {rcol!r} is not a column of the joined table.")
    lk, rk = _kind(left[lcol]), _kind(right[rcol])
    lref, rref = f"l.{_q(lcol)}", f"r.{_q(rcol)}"
    note = None
    if lk != rk:
        if op not in ("=", "!="):
            raise ValueError(f"Step {step_no}: can't compare {lcol!r} ({lk}) "
                             f"{op} {rcol!r} ({rk}).")
        lref, rref = f"CAST({lref} AS VARCHAR)", f"CAST({rref} AS VARCHAR)"
        note = f"{lcol} ({lk}) and {rcol} ({rk}) compared as text"
    return f"{lref} {op} {rref}", note


def _output_name(alias: str, col: str, taken: set[str]) -> str:
    name, n = f"{alias}{ARROW}{col}", 2
    while name in taken:
        name, n = f"{alias}{ARROW}{col} ({n})", n + 1
    taken.add(name)
    return name


def _step_sql(left: pd.DataFrame, right: pd.DataFrame, step: dict,
              step_no: int) -> tuple[str, list[str]]:
    how = _normalize_how(step.get("how", "left"))
    conds = step.get("conditions") or []
    if not conds:
        raise ValueError(f"Step {step_no}: add at least one join condition.")
    on, notes = [], []
    for cond in conds:
        sql, note = _condition_sql(cond, left, right, step_no)
        on.append(sql)
        if note:
            notes.append(note)
    select = [f"l.{_q(c)}" for c in left.columns]
    if how not in ("semi", "anti"):
        wanted = step.get("columns")
        cols = list(right.columns) if wanted is None else list(wanted)
        unknown = [c for c in cols if c not in right.columns]
        if unknown:
            raise ValueError(f"Step {step_no}: unknown column(s) {', '.join(map(repr, unknown))}.")
        alias = (step.get("alias") or "").strip() or "joined"
        taken = set(left.columns)
        select += [f"r.{_q(c)} AS {_q(_output_name(alias, c, taken))}" for c in cols]
    sql = (f"SELECT {', '.join(select)} FROM l {HOWS[how]} r "
           f"ON {' AND '.join(on)}")
    return sql, notes


def run(base_id: str, steps: list[dict], cap: int = queries.ROW_CAP) -> dict:
    """Execute the join pipeline. Returns the (capped) frame and stats."""
    if not steps:
        raise ValueError("Add at least one join step.")
    if len(steps) > MAX_STEPS:
        raise ValueError(f"At most {MAX_STEPS} joins in one pipeline.")
    frame = datasets.get(base_id)["df"]
    stats = {"base_rows": len(frame), "steps": [], "notes": []}
    con = duckdb.connect()
    try:
        for i, step in enumerate(steps, start=1):
            right = datasets.get(step.get("right_id", ""))["df"]
            sql, notes = _step_sql(frame, right, step, i)
            con.register("l", frame)
            con.register("r", right)
            total = con.execute(f"SELECT count(*) FROM ({sql})").fetchone()[0]
            frame = con.execute(f"{sql} LIMIT {int(cap)}").df()
            con.unregister("l")
            con.unregister("r")
            stats["steps"].append({"right_rows": len(right), "rows": int(total),
                                   "truncated": total > cap})
            stats["notes"] += [f"step {i}: {n}" for n in notes]
    finally:
        con.close()
    last = stats["steps"][-1]
    stats.update(rows=len(frame), total_rows=last["rows"],
                 truncated=any(s["truncated"] for s in stats["steps"]))
    return {"df": frame, "stats": stats}


def preview(base_id: str, steps: list[dict]) -> dict:
    out = run(base_id, steps)
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
