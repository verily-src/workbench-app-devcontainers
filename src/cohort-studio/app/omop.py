import datetime as dt
import logging
import math
import re
import threading
import time
from contextlib import contextmanager

import pandas as pd
from sqlalchemy import Engine, text

import database as db
import queries
from cache import ttl_cache

logger = logging.getLogger(__name__)

DOMAINS = {
    "condition": {"table": "condition_occurrence", "concept": "condition_concept_id",
                  "date": "condition_start_date"},
    "drug": {"table": "drug_exposure", "concept": "drug_concept_id",
             "date": "drug_exposure_start_date"},
    "procedure": {"table": "procedure_occurrence", "concept": "procedure_concept_id",
                  "date": "procedure_date"},
    "measurement": {"table": "measurement", "concept": "measurement_concept_id",
                    "date": "measurement_date", "value": "value_as_number"},
    "observation": {"table": "observation", "concept": "observation_concept_id",
                    "date": "observation_date"},
    "visit": {"table": "visit_occurrence", "concept": "visit_concept_id",
              "date": "visit_start_date"},
    "device": {"table": "device_exposure", "concept": "device_concept_id",
               "date": "device_exposure_start_date"},
    "death": {"table": "death", "concept": "cause_concept_id", "date": "death_date"},
}

DOMAIN_IDS = {"condition": "Condition", "drug": "Drug", "procedure": "Procedure",
              "measurement": "Measurement", "observation": "Observation",
              "visit": "Visit", "device": "Device"}
VOCAB_TABLES = ("concept", "concept_ancestor", "vocabulary", "domain",
                "concept_class", "concept_relationship", "relationship",
                "concept_synonym", "drug_strength", "source_to_concept_map")

OTHER_TABLES = {
    "person": "person", "observation_period": "person",
    "visit_detail": "clinical", "specimen": "clinical", "note": "clinical",
    "note_nlp": "clinical", "episode": "clinical", "episode_event": "clinical",
    "fact_relationship": "clinical",
    "condition_era": "era", "drug_era": "era", "dose_era": "era",
    "location": "health system", "care_site": "health system",
    "provider": "health system",
    "payer_plan_period": "economics", "cost": "economics",
    "cdm_source": "metadata", "metadata": "metadata",
    "cohort": "results", "cohort_definition": "results",
}
KNOWN_TABLES = ({d["table"]: k for k, d in DOMAINS.items()} | OTHER_TABLES
                | {t: "vocabulary" for t in VOCAB_TABLES})

OPENABLE = ({d["table"] for d in DOMAINS.values()}
            | {"person", "observation_period", "visit_detail", "specimen",
               "condition_era", "drug_era", "dose_era", "payer_plan_period"})

MAX_CRITERIA = 12
MAX_CONCEPTS = 500
MAX_SEARCH = 200
EXACT_COUNT_BELOW = 100_000
DETECT_TTL = 300
DETECT_TIMEOUT_MS = 10_000
SEARCH_TIMEOUT_MS = 5_000
COUNT_TIMEOUT_MS = 15_000
SUMMARY_TIMEOUT_MS = 30_000

OPEN_TIMEOUT_MS = 40_000
LABEL_CHARS = 32

_CRITERION_KEYS = {"domain", "concept_ids", "descendants", "exclude", "min_count",
                   "value_min", "value_max", "start", "end", "index_relation"}
_DEMOGRAPHIC_KEYS = {"gender_concept_ids", "age_min", "age_max",
                     "year_of_birth_min", "year_of_birth_max"}
_SPEC_KEYS = {"criteria", "demographics", "require_observation"}

class OmopTimeout(RuntimeError):
    pass

class OmopEngineError(RuntimeError):
    pass

def _q(ident: str) -> str:
    return '"' + str(ident).replace('"', '""') + '"'

def _cdm(info: dict, table: str) -> str:
    return f"{_q(info['cdm_schema'])}.{_q(table)}"

def _voc(info: dict, table: str) -> str:
    return f"{_q(info['vocab_schema'])}.{_q(table)}"

def _error(e: Exception, timeout_ms: int) -> Exception:
    orig = getattr(e, "orig", None) or e
    if getattr(orig, "sqlstate", None) == "57014":
        return OmopTimeout(f"The query took longer than {timeout_ms / 1000:g} s.")
    return OmopEngineError("Aurora: " + str(orig).split("\n")[0][:300])

@contextmanager
def _session(engine: Engine, timeout_ms: int):

    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
            yield conn
    except (ValueError, OmopTimeout, OmopEngineError):
        raise
    except Exception as e:
        raise _error(e, timeout_ms) from e

def _version(conn, info: dict) -> str | None:

    cols = info["columns"]
    if "cdm_version" in cols.get("cdm_source", []):
        try:
            with conn.begin_nested():
                raw = conn.execute(text(
                    f"SELECT cdm_version FROM {_cdm(info, 'cdm_source')} "
                    "WHERE cdm_version IS NOT NULL LIMIT 1")).scalar()
            m = re.search(r"(\d+)\.(\d+)", raw or "")
            if m:
                return f"{m[1]}.{m[2]}"
        except Exception as e:
            logger.info("cdm_source unreadable, using column heuristics: %s", e)
    visit = cols.get("visit_occurrence", [])
    if "admitted_from_concept_id" in visit:
        return "5.4"
    if "admitting_source_concept_id" in visit:
        return "5.3"
    if "procedure_end_date" in cols.get("procedure_occurrence", []):
        return "5.4"
    return None

