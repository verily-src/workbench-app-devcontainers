#!/usr/bin/env python3
"""
Generates 3 synthetic BigQuery tables used for the free-text -> condition concept_id ->
person_id lookup:

    cb_criteria           text search + participant-count ranking
    concept_ancestor      descendant expansion
    condition_occurrence  person_id retrieval

Output is newline-delimited JSON (NDJSON) for `bq load`.

Usage:
    python3 data/synthetic/generators/generate_condition_lookup_tables_synthetic.py

Defaults assume it's run from the repo root; both directories can be overridden.
"""

import argparse
import json
import os
import random
from datetime import date, timedelta

from use_cases import USE_CASES

# Small subset of concept IDs
CONGENITAL_HEART_DISEASE = 9000001
TETRALOGY_OF_FALLOT = 9000010
TOF_PULMONARY_ATRESIA = 9000011
TOF_ABSENT_PULMONARY_VALVE = 9000012
PENTALOGY_OF_FALLOT = 9000013
TOF_LATE_SEQUELAE = 9000014
TOF_UNSPECIFIED = 9000015
TOF_IN_ADULT = 9000016
FALLOT_TETRALOGY_REPAIRED = 9000018
T2DM = 9000030
T2DM_RENAL = 9000031

# Fake type concept, so 6.1 holds for every concept_id in the fixture including
# the OMOP bookkeeping ones.
EHR_ENCOUNTER_DIAGNOSIS = 9000900

# concept_id, name, est_count, role
CONCEPTS = [
    (CONGENITAL_HEART_DISEASE,
     "Congenital heart disease", 310,
     "over-broad parent"),
    (TETRALOGY_OF_FALLOT,
     "Tetralogy of Fallot", 205,
     "primary target"),
    (TOF_PULMONARY_ATRESIA,
     "Tetralogy of Fallot with pulmonary atresia", 25,
     "child of 9000010"),
    (TOF_ABSENT_PULMONARY_VALVE,
     "Tetralogy of Fallot with absent pulmonary valve", 8,
     "child of 9000010"),
    (PENTALOGY_OF_FALLOT,
     "Pentalogy of Fallot", 11,
     "decoy: has 'fallot', lacks 'tetralogy'"),
    (TOF_LATE_SEQUELAE,
     "Tetralogy of Fallot, late sequelae", 0,
     "decoy: zero count"),
    (TOF_UNSPECIFIED,
     "Tetralogy of Fallot, unspecified", -1,
     "edge case: est_count = -1"),
    (TOF_IN_ADULT,
     "Tetralogy of Fallot in adult", None,
     "edge case: est_count = NULL, must sort last"),
    (FALLOT_TETRALOGY_REPAIRED,
     "Fallot tetralogy, repaired", 8,
     "stopword regression: inverted word order, no 'of' anywhere"),
    (T2DM,
     "Type 2 diabetes mellitus", 1200,
     "high-prevalence anchor"),
    (T2DM_RENAL,
     "Type 2 diabetes mellitus with renal complications", 180,
     "child of 9000030"),
]

# Pipe-delimited synonyms
SYNONYMS = {
    TETRALOGY_OF_FALLOT: ["fallot tetralogy", "fallot's tetralogy", "tof"],
    T2DM: ["t2dm", "adult-onset diabetes"],
}

PATHS = {
    CONGENITAL_HEART_DISEASE: ["441840.4274025"],
    TETRALOGY_OF_FALLOT: ["441840.4274025.9000010",
                          "441840.4274025.9000019.9000010"],
    TOF_PULMONARY_ATRESIA: ["441840.4274025.9000010.9000011"],
    TOF_ABSENT_PULMONARY_VALVE: ["441840.4274025.9000010.9000012"],
    PENTALOGY_OF_FALLOT: ["441840.4274025.9000013"],
    TOF_LATE_SEQUELAE: ["441840.4274025.9000014"],
    TOF_UNSPECIFIED: ["441840.4274025.9000015"],
    TOF_IN_ADULT: ["441840.4274025.9000016"],
    FALLOT_TETRALOGY_REPAIRED: ["441840.4274025.9000018"],
    T2DM: ["441840.201826"],
    T2DM_RENAL: ["441840.201826.9000031"],
}

