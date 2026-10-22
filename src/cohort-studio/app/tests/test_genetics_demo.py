import uuid
import csv
import json

import pytest
from sqlalchemy import text
from pydantic import ValidationError

import genetics_demo


def test_demo_load_appears_in_schema_browser_and_joins_omop(client, engine, tmp_path):
    schema = f"genetics_demo_{uuid.uuid4().hex[:8]}"
    counts = {}
    try:
        raw = engine.raw_connection()
        try:
            counts = genetics_demo.load(raw, "cdm", schema, 2, 20, 77)
        finally:
            raw.close()
        assert counts == {"samples": 2, "variants": 20, "genotypes": 40}
        listed = client.get("/api/tables", params={"kind": "aurora", "resource_id": "omopdb"})
        assert listed.status_code == 200
        found = {(row["schema"], row["table"]) for row in listed.json()}
        assert (schema, "samples") in found
        assert (schema, "variants") in found
        opened = client.post("/api/datasets/open", json={
            "source_ref": {"kind": "aurora", "resource_id": "omopdb",
                           "schema": schema, "table": "samples"}})
        assert opened.status_code == 200
        assert opened.json()["rows"] == 2
        with engine.connect() as conn:
            joined = conn.execute(text(
                f'SELECT count(*) FROM "{schema}".genotypes g '
                f'JOIN "{schema}".samples s USING (sample_id) '
                'JOIN cdm.person p USING (person_id) '
                f'JOIN "{schema}".variants v USING (variant_id) '
                "WHERE v.demo_group = 'planted_demo_pattern' AND g.dosage = 2"
            )).scalar_one()
            assert joined == 20
            assert conn.execute(text(
                f'SELECT count(*) FROM "{schema}".demo_pattern_summary '
                "WHERE dosage = 2")).scalar_one() == 20
            assert conn.execute(text(
                f'SELECT count(*) FROM "{schema}".variants '
                "WHERE synthetic_gene LIKE 'SYN_GENE_%' "
                "AND synthetic_consequence IN ('missense','synonymous','splice')"
            )).scalar_one() == 20
        exported = tmp_path / "genetics-csv"
        raw = engine.raw_connection()
        try:
            manifest = genetics_demo.export_csv(raw, exported, schema)
        finally:
            raw.close()
        assert manifest["counts"] == counts
        assert json.loads((exported / "manifest.json").read_text())["seed"] == 77
        with (exported / "samples.csv").open(newline="") as stream:
            assert len(list(csv.DictReader(stream))) == 2
        raw = engine.raw_connection()
        try:
            with pytest.raises(FileExistsError):
                genetics_demo.export_csv(raw, exported, schema)
        finally:
            raw.close()
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def test_demo_options_are_bounded_and_strict():
    with pytest.raises(ValidationError):
        genetics_demo.DemoOptions(sample_count=5001, variant_count=20, seed=1)
    with pytest.raises(ValidationError):
        genetics_demo.DemoOptions(sample_count=True, variant_count=20, seed=1)


def test_demo_loader_refuses_existing_target_and_rolls_back(engine):
    schema = f"genetics_demo_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        conn.exec_driver_sql(f'CREATE TABLE "{schema}".keep (value integer)')
        conn.exec_driver_sql(f'INSERT INTO "{schema}".keep VALUES (9)')
    try:
        raw = engine.raw_connection()
        try:
            with pytest.raises(ValueError, match="already exists"):
                genetics_demo.load(raw, "cdm", schema, 2, 20, 77)
        finally:
            raw.close()
        with engine.connect() as conn:
            assert conn.execute(text(f'SELECT value FROM "{schema}".keep')).scalar_one() == 9
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