def _row_counts(conn, schema: str, tables: list[str]) -> dict[str, tuple]:

    est = dict(conn.execute(text(
        "SELECT c.relname, c.reltuples FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = :s AND c.relname = ANY(:t)"),
        {"s": schema, "t": tables}).fetchall())
    out = {}
    for t in tables:
        rows = est.get(t)
        if rows is not None and rows >= EXACT_COUNT_BELOW:
            out[t] = (int(rows), True)
            continue
        try:
            with conn.begin_nested():
                out[t] = (int(conn.execute(text(
                    f"SELECT count(*) FROM {_q(schema)}.{_q(t)}")).scalar()), False)
        except Exception:
            out[t] = (None, True)
    return out

def detect(engine: Engine) -> dict | None:

    if engine.dialect.name != "postgresql":
        return None
    with _session(engine, DETECT_TIMEOUT_MS) as conn:
        rows = conn.execute(text(
            "SELECT table_schema, table_name, column_name "
            "FROM information_schema.columns "
            "WHERE table_name = ANY(:names) "
            "AND table_schema NOT IN ('pg_catalog', 'information_schema') "
            "ORDER BY table_schema, table_name, ordinal_position"),
            {"names": list(KNOWN_TABLES)}).fetchall()
        schemas: dict[str, dict[str, list[str]]] = {}
        for schema, table, column in rows:
            schemas.setdefault(schema, {}).setdefault(table, []).append(column)
        domain_tables = {d["table"] for d in DOMAINS.values()}
        cdm = [s for s, t in schemas.items()
               if {"person", "observation_period"} <= set(t)
               and "person_id" in t["person"] and domain_tables & set(t)]
        if not cdm:
            return None
        cdm_schema = sorted(cdm, key=lambda s: (-len(schemas[s]), s))[0]
        vocab = [s for s, t in schemas.items() if {"concept", "concept_ancestor"} <= set(t)]
        vocab_schema = (cdm_schema if cdm_schema in vocab
                        else (sorted(vocab)[0] if vocab else None))
        columns = {t: c for t, c in schemas[cdm_schema].items() if t not in VOCAB_TABLES}
        if vocab_schema:
            columns |= {t: c for t, c in schemas[vocab_schema].items() if t in VOCAB_TABLES}
        info = {"cdm": True, "cdm_schema": cdm_schema, "vocab_schema": vocab_schema,
                "columns": columns}
        info["version"] = _version(conn, info)
        by_schema: dict[str, list[str]] = {}
        for t in columns:
            by_schema.setdefault(vocab_schema if t in VOCAB_TABLES else cdm_schema,
                                 []).append(t)
        tables = []
        for schema, names in by_schema.items():
            counts = _row_counts(conn, schema, names)
            tables += [{"name": t, "schema": schema, "domain": KNOWN_TABLES[t],
                        "rows": counts[t][0], "approx": counts[t][1]} for t in names]
    order = list(KNOWN_TABLES)
    info["tables"] = sorted(tables, key=lambda t: order.index(t["name"]))
    return info

def public(info: dict | None) -> dict:

    if info is None:
        return {"cdm": False}
    return {k: info[k] for k in ("cdm", "cdm_schema", "vocab_schema", "version", "tables")}

@ttl_cache(ttl=DETECT_TTL, maxsize=64)
def detect_resource(resource_id: str) -> dict | None:
    info = detect(db.get_engine_for_resource(resource_id))
    _remember(resource_id, info)
    return info

_hints: dict[str, tuple[float, dict | None]] = {}
_inflight: set[str] = set()
_hint_lock = threading.Lock()

def _remember(resource_id: str, info: dict | None):
    summary = None
    if info:
        person = next((t for t in info["tables"] if t["name"] == "person"), {})
        summary = {"cdm_schema": info["cdm_schema"], "vocab_schema": info["vocab_schema"],
                   "version": info["version"], "persons": person.get("rows")}
    with _hint_lock:
        _hints[resource_id] = (time.monotonic() + DETECT_TTL, summary)

def _detect_in_background(resource_id: str):
    try:
        detect_resource(resource_id)
    except Exception as e:
        logger.info("OMOP detection failed for %s: %s", resource_id, e)
        _remember(resource_id, None)
    finally:
        with _hint_lock:
            _inflight.discard(resource_id)

def hint(resource_id: str) -> dict | None:

    with _hint_lock:
        hit = _hints.get(resource_id)
        if (hit is None or hit[0] <= time.monotonic()) and resource_id not in _inflight:
            _inflight.add(resource_id)
            threading.Thread(target=_detect_in_background, args=(resource_id,),
                             daemon=True).start()
    return hit[1] if hit else None

def invalidate(resource_id: str | None = None):
    detect_resource.invalidate()
    with _hint_lock:
        if resource_id is None:
            _hints.clear()
        else:
            _hints.pop(resource_id, None)