# ---------------------------------------------------------------------------
# Hierarchy (HANDOFF 6.4)
# ---------------------------------------------------------------------------
# ancestor -> [(descendant, levels)]. Self-rows at level 0 are added for every
# concept in build_concept_ancestor; code depends on that invariant, since
# seeding on a leaf must return the leaf.
#
# 9000013 descends from the shared parent but NOT from 9000010. That asymmetry
# is the point: it is what makes cohort([9000001]) differ from cohort([9000010]).
#
# 9000014/15/16/18 get self-rows only. They exist to exercise search ranking and
# filtering, and keeping them out of the hierarchy keeps the cohort counts exact.
ANCESTOR_EDGES = {
    CONGENITAL_HEART_DISEASE: [
        (TETRALOGY_OF_FALLOT, 1),
        (TOF_PULMONARY_ATRESIA, 2),
        (TOF_ABSENT_PULMONARY_VALVE, 2),
        (PENTALOGY_OF_FALLOT, 1),
    ],
    TETRALOGY_OF_FALLOT: [
        (TOF_PULMONARY_ATRESIA, 1),
        (TOF_ABSENT_PULMONARY_VALVE, 1),
    ],
    T2DM: [
        (T2DM_RENAL, 1),
    ],
}

# ---------------------------------------------------------------------------
# Participants (HANDOFF 6.5)
# ---------------------------------------------------------------------------
# Disjoint contiguous assignment so the expected counts are exact, not sampled.
#
# What the ranges below are built to produce, after expansion through concept_ancestor:
#
#   cohort([9000010]) -> 214   180 + 26 + 8; seed-only matching gives 180, which is the
#                              silent-undercount bug descendant expansion exists to prevent
#   cohort([9000001]) -> 225   also pulls in Pentalogy: the "don't seed on a parent" failure
#   cohort([9000030]) -> 1200  high-prevalence anchor
#   cohort([9000031]) -> 180   subset of the above
#
# Verified against BigQuery, not asserted here.
PERSON_RANGES = {
    TETRALOGY_OF_FALLOT: range(1, 181),        # 180
    TOF_PULMONARY_ATRESIA: range(181, 207),    # 26
    TOF_ABSENT_PULMONARY_VALVE: range(207, 215),  # 8
    PENTALOGY_OF_FALLOT: range(300, 311),      # 11
}

T2DM_POOL = range(1000, 5001)   # disjoint from the ranges above
T2DM_N = 1200
T2DM_RENAL_N = 180              # subset of the T2DM persons

# ---------------------------------------------------------------------------
# Demo use cases (use_cases/)
# ---------------------------------------------------------------------------
# Each use case's condition that isn't already defined above gets a standalone concept, with its
# own disjoint block of participants so its count is exact. Kept out of every hierarchy, so the
# counts documented above don't move.
USE_CASE_PERSON_BLOCK = 10_000   # participants start at 20000, 30000, ...
USE_CASE_PATH_PARENT = "441840.134057"  # a made-up "disorder of cardiovascular system" group

# Separate from CONCEPTS, and written after everything else in each table, so the rows above keep
# their ids.
USE_CASE_CONCEPTS = []
for _i, _case in enumerate([c for c in USE_CASES if c.condition.generate], start=2):
    _c = _case.condition
    USE_CASE_CONCEPTS.append((_c.concept_id, _c.name, _c.est_count, f"use case: {_case.key}"))
    if _c.synonyms:
        SYNONYMS[_c.concept_id] = list(_c.synonyms)
    PATHS[_c.concept_id] = [f"{USE_CASE_PATH_PARENT}.{_c.concept_id}"]
    _start = _i * USE_CASE_PERSON_BLOCK
    PERSON_RANGES[_c.concept_id] = range(_start, _start + _c.participants)

