from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Literal

import config
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import inspect
from sqlalchemy.sql.sqltypes import Boolean, Date, DateTime, Float, Integer, LargeBinary, Numeric, String, Time

import database as db
from source_models import ColumnSetting

METADATA_TIMEOUT_MS = 3000
JEV_TIMEOUT_SECONDS = 8
TYPESAFE_SYSTEMONE_URL = "https://api.typesafe.ai/v1/systemone"
MAX_COLUMNS_PER_TABLE = 64
MAX_JEV_PAIRS = 40
MAX_CANDIDATES = 3
_ROLES = ("person", "sample", "variant", "clinical_event", "concept", "other", "unknown")
_lock = threading.RLock()
_metadata_cache: dict[str, dict] = {}
_recommendation_cache: dict[str, dict] = {}


class AuroraTableRef(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["aurora"]
    resource_id: str = Field(min_length=1, max_length=256)
    table: str = Field(min_length=1, max_length=2048)
    schema_name: str = Field(default="public", alias="schema", min_length=1, max_length=128)
    uuid: str | None = None
    settings: list[ColumnSetting] = Field(default_factory=list, max_length=200)


class RecommendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    left: AuroraTableRef
    right: AuroraTableRef
    refresh: bool = False


class JoinKeyPair(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    left: str = Field(min_length=1, max_length=512)
    right: str = Field(min_length=1, max_length=512)


class JoinCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    keys: list[JoinKeyPair] = Field(min_length=1, max_length=12)
    method: Literal["foreign_key", "exact_name", "jev"]
    evidence: list[str] = Field(max_length=12)
    confidence: float | None = Field(default=None, ge=0, le=1)


class JevStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["not_configured", "unavailable", "used"]
    configured: bool
    model: str


class JoinRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    candidates: list[JoinCandidate] = Field(max_length=MAX_CANDIDATES)
    warnings: list[str] = Field(max_length=32)
    jev: JevStatus


def _ttl() -> int:
    try:
        return max(0, min(300, int(os.environ.get("STUDIO_JOIN_DISCOVERY_CACHE_TTL", "30"))))
    except (TypeError, ValueError):
        return 30


def invalidate_resource(resource_id: str) -> None:
    with _lock:
        for cache in (_metadata_cache, _recommendation_cache):
            for key, value in list(cache.items()):
                if resource_id in value.get("resources", ()):
                    cache.pop(key, None)


def _q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _family(type_obj) -> str | None:
    try:
        affinity = type_obj._type_affinity
    except (AttributeError, NotImplementedError):
        return None
    if issubclass(affinity, (Integer, Numeric, Float)):
        return "number"
    if issubclass(affinity, String):
        return "text"
    if issubclass(affinity, (Date, DateTime, Time)):
        return "time"
    if issubclass(affinity, Boolean):
        return "boolean"
    if issubclass(affinity, LargeBinary):
        return "binary"
    return None


def _compatible(left: dict, right: dict) -> bool:
    return bool(left.get("family") and left["family"] == right.get("family"))


def _key_candidate(column: dict) -> bool:
    name = column["name"]
    return (name.casefold() != "id"
            and bool(re.search(r"(?:_id|Id|_key|Key)$", name)
                     or column.get("primary_key") or column.get("unique")))


def _key(ref: AuroraTableRef) -> str:
    return f"{ref.resource_id}\0{ref.schema_name}\0{ref.table}"


def _signature(metadata: dict) -> str:
    stable = {key: value for key, value in metadata.items()
              if key not in {"resource_id", "probe_non_null"}}
    return hashlib.sha256(json.dumps(stable, sort_keys=True, default=str,
                                     separators=(",", ":")).encode()).hexdigest()


def _read_metadata(ref: AuroraTableRef) -> dict:
    engine = db.get_engine_for_resource(ref.resource_id)
    if engine.dialect.name != "postgresql":
        raise ValueError("Join discovery supports Aurora PostgreSQL tables only.")
    with engine.connect() as conn:
        conn.exec_driver_sql("SET TRANSACTION READ ONLY")
        conn.exec_driver_sql(f"SET LOCAL statement_timeout = {METADATA_TIMEOUT_MS}")
        inspector = inspect(conn)
        if not inspector.has_table(ref.table, schema=ref.schema_name):
            raise ValueError(f"Table not found: {ref.schema_name}.{ref.table}.")
        raw_columns = inspector.get_columns(ref.table, schema=ref.schema_name)
        if not raw_columns:
            raise ValueError(f"Table has no readable columns: {ref.schema_name}.{ref.table}.")
        metadata_warnings = []
        def optional(reader, fallback, warning):
            savepoint = conn.begin_nested()
            try:
                value = reader()
            except Exception:
                savepoint.rollback()
                metadata_warnings.append(warning)
                return fallback
            savepoint.commit()
            return value

        primary_constraint = optional(
            lambda: inspector.get_pk_constraint(ref.table, schema=ref.schema_name),
            {}, "Primary-key metadata is unavailable.")
        primary = set(primary_constraint.get("constrained_columns") or [])
        unique_groups = optional(
            lambda: inspector.get_unique_constraints(ref.table, schema=ref.schema_name),
            [], "Unique-constraint metadata is unavailable.")
        indexes = optional(
            lambda: inspector.get_indexes(ref.table, schema=ref.schema_name),
            [], "Index metadata is unavailable.")
        foreign_keys = optional(
            lambda: inspector.get_foreign_keys(ref.table, schema=ref.schema_name),
            [], "Foreign-key metadata is unavailable.")
        comment = optional(
            lambda: inspector.get_table_comment(ref.table, schema=ref.schema_name).get("text"),
            None, "Table description is unavailable.")
        unique = {name for item in unique_groups
                  for name in item.get("column_names") or []}
        unique_single = {item["column_names"][0] for item in unique_groups
                         if len(item.get("column_names") or []) == 1}
        unique_single.update(index["column_names"][0] for index in indexes
                             if index.get("unique")
                             and len(index.get("column_names") or []) == 1)
        indexed = {name for index in indexes
                   for name in index.get("column_names") or [] if name}
        selectable = [col for col in raw_columns
                      if _family(col["type"]) not in (None, "binary")]
        probe_sql = ", ".join(
            f"{_q(col['name'])} IS NOT NULL AS {_q(f'probe_{i}')}"
            for i, col in enumerate(selectable[:128]))
        row = (conn.exec_driver_sql(
            f"SELECT {probe_sql} FROM {_q(ref.schema_name)}.{_q(ref.table)} LIMIT 1").first()
               if probe_sql else None)
        probe_non_null = ({col["name"]: bool(row[i])
                           for i, col in enumerate(selectable[:128])}
                          if row is not None else {})
        if len(selectable) > 128:
            metadata_warnings.append("Non-null probing was limited to 128 compatible columns.")
    columns = [{
        "name": col["name"], "type": str(col["type"]),
        "family": _family(col["type"]),
        "nullable": bool(col.get("nullable", True)),
        "primary_key": len(primary) == 1 and col["name"] in primary,
        "primary_key_component": col["name"] in primary,
        "primary_key_columns": sorted(primary),
        "unique": col["name"] in unique_single,
        "unique_component": col["name"] in unique,
        "indexed": col["name"] in indexed,
        "probe_non_null": probe_non_null.get(col["name"]),
    } for col in raw_columns]
    unique_constraints = [item.get("column_names") or [] for item in unique_groups]
    return {"resource_id": ref.resource_id, "schema": ref.schema_name,
            "table": ref.table, "comment": comment, "columns": columns,
            "foreign_keys": foreign_keys, "metadata_warnings": metadata_warnings,
            "unique_constraints": unique_constraints,
            "probe_has_row": row is not None}


def _metadata(ref: AuroraTableRef, refresh: bool) -> dict:
    key = _key(ref)
    ttl = _ttl()
    now = time.monotonic()
    with _lock:
        cached = _metadata_cache.get(key)
        if not refresh and ttl and cached and now - cached["stored"] < ttl:
            return copy.deepcopy(cached["value"])
    value = _read_metadata(ref)
    if ttl:
        with _lock:
            _metadata_cache[key] = {"value": copy.deepcopy(value),
                                    "stored": now,
                                    "resources": (ref.resource_id,)}
            while len(_metadata_cache) > 128:
                oldest = min(_metadata_cache, key=lambda item: _metadata_cache[item]["stored"])
                _metadata_cache.pop(oldest, None)
    return value


def _columns(metadata: dict) -> dict:
    return {column["name"]: column for column in metadata["columns"]}


def _candidate(keys: list[dict], method: str, evidence: list[str],
               confidence: float | None = None) -> dict:
    return {"keys": keys, "method": method, "evidence": evidence,
            "confidence": confidence}


def _deterministic(left_ref: AuroraTableRef, right_ref: AuroraTableRef,
                   left: dict, right: dict) -> list[dict]:
    lc, rc = _columns(left), _columns(right)
    out = []
    if left_ref.resource_id == right_ref.resource_id:
        for source, target, reverse in ((left, right_ref, False),
                                        (right, left_ref, True)):
            for fk in source["foreign_keys"]:
                schema = fk.get("referred_schema") or "public"
                if fk.get("referred_table") != target.table or schema != target.schema_name:
                    continue
                constrained = fk.get("constrained_columns") or []
                referred = fk.get("referred_columns") or []
                pairs = list(zip(referred, constrained) if reverse
                             else zip(constrained, referred))
                if pairs and all(a in lc and b in rc for a, b in pairs):
                    out.append(_candidate(
                        [{"left": a, "right": b} for a, b in pairs],
                        "foreign_key", ["Declared foreign key" +
                                        (f" {fk['name']}" if fk.get("name") else "")]))
    seen = {tuple((x["left"], x["right"]) for x in item["keys"]) for item in out}
    foreign_key_pairs = {(x["left"], x["right"])
                         for item in out for x in item["keys"]}
    for name, col in lc.items():
        other = rc.get(name)
        key_shaped = bool(re.search(r"(?:_id|Id|_key|Key)$", name))
        if (name.casefold() == "id" or other is None or not _compatible(col, other)
                or (name, name) in foreign_key_pairs
                or not (key_shaped or col["primary_key"] or other["primary_key"]
                        or col["unique"] or other["unique"])):
            continue
        pair = ((name, name),)
        if pair in seen:
            continue
        evidence = ["Exact column name", f"Compatible type: {col['family']}"]
        if col["primary_key"] or other["primary_key"]:
            evidence.append("Primary-key column")
        elif col["unique"] or other["unique"]:
            evidence.append("Unique column")
        elif col["indexed"] or other["indexed"]:
            evidence.append("Indexed column")
        out.append(_candidate([{"left": name, "right": name}], "exact_name", evidence))
    return out


def _decision(api_key: str, model: str, state: dict, questions: dict) -> dict:
    body = json.dumps({"model": model, "state": state, "questions": questions},
                      separators=(",", ":")).encode()
    request = urllib.request.Request(
        TYPESAFE_SYSTEMONE_URL, data=body,
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=JEV_TIMEOUT_SECONDS) as response:
            raw = response.read(1_000_001)
    except urllib.error.HTTPError as exc:
        raise ValueError(f"Jev request failed with HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ValueError("Jev request failed or timed out.") from exc
    if len(raw) > 1_000_000:
        raise ValueError("Jev response exceeded the size limit.")
    try:
        result = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("Jev returned invalid JSON.") from exc
    if not isinstance(result, dict) or not isinstance(result.get("answers"), dict):
        raise ValueError("Jev response did not contain typed answers.")
    return result["answers"]


def _choice(answer, options: set[str]):
    if not isinstance(answer, dict) or answer.get("type") != "choice":
        return None
    choice, confidence, probabilities = (
        answer.get("choice"), answer.get("confidence"), answer.get("probabilities"))
    if (not isinstance(choice, str) or choice not in options or isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(confidence) or not 0 <= confidence <= 1
            or not isinstance(probabilities, dict) or set(probabilities) != options):
        return None
    values = {}
    for key, value in probabilities.items():
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not 0 <= value <= 1):
            return None
        values[key] = float(value)
    if abs(sum(values.values()) - 1.0) > 0.01 or values[choice] + 1e-9 < max(values.values()):
        return None
    return choice, float(confidence), values


def _question(identifier: str) -> dict:
    return {
        "type": "choice",
        "instructions": (f"Classify identifier {identifier!r} from schema metadata only. "
                         "This must be a record key, not an entity attribute."),
        "criteria": {
            "person": "A key that identifies a human, patient, person, or subject record.",
            "sample": "A key that identifies a biospecimen, sample, or aliquot record.",
            "variant": "A key that identifies a genetic variant or genomic locus record.",
            "clinical_event": "A key that identifies a clinical record or event, such as condition, drug, measurement, or visit.",
            "concept": "A key that identifies a vocabulary or ontology concept record.",
            "other": "A key for another record type.",
            "unknown": "The role cannot be inferred from schema metadata.",
        },
    }


def _jev_column(name: str, col: dict) -> dict:
    return {"name": name, "sql_type": col["type"],
            "primary_key": col["primary_key"], "unique": col["unique"],
            "indexed": col["indexed"],
            "sample_row_non_null": col["probe_non_null"]}


def _jev(left_ref: AuroraTableRef, right_ref: AuroraTableRef,
         left: dict, right: dict, warnings: list[str], api_key: str,
         model: str) -> list[dict]:
    if not api_key:
        warnings.append("Jev is not configured; add a token in Settings.")
        return []
    if not model:
        warnings.append("Jev is not configured; select a TypeSafe model in Settings.")
        return []
    lc, rc = _columns(left), _columns(right)
    order_l = sorted(lc, key=lambda n: (
        not (lc[n]["primary_key"] or lc[n]["unique"] or lc[n]["indexed"]), n))
    order_r = sorted(rc, key=lambda n: (
        not (rc[n]["primary_key"] or rc[n]["unique"] or rc[n]["indexed"]), n))
    order_l = [name for name in order_l if name.casefold() != "id"]
    order_r = [name for name in order_r if name.casefold() != "id"]
    if len(order_l) > MAX_COLUMNS_PER_TABLE or len(order_r) > MAX_COLUMNS_PER_TABLE:
        warnings.append("Jev classification is limited to the first 64 key-prioritized columns per table.")
    order_l, order_r = order_l[:MAX_COLUMNS_PER_TABLE], order_r[:MAX_COLUMNS_PER_TABLE]
    state = {
        "left": {"table": left_ref.table, "schema": left_ref.schema_name,
                 "description": left.get("comment"),
                 "columns": [_jev_column(n, lc[n]) for n in order_l]},
        "right": {"table": right_ref.table, "schema": right_ref.schema_name,
                  "description": right.get("comment"),
                  "columns": [_jev_column(n, rc[n]) for n in order_r]},
    }
    questions = ({f"l{i}": _question(f"{left_ref.schema_name}.{left_ref.table}.{n}")
                  for i, n in enumerate(order_l)}
                 | {f"r{i}": _question(f"{right_ref.schema_name}.{right_ref.table}.{n}")
                    for i, n in enumerate(order_r)})
    try:
        answers = _decision(api_key, model, state, questions)
    except ValueError as exc:
        warnings.append(str(exc) + " Showing metadata matches only.")
        return []
    classes = {"left": {}, "right": {}}
    invalid_classification = False
    for side, names, prefix in (("left", order_l, "l"), ("right", order_r, "r")):
        for i, name in enumerate(names):
            result = _choice(answers.get(f"{prefix}{i}"), set(_ROLES))
            if result:
                role_probability = result[2][result[0]]
                if result[0] not in {"other", "unknown"} and role_probability >= 0.6:
                    classes[side][name] = (result[0], role_probability)
            else:
                invalid_classification = True
    if invalid_classification:
        warnings.append("Jev returned an invalid classification; Jev abstained.")
        return []
    pairs = []
    for lname in order_l:
        lrole = classes["left"].get(lname)
        if not lrole or lrole[0] in {"other", "unknown"}:
            continue
        for rname in order_r:
            rrole = classes["right"].get(rname)
            if (not rrole or rrole[0] != lrole[0] or
                    rrole[0] in {"other", "unknown"} or
                    not _key_candidate(lc[lname]) or not _key_candidate(rc[rname]) or
                    not _compatible(lc[lname], rc[rname])):
                continue
            pairs.append({"left": lname, "right": rname, "role": lrole[0],
                          "class_probability": min(lrole[1], rrole[1])})
    pairs.sort(key=lambda x: (-x["class_probability"], x["left"], x["right"]))
    pairs = pairs[:MAX_JEV_PAIRS]
    if not pairs:
        return []
    pair_options = {f"pair_{i}": f"{pair['left']} matches {pair['right']} "
                    f"(both classified as {pair['role']})"
                    for i, pair in enumerate(pairs)}
    pair_options["none"] = "No defensible join-key pair"
    try:
        ranked = _decision(api_key, model, {"source_metadata": state, "candidate_pairs": [
            {"id": key, "description": value}
            for key, value in pair_options.items()]}, {
                "best_pair": {"type": "choice",
                              "instructions": "Choose the key pair most likely to identify the same entity. Choose none if evidence is weak or ambiguous. Similar names alone are not proof.",
                              "criteria": pair_options}})
    except ValueError as exc:
        warnings.append(str(exc) + " Jev abstained; showing metadata matches only.")
        return []
    else:
        ranked_choice = _choice(ranked.get("best_pair"), set(pair_options))
        if not ranked_choice:
            warnings.append("Jev returned an invalid ranking; showing metadata matches only.")
            return []
        if ranked_choice[0] == "none":
            return []
    probabilities = ranked_choice[2]
    chosen = ranked_choice[0]
    if probabilities.get("none", 0) > probabilities.get(chosen, 0) or probabilities[chosen] < 0.5:
        return []
    indices = sorted(range(len(pairs)),
                     key=lambda i: (-probabilities.get(f"pair_{i}", 0), i))
    out = []
    for i in list(indices)[:MAX_CANDIDATES]:
        probability = probabilities.get(f"pair_{i}")
        if probability <= 0:
            continue
        pair = pairs[i]
        out.append(_candidate(
            [{"left": pair["left"], "right": pair["right"]}], "jev",
            [f"Jev classified both columns as {pair['role']}",
             f"Compatible type: {lc[pair['left']]['family']}",
             f"Jev pair probability: {probability:.3f}; not a match rate",
             "No row overlap or cardinality was measured"], probability))
    return out


def recommend(req: RecommendRequest) -> JoinRecommendation:
    left, right = _metadata(req.left, req.refresh), _metadata(req.right, req.refresh)
    model = config.get_jev_model()
    api_key = (config.get_integration_key("jev") or "").strip()
    signature = hashlib.sha256(json.dumps([
        req.left.resource_id, req.right.resource_id,
        _signature(left), _signature(right), model,
        bool(api_key), hashlib.sha256(api_key.encode()).hexdigest() if api_key else "",
    ], separators=(",", ":")).encode()).hexdigest()
    ttl = _ttl()
    if not req.refresh and ttl:
        with _lock:
            cached = _recommendation_cache.get(signature)
            if cached and time.monotonic() - cached["stored"] < ttl:
                return JoinRecommendation.model_validate(cached["value"])
    warnings = ["A LIMIT 1 probe checks only one row; overlap, uniqueness, and cardinality were not measured."]
    warnings.extend(left["metadata_warnings"])
    warnings.extend(right["metadata_warnings"])
    if not left["probe_has_row"] or not right["probe_has_row"]:
        warnings.append("At least one table had no row for the bounded probe.")
    deterministic = _deterministic(req.left, req.right, left, right)
    warning_start = len(warnings)
    jev = _jev(req.left, req.right, left, right, warnings, api_key, model)
    if not api_key or not model:
        jev_status = "not_configured"
    elif any("Jev request failed" in item or "Jev returned" in item or "Jev response" in item
             for item in warnings[warning_start:]):
        jev_status = "unavailable"
    else:
        jev_status = "used"
    candidates = deterministic + jev
    seen, unique = set(), []
    for candidate in candidates:
        key = tuple((pair["left"], pair["right"]) for pair in candidate["keys"])
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    result = JoinRecommendation.model_validate({
        "candidates": unique[:MAX_CANDIDATES], "warnings": warnings,
        "jev": {"status": jev_status,
                "configured": bool(api_key and model),
                "model": model}})
    if ttl:
        resources = (req.left.resource_id, req.right.resource_id)
        with _lock:
            _recommendation_cache[signature] = {
                "value": result.model_dump(mode="json"),
                "stored": time.monotonic(), "resources": resources}
            while len(_recommendation_cache) > 128:
                oldest = min(_recommendation_cache,
                             key=lambda item: _recommendation_cache[item]["stored"])
                _recommendation_cache.pop(oldest, None)
    return result