def _like(word: str) -> str:
    return "%" + re.sub(r"([\\%_])", r"\\\1", word) + "%"

def _person_counts(engine: Engine, info: dict, results: list[dict]):

    by_table: dict[str, list[int]] = {}
    for r in results:
        key = next((k for k, v in DOMAIN_IDS.items() if v == r["domain_id"]), None)
        if key and DOMAINS[key]["table"] in info["columns"]:
            by_table.setdefault(key, []).append(r["concept_id"])
    if not by_table:
        return
    parts = []
    params = {}
    for index, (key, ids) in enumerate(by_table.items()):
        d = DOMAINS[key]
        bind = f"ids_{index}"
        parts.append(
            f"SELECT {_q(d['concept'])} AS concept_id, count(DISTINCT person_id) AS persons "
            f"FROM {_cdm(info, d['table'])} "
            f"WHERE {_q(d['concept'])} = ANY(CAST(:{bind} AS BIGINT[])) GROUP BY 1")
        params[bind] = ids
    counts: dict[int, int] = {}
    try:
        with _session(engine, SEARCH_TIMEOUT_MS) as conn:
            counts = dict(conn.execute(text(" UNION ALL ".join(parts)), params).fetchall())
    except (OmopTimeout, OmopEngineError) as e:
        logger.info("Concept person counts skipped: %s", e)
        return
    for r in results:
        key = next((k for k, v in DOMAIN_IDS.items() if v == r["domain_id"]), None)
        if key in by_table:
            r["persons"] = int(counts.get(r["concept_id"], 0))

def search_concepts(engine: Engine, info: dict, q: str = "", domain: str | None = None,
                    vocabulary: str | None = None, standard_only: bool = True,
                    limit: int = 50, persons: bool = True) -> list[dict]:

    if not info.get("vocab_schema"):
        raise ValueError("This database has no OMOP vocabulary tables "
                         "(concept, concept_ancestor).")
    q = (q or "").strip()
    if len(q) > 200:
        raise ValueError("Search text is limited to 200 characters.")
    params = {"limit": max(1, min(int(limit), MAX_SEARCH))}
    where, order = [], []
    if q:
        words = q.split()[:8]
        params |= {f"w{i}": _like(w) for i, w in enumerate(words)}
        name = " AND ".join(f"c.concept_name ILIKE :w{i}" for i in range(len(words)))
        match = [f"({name})", "c.concept_code = :q"]
        params["q"] = q
        if q.isdigit() and len(q) <= 10:
            match.append("c.concept_id = :qid")
            params["qid"] = int(q)
            order.append("(c.concept_id = :qid) DESC")
        where.append("(" + " OR ".join(match) + ")")
        order += ["(c.concept_code = :q) DESC", "(lower(c.concept_name) = lower(:q)) DESC"]
    if domain:
        where.append("c.domain_id = :domain")
        params["domain"] = DOMAIN_IDS.get(domain.lower(), domain)
    if vocabulary:
        where.append("c.vocabulary_id = :vocabulary")
        params["vocabulary"] = vocabulary
    if standard_only:
        where.append("c.standard_concept = 'S'")
    order += ["length(c.concept_name)", "c.concept_id"]
    sql = (f"SELECT c.concept_id, c.concept_name, c.domain_id, c.vocabulary_id, "
           f"c.concept_class_id, c.concept_code, c.standard_concept "
           f"FROM {_voc(info, 'concept')} AS c "
           f"WHERE {' AND '.join(where) or 'TRUE'} "
           f"ORDER BY {', '.join(order)} LIMIT :limit")
    with _session(engine, SEARCH_TIMEOUT_MS) as conn:
        res = conn.execute(text(sql), params)
        results = [dict(r._mapping) | {"persons": None} for r in res]
    if persons and results:
        _person_counts(engine, info, results)
    return results

def _int(value, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or (isinstance(value, float) and not value.is_integer()):
        raise ValueError(f"{what} must be an integer.")
    return int(value)

def _number(value, what: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{what} must be a number.")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{what} must be a finite number.")
    return value

def _date(value, what: str) -> dt.date | None:
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{what} must be an ISO date (YYYY-MM-DD).")
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{what} must be an ISO date (YYYY-MM-DD).") from None

def _bool(value, default: bool, what: str) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"{what} must be true or false.")
    return value

def _ids(value, what: str) -> list[int]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{what} must be a list of concept ids.")
    if len(value) > MAX_CONCEPTS:
        raise ValueError(f"{what}: at most {MAX_CONCEPTS} concept ids.")
    return list(dict.fromkeys(_int(v, what) for v in value))

def _range(lo, hi, what: str):
    if lo is not None and hi is not None and lo > hi:
        raise ValueError(f"{what}: the minimum is greater than the maximum.")