# ---------------------------------------------------------------------------
# Overlap between use cases
# ---------------------------------------------------------------------------
# A search can filter by several conditions, matching participants recorded with any of them,
# and shows each condition's own count beside the union. With every use case on its own block
# of participants the union would always equal the sum and that display would show nothing, so
# some of one use case's participants are drawn from another's instead of its own block:
# (condition, condition it shares with, how many). Each condition's own count is unchanged --
# the shared participants replace, rather than add to, its own -- so the fixtures still apply.
#
#   cohort([9000040, 9000060]) -> 214 + 131 - 13 = 332
SHARED_PARTICIPANTS = [
    (9000060, 9000040, 13),   # a tenth of long QT syndrome's participants also have HCM
]

FIRST_DATE = date(2015, 1, 1)
LAST_DATE = date(2024, 12, 31)

def full_text(concept_id, name):
    """Lowercased name plus pipe-delimited synonyms, as the real column is built."""
    parts = [name.lower()] + SYNONYMS.get(concept_id, [])
    return " | ".join(parts)


def build_cb_criteria():
    """
    One row per (concept, path).

    The search projects DISTINCT concept_id/name/est_count, so the duplicate
    rows for 9000010 collapse only because id and path are excluded from the
    SELECT. Every duplicate pair below is therefore identical in all three
    projected columns; making them differ would silently reintroduce the
    duplicate the fixture is meant to catch.
    """
    rows = []
    next_id = 1

    def concept_rows(concepts):
        nonlocal next_id
        for concept_id, name, est_count, _role in concepts:
            is_leaf = concept_id not in ANCESTOR_EDGES
            for path in PATHS[concept_id]:
                rows.append({
                    "id": next_id,
                    "parent_id": int(path.split(".")[-2]) if "." in path else None,
                    "domain_id": "CONDITION",   # UPPERCASE here, mixed case in `concept`
                    "is_standard": 1,
                    "type": "SNOMED",
                    "subtype": None,
                    "concept_id": concept_id,
                    "code": f"{concept_id % 1000000}00{concept_id % 7}",
                    "name": name,
                    "value": None,
                    "est_count": est_count,
                    "is_group": 0 if is_leaf else 1,
                    "is_selectable": 1,
                    "has_hierarchy": 1,
                    "has_ancestor_data": 0,
                    "path": path,
                    "synonyms": " | ".join(SYNONYMS.get(concept_id, [])) or None,
                    "item_count": est_count,
                    "rollup_count": est_count,
                    "full_text": full_text(concept_id, name),
                })
                next_id += 1

    concept_rows(CONCEPTS)

    # Group/header row: no concept_id. Its full_text deliberately matches the
    # fallot searches, so the `concept_id IS NOT NULL` filter is the only thing
    # keeping it out of the results.
    rows.append({
        "id": next_id,
        "parent_id": None,
        "domain_id": "CONDITION",
        "is_standard": 1,
        "type": "SNOMED",
        "subtype": None,
        "concept_id": None,
        "code": None,
        "name": "Fallot tetralogy and related anomalies",
        "value": None,
        "est_count": None,
        "is_group": 1,
        "is_selectable": 0,
        "has_hierarchy": 1,
        "has_ancestor_data": 0,
        "path": "441840.4274025.9000019",
        "synonyms": None,
        "item_count": None,
        "rollup_count": None,
        "full_text": "fallot tetralogy and related anomalies",
    })
    next_id += 1

    concept_rows(USE_CASE_CONCEPTS)
    rows.sort(key=lambda r: r["id"])
    return rows


def build_concept_ancestor():
    """Self-rows at level 0 for every concept, plus the declared edges."""
    rows = []
    for concept_id, _name, _count, _role in CONCEPTS + USE_CASE_CONCEPTS:
        rows.append({
            "ancestor_concept_id": concept_id,
            "descendant_concept_id": concept_id,
            "min_levels_of_separation": 0,
            "max_levels_of_separation": 0,
        })
    for ancestor, edges in ANCESTOR_EDGES.items():
        for descendant, levels in edges:
            rows.append({
                "ancestor_concept_id": ancestor,
                "descendant_concept_id": descendant,
                "min_levels_of_separation": levels,
                "max_levels_of_separation": levels,
            })
    rows.sort(key=lambda r: (r["ancestor_concept_id"], r["descendant_concept_id"]))
    return rows


