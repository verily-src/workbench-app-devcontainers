import csv
import gzip
import hashlib
import json
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text

import omop
import synpuf_load


def _export(directory, outsider=False):
    directory.mkdir(parents=True, exist_ok=True)
    people = [{"person_id": i, "birth_datetime": "1950-01-01T00:00:00",
               "source_value": "" if i == 1 else None}
              for i in range(1, 100_001)]
    tables = [
        ("person", [("person_id", "INTEGER"), ("birth_datetime", "DATETIME"),
                    ("source_value", "STRING")], people),
        ("observation_period", [("observation_period_id", "INTEGER"),
                                ("person_id", "INTEGER"),
                                ("observation_period_start_date", "DATE"),
                                ("observation_period_end_date", "DATE")], [
            {"observation_period_id": 1, "person_id": 1,
             "observation_period_start_date": "2000-01-01",
             "observation_period_end_date": "2020-01-01"},
        ]),
        ("condition_occurrence", [("condition_occurrence_id", "INTEGER"),
                                  ("person_id", "INTEGER"),
                                  ("condition_concept_id", "INTEGER"),
                                  ("condition_start_date", "DATE"),
                                  ("condition_source_value", "STRING")], [
            {"condition_occurrence_id": 1, "person_id": 1,
             "condition_concept_id": 10, "condition_start_date": "2010-01-01",
             "condition_source_value": None},
            {"condition_occurrence_id": 2, "person_id": 100_000 if not outsider else 100_001,
             "condition_concept_id": 10, "condition_start_date": "2011-01-01",
             "condition_source_value": ""},
        ]),
        ("procedure_occurrence", [("procedure_occurrence_id", "INTEGER"),
                                  ("person_id", "INTEGER"),
                                  ("procedure_concept_id", "INTEGER"),
                                  ("procedure_dat", "DATE"),
                                  ("procedure_datetime", "DATETIME")], [
            {"procedure_occurrence_id": 1, "person_id": 2,
             "procedure_concept_id": 20, "procedure_dat": "2012-03-04",
             "procedure_datetime": "2012-03-04T10:11:12"},
        ]),
        ("concept", [("concept_id", "INTEGER"), ("concept_name", "STRING"),
                     ("domain_id", "STRING")], [
            {"concept_id": 10, "concept_name": "Condition", "domain_id": "Condition"},
            {"concept_id": 20, "concept_name": "Procedure", "domain_id": "Procedure"},
        ]),
        ("concept_ancestor", [("ancestor_concept_id", "INTEGER"),
                              ("descendant_concept_id", "INTEGER")], [
            {"ancestor_concept_id": 10, "descendant_concept_id": 10},
            {"ancestor_concept_id": 20, "descendant_concept_id": 20},
        ]),
    ]
    manifest_tables = []
    for name, columns, rows in tables:
        path = directory / f"{name}.csv.gz"
        with gzip.open(path, "wt", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow([column for column, _ in columns])
            for row in rows:
                writer.writerow([r"\N" if row[column] is None else row[column]
                                 for column, _ in columns])
        manifest_tables.append({
            "name": name,
            "columns": [{"name": column, "type": kind} for column, kind in columns],
            "file": path.name,
            "rows": len(rows),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    manifest = {
        "version": 1,
        "source": synpuf_load.SOURCE,
        "job_project": synpuf_load.JOB_PROJECT,
        "person_limit": synpuf_load.PERSON_LIMIT,
        "selection_sql": "SELECT person_id FROM approved_selection",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tables": manifest_tables,
    }
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def _load(engine, source_dir, schema):
    conn = engine.raw_connection()
    try:
        return synpuf_load.load(conn, source_dir, schema, log=lambda *_: None)
    finally:
        conn.close()


def test_import_streams_verified_export_and_detects_unversioned_omop(pg, tmp_path):
    schema = f"synpuf_test_{uuid.uuid4().hex[:8]}"
    engine = create_engine(pg["url"]("empty"))
    _export(tmp_path / "export")
    try:
        counts = _load(engine, tmp_path / "export", schema)
        assert counts == {
            "person": 100_000, "observation_period": 1,
            "condition_occurrence": 2, "procedure_occurrence": 1,
            "concept": 2, "concept_ancestor": 2,
        }
        with engine.connect() as conn:
            assert conn.execute(text(
                f'SELECT count(DISTINCT person_id) FROM "{schema}".person'
            )).scalar_one() == 100_000
            assert conn.execute(text(
                f'SELECT source_value FROM "{schema}".person WHERE person_id = 1'
            )).scalar_one() == ""
            assert conn.execute(text(
                f'SELECT condition_source_value FROM "{schema}".condition_occurrence '
                "WHERE condition_occurrence_id = 1"
            )).scalar_one() is None
            assert conn.execute(text(
                f'SELECT procedure_date, procedure_datetime FROM "{schema}".procedure_occurrence'
            )).one() == (datetime(2012, 3, 4).date(), datetime(2012, 3, 4, 10, 11, 12))
            names = {row[0] for row in conn.execute(text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = :schema"),
                {"schema": schema})}
            assert "cdm_source" not in names
            assert "visit_occurrence" not in names
            indexes = list(conn.execute(text(
                "SELECT tablename, indexdef FROM pg_indexes WHERE schemaname = :schema"),
                {"schema": schema}))
            assert any(table == "concept" and "(concept_id)" in definition
                       for table, definition in indexes)
            assert any(table == "procedure_occurrence" and "(procedure_date)" in definition
                       for table, definition in indexes)
            provenance = conn.execute(text(
                f'SELECT column_mappings FROM "{schema}"._synpuf_import_metadata'
            )).scalar_one()
            assert provenance["procedure_occurrence"]["procedure_dat"] == "procedure_date"
        detected = omop.detect(engine)
        assert detected["cdm"] is True
        assert detected["cdm_schema"] == schema
        assert detected["vocab_schema"] == schema
        assert detected["version"] is None
        with engine.begin() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
    finally:
        engine.dispose()


def test_outside_clinical_person_id_rolls_back_entire_schema(engine, tmp_path):
    schema = f"synpuf_bad_{uuid.uuid4().hex[:8]}"
    _export(tmp_path / "bad-export", outsider=True)
    with pytest.raises(ValueError, match="outside the selected people"):
        _load(engine, tmp_path / "bad-export", schema)
    with engine.connect() as conn:
        assert conn.execute(text(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name = :schema"),
            {"schema": schema}).first() is None


def test_hash_mismatch_and_existing_schema_do_not_mutate_target(engine, tmp_path):
    schema = f"synpuf_safe_{uuid.uuid4().hex[:8]}"
    export = tmp_path / "hash-export"
    manifest = _export(export)
    manifest["tables"][2]["sha256"] = "0" * 64
    (export / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        _load(engine, export, schema)
    with engine.connect() as conn:
        assert conn.execute(text(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name = :schema"),
            {"schema": schema}).first() is None

    with engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        conn.exec_driver_sql(f'CREATE TABLE "{schema}".sentinel (value integer)')
        conn.exec_driver_sql(f'INSERT INTO "{schema}".sentinel VALUES (42)')
    _export(export)
    with pytest.raises(ValueError, match="already exists"):
        _load(engine, export, schema)
    with engine.connect() as conn:
        assert conn.execute(text(f'SELECT value FROM "{schema}".sentinel')).scalar_one() == 42
    with engine.begin() as conn:
        conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