def parse_spec(spec: dict | None) -> dict:

    spec = {} if spec is None else spec
    if not isinstance(spec, dict):
        raise ValueError("The cohort spec must be a JSON object.")
    if set(spec) - _SPEC_KEYS:
        raise ValueError(f"Unknown cohort spec key(s): {', '.join(sorted(set(spec) - _SPEC_KEYS))}.")
    raw = spec.get("criteria", [])
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise ValueError("criteria must be a list.")
    if len(raw) > MAX_CRITERIA:
        raise ValueError(f"At most {MAX_CRITERIA} criteria.")
    criteria = []
    for n, c in enumerate(raw, start=1):
        what = f"Criterion {n}"
        if not isinstance(c, dict):
            raise ValueError(f"{what} must be an object.")
        if set(c) - _CRITERION_KEYS:
            raise ValueError(f"{what}: unknown key(s) "
                             f"{', '.join(sorted(set(c) - _CRITERION_KEYS))}.")
        domain = c.get("domain")
        if domain not in DOMAINS:
            raise ValueError(f"{what}: domain must be one of {', '.join(DOMAINS)}.")
        ids = _ids(c.get("concept_ids"), f"{what} concept_ids")
        if not ids and domain != "death":
            raise ValueError(f"{what}: pick at least one concept.")
        out = {"domain": domain, "concept_ids": ids,
               "descendants": _bool(c.get("descendants"), True, f"{what} descendants"),
               "exclude": _bool(c.get("exclude"), False, f"{what} exclude"),
               "min_count": _int(c.get("min_count", 1), f"{what} min_count"),
               "value_min": _number(c.get("value_min"), f"{what} value_min"),
               "value_max": _number(c.get("value_max"), f"{what} value_max"),
               "start": _date(c.get("start"), f"{what} start"),
               "end": _date(c.get("end"), f"{what} end"),
               "index_relation": c.get("index_relation")}
        if out["min_count"] < 1:
            raise ValueError(f"{what}: min_count must be at least 1.")
        if (out["value_min"] is not None or out["value_max"] is not None) \
                and "value" not in DOMAINS[domain]:
            raise ValueError(f"{what}: value_min/value_max apply to measurement only.")
        if out["index_relation"] not in (None, "before", "after"):
            raise ValueError(f"{what}: index_relation must be 'before', 'after' or null.")
        _range(out["value_min"], out["value_max"], f"{what} value")
        _range(out["start"], out["end"], f"{what} dates")
        criteria.append(out)
    first = next((i for i, c in enumerate(criteria) if not c["exclude"]), None)
    if first is not None and criteria[first]["index_relation"]:
        raise ValueError(f"Criterion {first + 1} defines the index date, so it "
                         "can't be relative to it.")
    demo = spec.get("demographics", {})
    if demo is None:
        demo = {}
    if not isinstance(demo, dict):
        raise ValueError("demographics must be an object.")
    if set(demo) - _DEMOGRAPHIC_KEYS:
        raise ValueError(f"Unknown demographics key(s): "
                         f"{', '.join(sorted(set(demo) - _DEMOGRAPHIC_KEYS))}.")
    demographics = {
        "gender_concept_ids": _ids(demo.get("gender_concept_ids"), "gender_concept_ids"),
        "age_min": _number(demo.get("age_min"), "age_min"),
        "age_max": _number(demo.get("age_max"), "age_max"),
        "year_of_birth_min": (None if demo.get("year_of_birth_min") is None
                              else _int(demo["year_of_birth_min"], "year_of_birth_min")),
        "year_of_birth_max": (None if demo.get("year_of_birth_max") is None
                              else _int(demo["year_of_birth_max"], "year_of_birth_max")),
    }
    _range(demographics["age_min"], demographics["age_max"], "age")
    _range(demographics["year_of_birth_min"], demographics["year_of_birth_max"],
           "year of birth")
    return {"criteria": criteria, "demographics": demographics,
            "require_observation": _bool(spec.get("require_observation"), True,
                                         "require_observation")}

def _check_tables(info: dict, spec: dict):
    need = {"person"} | ({"observation_period"} if spec["require_observation"] else set())
    need |= {DOMAINS[c["domain"]]["table"] for c in spec["criteria"]}
    if any(c["index_relation"] for c in spec["criteria"]) \
            and all(c["exclude"] for c in spec["criteria"]):
        need.add("observation_period")
    for t in sorted(need):
        if t not in info["columns"]:
            raise ValueError(f"This CDM has no {t} table.")
    if not info.get("vocab_schema") and any(c["descendants"] and c["concept_ids"]
                                            for c in spec["criteria"]):
        raise ValueError("Descendant expansion needs the concept_ancestor table; "
                         "set descendants to false.")

def _concept_names(conn, info: dict, ids: list[int]) -> dict[int, str]:
    if not ids or not info.get("vocab_schema"):
        return {}
    return dict(conn.execute(text(
        f"SELECT concept_id, concept_name FROM {_voc(info, 'concept')} "
        "WHERE concept_id = ANY(CAST(:ids AS BIGINT[]))"), {"ids": ids}).fetchall())

def _labels(conn, info: dict, spec: dict) -> list[str]:

    names = _concept_names(conn, info, sorted({i for c in spec["criteria"]
                                                for i in c["concept_ids"]}))
    labels, used = [], set()
    for c in spec["criteria"]:
        ids = c["concept_ids"]
        if not ids:
            base = c["domain"].capitalize()
        else:
            base = str(names.get(ids[0]) or f"concept {ids[0]}")
            if len(base) > LABEL_CHARS:
                base = base[:LABEL_CHARS - 1].rstrip() + "…"
            if len(ids) > 1:
                base += f" +{len(ids) - 1}"
        label, n = base, 2
        while label in used:
            label, n = f"{base} ({n})", n + 1
        used.add(label)
        labels.append(label)
    return labels

