import pytest

import omop
from omop_matching import required_columns, resolve, suggestions


def test_suggestions_require_required_columns_and_never_select_ambiguous_names():
    columns = list(required_columns()["condition_occurrence"])
    tables = {"condition_occurence": columns, "condition_occurrences": columns,
              "condition_occurrenc": ["person_id"]}
    found = suggestions(tables, {"condition_occurrence"})
    assert set(found["condition_occurrence"]) == {"condition_occurence", "condition_occurrences"}
    tables["condition_occurrence"] = columns
    assert suggestions(tables, {"condition_occurrence"}) == {}


def test_ddl_signatures_cover_key_omop_tables():
    signatures = required_columns()
    assert len(signatures) == 39
    assert {"person_id", "year_of_birth", "gender_concept_id"} <= signatures["person"]
    assert {"concept_id", "concept_name", "domain_id"} <= signatures["concept"]


def test_ambiguous_names_are_not_resolved():
    columns = list(required_columns()["condition_occurrence"])
    mapping, ambiguous = resolve({"condition_occurence": columns, "condition_occurrences": columns},
                                 {"condition_occurrence"})
    assert mapping == {}
    assert len(ambiguous["condition_occurrence"]) == 2


def test_renamed_tables_count_real_cohort_and_mapping_drift_is_rejected(engine):
    schema = "omop_matching_test"
    names = {"person": "persons", "observation_period": "observation_period",
             "condition_occurrence": "condition_occurence", "concept": "concept",
             "concept_ancestor": "concept_ancestor"}
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            for original, renamed in names.items():
                conn.exec_driver_sql(f'CREATE TABLE "{schema}"."{renamed}" (LIKE cdm."{original}" INCLUDING ALL)')
                conn.exec_driver_sql(f'INSERT INTO "{schema}"."{renamed}" SELECT * FROM cdm."{original}"')
        info = omop.detect(engine, schema)
        assert info["table_mapping"]["person"] == "persons"
        assert info["table_mapping"]["condition_occurrence"] == "condition_occurence"
        spec = {"criteria": [{"domain": "condition", "concept_ids": [192671]}]}
        report = omop.compatibility(info, spec)
        assert report["percent"] == 100 and report["meets_threshold"]
        assert omop.count(engine, info, spec)["persons"] == 40
        pinned = omop.pin_table_mapping(info, spec)
        with engine.begin() as conn:
            conn.exec_driver_sql(f'ALTER TABLE "{schema}".condition_occurence RENAME TO condition_occurrences')
        changed = omop.detect(engine, schema)
        with pytest.raises(ValueError, match="mappings have changed"):
            omop.pin_table_mapping(changed, spec, pinned)
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def test_compatibility_uses_only_selected_features_and_checks_required_columns(info):
    report = omop.compatibility(info, {"criteria": [{"domain": "condition", "concept_ids": [192671]}]})
    assert report["percent"] == 100
    assert "drug_exposure" not in report["required_tables"]
    broken = {**info, "columns": {**info["columns"], "condition_occurrence": ["person_id"]}}
    report = omop.compatibility(broken, {"criteria": [{"domain": "condition", "concept_ids": [192671]}]})
    assert report["matched"] == report["total"] - 1
    assert report["missing_columns"]["condition_occurrence"] == ["condition_concept_id", "condition_start_date"]
    with pytest.raises(ValueError, match="missing columns"):
        omop._check_tables(broken, omop.parse_spec({"criteria": [{"domain": "condition", "concept_ids": [192671]}]}))


def test_relations_follow_cohort_criteria_and_saved_legacy_mapping(info):
    spec = {"criteria": [
        {"domain": "condition", "concept_ids": [192671]},
        {"domain": "measurement", "concept_ids": [3006322], "descendants": False,
         "exclude": True, "index_relation": "after"}]}
    graph = omop.cohort_relations(info, spec)
    assert graph["start"] == "cdm.person"
    rows = graph["relations"]
    assert any(r["operation"] == "LEFT JOIN" and "condition_occurrence" in r["right"] for r in rows)
    assert any(r["operation"] == "EXISTS" and "observation_period" in r["right"] for r in rows)
    assert sum(r["operation"] == "IN subquery" for r in rows) == 1
    assert any(r["operation"] == "INNER JOIN" and "after index" in r["condition"] for r in rows)
    assert any("Exclude;" in r["detail"] and "measurement" in r["right"] for r in rows)
    assert sum(r["operation"] == "LEFT JOIN" and r["right"].endswith(".concept") for r in rows) == 3
    current = omop.pin_table_mapping(info, {})
    assert "concept" in current
    legacy = {key: value for key, value in current.items() if key != "concept"}
    assert omop.pin_table_mapping(info, {}, legacy) == current