def assign_persons(rng):
    """concept_id -> sorted list of person_ids. Deterministic given the seed."""
    assignment = {c: sorted(r) for c, r in PERSON_RANGES.items()}
    t2dm = sorted(rng.sample(list(T2DM_POOL), T2DM_N))
    assignment[T2DM] = t2dm
    assignment[T2DM_RENAL] = sorted(rng.sample(t2dm, T2DM_RENAL_N))
    for concept_id, shared_with, n in SHARED_PARTICIPANTS:
        own, other = assignment[concept_id], assignment[shared_with]
        if n > len(own) or n > len(other):
            raise SystemExit(f"ERROR: {concept_id} can't share {n} participants with {shared_with}")
        # The first n of the other's stand in for the first n of its own, keeping its count.
        assignment[concept_id] = sorted(other[:n] + own[n:])
    return assignment


def build_condition_occurrence(rng, assignment):
    """
    1-5 occurrence rows per (person, concept), with varied dates, so that
    DISTINCT person_id is doing real work rather than passing by accident.
    """
    span = (LAST_DATE - FIRST_DATE).days
    rows = []
    next_id = 1

    for concept_id in sorted(assignment):
        for person_id in assignment[concept_id]:
            for _ in range(rng.randint(1, 5)):
                start = FIRST_DATE + timedelta(days=rng.randint(0, span))
                has_end = rng.random() < 0.7
                end = start + timedelta(days=rng.randint(0, 30)) if has_end else None
                hour, minute = rng.randint(7, 19), rng.choice([0, 15, 30, 45])
                rows.append({
                    "condition_occurrence_id": next_id,
                    "person_id": person_id,
                    "condition_concept_id": concept_id,
                    "condition_start_date": start.isoformat(),
                    "condition_start_datetime":
                        f"{start.isoformat()} {hour:02d}:{minute:02d}:00",
                    "condition_end_date": end.isoformat() if end else None,
                    "condition_end_datetime":
                        f"{end.isoformat()} {hour:02d}:{minute:02d}:00"
                        if end else None,
                    "condition_type_concept_id": EHR_ENCOUNTER_DIAGNOSIS,
                    "condition_status_concept_id": None,
                    "stop_reason": None,
                    "provider_id": None,
                    "visit_occurrence_id": rng.randint(1, 500000),
                    "visit_detail_id": None,
                    "condition_source_value": f"SYN{concept_id % 100000}",
                    "condition_source_concept_id": concept_id,
                    "condition_status_source_value": None,
                })
                next_id += 1

    rows.sort(key=lambda r: (r["person_id"], r["condition_start_date"],
                             r["condition_occurrence_id"]))
    return rows


def write_ndjson(path, rows, schema_path=None):
    if schema_path:
        with open(schema_path) as fh:
            schema = json.load(fh)
        expected = {f["name"] for f in schema}
        produced = set(rows[0].keys())
        missing, extra = expected - produced, produced - expected
        if missing:
            raise SystemExit(f"ERROR: {path}: schema fields not generated: {sorted(missing)}")
        if extra:
            raise SystemExit(f"ERROR: {path}: generated fields not in schema: {sorted(extra)}")
        order = [f["name"] for f in schema]
        rows = [{k: r[k] for k in order} for r in rows]

    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    with open(path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    print(f"Wrote {len(rows):>5} rows to {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="data/synthetic/tables")
    ap.add_argument("--schema-dir", default="data/synthetic/schemas",
                    help="Directory of BQ schema JSONs, for field validation.")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rng = random.Random(args.seed)

    cb_rows = build_cb_criteria()
    ancestor_rows = build_concept_ancestor()
    occurrence_rows = build_condition_occurrence(rng, assign_persons(rng))

    outputs = [
        ("synthetic_cb_criteria.ndjson", cb_rows, "cb_criteria_schema.json"),
        ("synthetic_concept_ancestor.ndjson", ancestor_rows,
         "concept_ancestor_schema.json"),
        ("synthetic_condition_occurrence.ndjson", occurrence_rows,
         "condition_occurrence_schema.json"),
    ]
    for filename, rows, schema_name in outputs:
        write_ndjson(
            os.path.join(args.out_dir, filename),
            rows,
            os.path.join(args.schema_dir, schema_name) if args.schema_dir else None,
        )


if __name__ == "__main__":
    main()