def _step_label(c: dict, label: str) -> str:
    out = f"{'Without' if c['exclude'] else 'With'} {label}"
    extra = []
    if c["min_count"] > 1:
        extra.append(f"≥{c['min_count']} events")
    if c["value_min"] is not None or c["value_max"] is not None:
        extra.append(f"value {_fmt(c['value_min'])}–{_fmt(c['value_max'])}")
    if c["start"] or c["end"]:
        extra.append(f"{c['start'] or '…'} to {c['end'] or '…'}")
    if c["index_relation"]:
        extra.append(f"{c['index_relation']} index")
    return out + (f" ({', '.join(extra)})" if extra else "")

def _fmt(v) -> str:
    return "…" if v is None else f"{v:g}"

def compile_spec(info: dict, spec: dict, labels: list[str]) -> dict:

    params: dict = {}

    def p(value) -> str:
        name = f"p{len(params)}"
        params[name] = value
        return f":{name}"

    criteria = spec["criteria"]
    first = next((i for i, c in enumerate(criteria) if not c["exclude"]), None)
    ctes = []
    if "observation_period" in info["columns"]:
        ctes.append(
            "obs AS (SELECT person_id, min(observation_period_start_date) AS observation_start, "
            "max(observation_period_end_date) AS observation_end "
            f"FROM {_cdm(info, 'observation_period')} GROUP BY person_id)")

    order = ([first] if first is not None else []) + \
        [i for i in range(len(criteria)) if i != first]
    for i in order:
        c = criteria[i]
        d = DOMAINS[c["domain"]]
        date = f"t.{_q(d['date'])}"
        where, join = [], ""
        if c["concept_ids"]:
            ids = p(c["concept_ids"])
            col = f"t.{_q(d['concept'])}"
            if c["descendants"]:
                where.append(
                    f"{col} IN (SELECT descendant_concept_id FROM {_voc(info, 'concept_ancestor')} "
                    f"WHERE ancestor_concept_id = ANY(CAST({ids} AS BIGINT[])) "
                    f"UNION ALL SELECT unnest(CAST({ids} AS BIGINT[])))")
            else:
                where.append(f"{col} = ANY(CAST({ids} AS BIGINT[]))")
        if c["value_min"] is not None:
            where.append(f"t.{_q(d['value'])} >= {p(c['value_min'])}")
        if c["value_max"] is not None:
            where.append(f"t.{_q(d['value'])} <= {p(c['value_max'])}")
        if c["start"]:
            where.append(f"{date} >= {p(c['start'])}")
        if c["end"]:
            where.append(f"{date} <= {p(c['end'])}")
        if spec["require_observation"] and c["domain"] != "death":
            where.append(
                f"EXISTS (SELECT 1 FROM {_cdm(info, 'observation_period')} AS op "
                f"WHERE op.person_id = t.person_id AND {date} "
                "BETWEEN op.observation_period_start_date AND op.observation_period_end_date)")
        if c["index_relation"]:
            ix = f"e{first}" if first is not None else "obs"
            ix_date = "ix.first_date" if first is not None else "ix.observation_start"
            op = "<" if c["index_relation"] == "before" else ">"
            join = f" JOIN {ix} AS ix ON ix.person_id = t.person_id AND {date} {op} {ix_date}"
        ctes.append(
            f"e{i} AS (SELECT t.person_id, count(*) AS n, min({date}) AS first_date "
            f"FROM {_cdm(info, d['table'])} AS t{join} "
            f"WHERE {' AND '.join(where) or 'TRUE'} "
            f"GROUP BY t.person_id HAVING count(*) >= {p(c['min_count'])})")
    has_obs = "observation_period" in info["columns"]
    index = (f"e{first}.first_date" if first is not None
             else ("o.observation_start" if has_obs else "NULL"))
    cols = ["p.person_id", "p.gender_concept_id", "p.race_concept_id",
            "p.ethnicity_concept_id", "p.year_of_birth",
            "o.observation_start" if has_obs else "NULL AS observation_start",
            "o.observation_end" if has_obs else "NULL AS observation_end",
            f"{index} AS index_date"]
    joins = ["LEFT JOIN obs AS o ON o.person_id = p.person_id"] if has_obs else []
    for i in range(len(criteria)):
        cols += [f"e{i}.n AS e{i}_n", f"e{i}.first_date AS e{i}_first"]
        joins.append(f"LEFT JOIN e{i} ON e{i}.person_id = p.person_id")
    ctes.append(f"pop AS (SELECT {', '.join(cols)} FROM {_cdm(info, 'person')} AS p "
                f"{' '.join(joins)})")

    steps = []
    if spec["require_observation"]:
        steps.append(("With an observation period", "observation_start IS NOT NULL"))
    for i, c in enumerate(criteria):
        steps.append((_step_label(c, labels[i]),
                      f"e{i}_n IS {'' if c['exclude'] else 'NOT '}NULL"))
    demo = spec["demographics"]
    if demo["gender_concept_ids"]:
        steps.append(("Gender", f"gender_concept_id = ANY(CAST("
                                f"{p(demo['gender_concept_ids'])} AS BIGINT[]))"))
    lo, hi = demo["year_of_birth_min"], demo["year_of_birth_max"]
    if lo is not None or hi is not None:
        conds = ([f"year_of_birth >= {p(lo)}"] if lo is not None else []) + \
                ([f"year_of_birth <= {p(hi)}"] if hi is not None else [])
        steps.append((f"Born {lo or '…'}–{hi or '…'}", " AND ".join(conds)))
    lo, hi = demo["age_min"], demo["age_max"]
    if lo is not None or hi is not None:
        age = "(CAST(EXTRACT(YEAR FROM index_date) AS INTEGER) - year_of_birth)"
        conds = ([f"{age} >= {p(lo)}"] if lo is not None else []) + \
                ([f"{age} <= {p(hi)}"] if hi is not None else [])
        steps.append((f"Age {_fmt(lo)}–{_fmt(hi)} at index", " AND ".join(conds)))
    flags = "".join(f", ({expr}) AS f{k}" for k, (_, expr) in enumerate(steps))
    ctes.append(f"flags AS (SELECT pop.*{flags} FROM pop)")
    inclusion = [(i, labels[i]) for i, c in enumerate(criteria) if not c["exclude"]]
    return {"ctes": ctes, "params": params, "steps": steps, "inclusion": inclusion}

def _members(steps: list, upto: int | None = None) -> str:
    n = len(steps) if upto is None else upto + 1
    return " AND ".join(f"f{k}" for k in range(n)) or "TRUE"

def _prepare(conn, info: dict, spec: dict | None) -> dict:
    spec = parse_spec(spec)
    _check_tables(info, spec)
    return compile_spec(info, spec, _labels(conn, info, spec))

def count(engine: Engine, info: dict, spec: dict | None,
          timeout_ms: int | None = None) -> dict:

    timeout_ms = timeout_ms or COUNT_TIMEOUT_MS
    with _session(engine, timeout_ms) as conn:
        c = _prepare(conn, info, spec)
        sums = ["count(*)"] + [f"count(*) FILTER (WHERE {_members(c['steps'], k)})"
                               for k in range(len(c["steps"]))]
        row = conn.execute(text(f"WITH {', '.join(c['ctes'])} "
                                f"SELECT {', '.join(sums)} FROM flags"),
                           c["params"]).fetchone()
    attrition = [{"label": label, "persons": int(n)}
                 for (label, _), n in zip(c["steps"], row[1:])]
    return {"persons": int(row[-1]), "total_persons": int(row[0]),
            "attrition": attrition}

def cohort_summary(engine: Engine, info: dict, spec: dict | None) -> dict:
    spec = {} if spec is None else spec
    deadline = time.monotonic() + SUMMARY_TIMEOUT_MS / 1000
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            conn.exec_driver_sql(f"SET LOCAL statement_timeout = {SUMMARY_TIMEOUT_MS}")
            c = _prepare(conn, info, spec)
            def execute(sql, params):
                remaining = int((deadline - time.monotonic()) * 1000)
                if remaining < 1:
                    raise OmopTimeout(f"The query took longer than {SUMMARY_TIMEOUT_MS / 1000:g} s.")
                conn.exec_driver_sql(f"SET LOCAL statement_timeout = {remaining}")
                return conn.execute(text(sql), params)

            attrition_sql = ", ".join(
                ["count(*)"] + [f"count(*) FILTER (WHERE {_members(c['steps'], k)})"
                                  for k in range(len(c["steps"]))])
            row = execute(f"WITH {', '.join(c['ctes'])} "
                          f"SELECT {attrition_sql} FROM flags", c["params"]).fetchone()
            attrition = [{"label": label, "persons": int(n)}
                         for (label, _), n in zip(c["steps"], row[1:])]
            charts_ctes = ", ".join(c["ctes"] + [
                "cohort AS (SELECT DISTINCT ON (person_id) person_id, "
                "gender_concept_id, year_of_birth, index_date FROM flags "
                f"WHERE {_members(c['steps'])} ORDER BY person_id)"])
            concept_join = (f"LEFT JOIN {_voc(info, 'concept')} AS v "
                            "ON v.concept_id = cohort.gender_concept_id"
                            if info.get("vocab_schema") else "")
            gender_label = ("COALESCE(MAX(v.concept_name), "
                            "CASE WHEN cohort.gender_concept_id IS NULL "
                            "OR cohort.gender_concept_id <= 0 THEN 'Unknown / not recorded' "
                            "ELSE CAST(cohort.gender_concept_id AS TEXT) END)"
                            if info.get("vocab_schema") else
                            "CASE WHEN cohort.gender_concept_id IS NULL "
                            "OR cohort.gender_concept_id <= 0 THEN 'Unknown / not recorded' "
                            "ELSE CAST(cohort.gender_concept_id AS TEXT) END")
            genders = execute(
                f"WITH {charts_ctes} SELECT cohort.gender_concept_id, {gender_label} AS category, "
                "count(DISTINCT cohort.person_id) AS persons FROM cohort "
                f"{concept_join} GROUP BY cohort.gender_concept_id "
                "ORDER BY persons DESC, cohort.gender_concept_id NULLS FIRST",
                c["params"]).fetchall()
            bins = [
                ("under_18", "Under 18", None, 17),
                ("18_29", "18–29", 18, 29),
                ("30_44", "30–44", 30, 44),
                ("45_59", "45–59", 45, 59),
                ("60_74", "60–74", 60, 74),
                ("75_plus", "75+", 75, None),
                ("unknown", "Unknown", None, None),
            ]
            values = ", ".join(
                f"({i}, :label_{i}, :lo_{i}, :hi_{i})" for i in range(len(bins)))
            bin_params = {f"label_{i}": label for i, (_, label, _, _) in enumerate(bins)}
            bin_params.update({f"lo_{i}": lo for i, (_, _, lo, _) in enumerate(bins)})
            bin_params.update({f"hi_{i}": hi for i, (_, _, _, hi) in enumerate(bins)})
            age = "(CAST(EXTRACT(YEAR FROM index_date) AS INTEGER) - year_of_birth)"
            age_conditions = []
            for i, (_, _, lo, hi) in enumerate(bins[:-1]):
                if lo is None:
                    interval = f"{age} <= :hi_{i}"
                elif hi is None:
                    interval = f"{age} >= :lo_{i}"
                else:
                    interval = f"{age} >= :lo_{i} AND {age} <= :hi_{i}"
                age_conditions.append(f"(b.bin = {i} AND {age} IS NOT NULL AND {interval})")
            age_join = " OR ".join(age_conditions)
            age_join += f" OR (b.bin = {len(bins) - 1} AND {age} IS NULL)"
            age_rows = execute(
                f"WITH {charts_ctes}, bins AS (SELECT * FROM (VALUES {values}) "
                "AS b(bin, category, lo, hi)) SELECT b.bin, b.category, b.lo, b.hi, "
                f"count(DISTINCT cohort.person_id) AS persons FROM bins b LEFT JOIN cohort ON ({age_join}) "
                "GROUP BY b.bin, b.category, b.lo, b.hi ORDER BY b.bin",
                c["params"] | bin_params).fetchall()
            domain_charts = []
            for domain in dict.fromkeys(item["domain"] for item in (spec.get("criteria") or [])):
                d = DOMAINS[domain]
                concept_col = f"e.{_q(d['concept'])}"
                label = (f"COALESCE(MAX(v.concept_name), CAST({concept_col} AS TEXT))"
                         if info.get("vocab_schema") else f"CAST({concept_col} AS TEXT)")
                concept_join = (f"LEFT JOIN {_voc(info, 'concept')} AS v "
                                f"ON v.concept_id = {concept_col}"
                                if info.get("vocab_schema") else "")
                top = execute(
                    f"WITH {charts_ctes} SELECT {concept_col}, {label} AS label, "
                    f"count(DISTINCT e.person_id) AS persons FROM {_cdm(info, d['table'])} AS e "
                    "JOIN cohort ON cohort.person_id = e.person_id "
                    f"{concept_join} WHERE {concept_col} IS NOT NULL "
                    f"GROUP BY {concept_col} ORDER BY persons DESC, {concept_col} LIMIT 10",
                    c["params"]).fetchall()
                domain_charts.append({"domain": domain, "label": domain.capitalize(),
                                      "concepts": [{"concept_id": int(cid), "label": name,
                                                    "persons": int(persons)}
                                                   for cid, name, persons in top]})
        return {"scope": "database", "persons": int(row[-1]),
                "total_persons": int(row[0]), "attrition": attrition,
                "charts": {
                    "gender": [{"concept_id": cid, "category": category,
                                "persons": int(persons)}
                               for cid, category, persons in genders],
                    "age_at_index": [{"category": category, "lo": lo, "hi": hi,
                                      "persons": int(persons)}
                                     for _, category, lo, hi, persons in age_rows],
                    "domains": domain_charts,
                }}
    except (ValueError, OmopTimeout, OmopEngineError):
        raise
    except Exception as e:
        raise _error(e, SUMMARY_TIMEOUT_MS) from e

def _read(conn, sql: str, params: dict) -> pd.DataFrame:
    res = conn.execute(text(sql), params)
    return pd.DataFrame.from_records([tuple(r) for r in res.fetchall()],
                                     columns=list(res.keys()), coerce_float=True)

def _cohort_select(info: dict, c: dict) -> tuple[str, dict]:
    if info.get("vocab_schema"):
        names = [f"{a}.concept_name AS {n}" for a, n in
                 (("g", "gender"), ("r", "race"), ("en", "ethnicity"))]
        joins = " ".join(
            f"LEFT JOIN {_voc(info, 'concept')} AS {a} ON {a}.concept_id = f.{col}"
            for a, col in (("g", "gender_concept_id"), ("r", "race_concept_id"),
                           ("en", "ethnicity_concept_id")))
    else:
        names = [f"CAST(f.{col}_concept_id AS TEXT) AS {col}"
                 for col in ("gender", "race", "ethnicity")]
        joins = ""
    cols = (["f.person_id"] + names + [
        "f.year_of_birth",
        "CAST(EXTRACT(YEAR FROM f.index_date) AS INTEGER) - f.year_of_birth AS age",
        "f.index_date", "f.observation_start", "f.observation_end"]
        + [f"f.e{i}_n AS e{i}_n, f.e{i}_first AS e{i}_first"
           for i, _ in c["inclusion"]]
        + ["f.gender_concept_id", "f.race_concept_id", "f.ethnicity_concept_id"])
    sql = (f"WITH {', '.join(c['ctes'])} SELECT {', '.join(cols)} "
           f"FROM flags AS f {joins} WHERE {_members(c['steps'])} "
           "ORDER BY f.person_id")
    rename = {}
    for i, label in c["inclusion"]:
        rename |= {f"e{i}_n": f"{label} events", f"e{i}_first": f"{label} first"}
    return sql, rename


def _cohort_frame(df: pd.DataFrame, rename: dict) -> pd.DataFrame:
    df = df.rename(columns=rename)
    for col in ["index_date", "observation_start", "observation_end"] + \
               [name for name in rename.values() if name.endswith(" first")]:
        df[col] = pd.to_datetime(df[col])
    return df


def _cohort_data(engine: Engine, info: dict, spec: dict | None,
                 cap: int) -> tuple[pd.DataFrame, str, dict, dict]:
    if cap < 0:
        raise ValueError("Row limit must be non-negative.")
    with _session(engine, OPEN_TIMEOUT_MS) as conn:
        c = _prepare(conn, info, spec)
        sql, rename = _cohort_select(info, c)
        df = _read(conn, f"{sql} LIMIT {int(cap)}", c["params"])
    df = _cohort_frame(df, rename)
    return df, sql, c["params"], rename


def open_cohort(engine: Engine, info: dict, spec: dict | None,
                cap: int = queries.ROW_CAP) -> pd.DataFrame:
    return _cohort_data(engine, info, spec, cap)[0]


def open_cohort_source(engine: Engine, info: dict, resource_id: str,
                       spec: dict | None,
                       cap: int = queries.ROW_CAP) -> tuple[pd.DataFrame, dict]:
    df, sql, params, rename = _cohort_data(engine, info, spec, cap)
    physical_names = {logical: physical for physical, logical in rename.items()}
    live_source = {"resource_id": resource_id, "sql": sql, "params": params,
                   "columns": {column: physical_names.get(column, column)
                               for column in df.columns}}
    import disk_data
    source_ref = {"kind": "omop_cohort", "resource_id": resource_id,
                  "spec": parse_spec(spec), "membership_mode": "live"}
    live_source = disk_data._compiled_omop_query(source_ref, live_source)
    return df, live_source

def open_domain(engine: Engine, info: dict, table: str, spec: dict | None = None,
                cap: int = queries.ROW_CAP, concept_names: bool = True,
                resource_id: str | None = None) -> tuple[pd.DataFrame, dict | None]:

    if table not in OPENABLE or table not in info["columns"]:
        raise ValueError(f"{table!r} is not a person-level table of this CDM.")
    enrich = concept_names and bool(info.get("vocab_schema"))
    select, joins = [], []
    for k, col in enumerate(info["columns"][table]):
        select.append(f"t.{_q(col)}")
        if enrich and col.endswith("_concept_id"):
            a = f"n{k}"
            joins.append(f"LEFT JOIN {_voc(info, 'concept')} AS {a} "
                         f"ON {a}.concept_id = t.{_q(col)}")
            select.append(f"{a}.concept_name AS {_q(col[:-3] + '_name')}")
    with _session(engine, OPEN_TIMEOUT_MS) as conn:
        params, with_, where = {}, "", ""
        if spec is not None:
            c = _prepare(conn, info, spec)
            params, with_ = c["params"], f"WITH {', '.join(c['ctes'])} "
            where = (" WHERE t.person_id IN (SELECT person_id FROM flags "
                     f"WHERE {_members(c['steps'])})")
        df = _read(conn, f"{with_}SELECT {', '.join(select)} FROM {_cdm(info, table)} AS t "
                         f"{' '.join(joins)}{where} LIMIT {int(cap)}", params)
    origin = None
    if spec is None and not enrich and resource_id:
        origin = {"kind": "aurora", "resource_id": resource_id,
                  "schema": info["cdm_schema"], "table": table}
    return df, origin

def tables_used(info: dict, spec: dict | None) -> list[str]:

    spec = parse_spec(spec)
    names = ["person"] + [DOMAINS[c["domain"]]["table"] for c in spec["criteria"]]
    if "observation_period" in info["columns"]:
        names.append("observation_period")
    ids = any(c["concept_ids"] for c in spec["criteria"])
    if ids and info.get("vocab_schema"):
        vocab_names = ["concept"]
        if any(c["concept_ids"] and c["descendants"] for c in spec["criteria"]):
            vocab_names.append("concept_ancestor")
        return ([f"{info['cdm_schema']}.{t}" for t in dict.fromkeys(names)]
                + [f"{info['vocab_schema']}.{t}" for t in vocab_names])
    return [f"{info['cdm_schema']}.{t}" for t in dict.fromkeys(names)]
