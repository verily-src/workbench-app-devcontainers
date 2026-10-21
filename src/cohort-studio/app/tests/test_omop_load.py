import argparse
import csv
import gzip
import shutil
from pathlib import Path

import pytest
import psycopg
from sqlalchemy import text

import db
import omop_load

FIXTURE = Path(__file__).parent / "fixtures" / "omop"


def test_non_omop_source_is_rejected_before_database_mutation(engine, tmp_path):
    raw_claims = tmp_path / "cms_synpuf"
    raw_claims.mkdir()
    (raw_claims / "beneficiary_summary.csv").write_text("DESYNPUF_ID\n1\n")
    conn = engine.raw_connection()
    try:
        with pytest.raises(ValueError, match="recognizable OMOP CDM"):
            omop_load.load(conn, raw_claims, "omop_reject_raw")
    finally:
        conn.close()
    with engine.connect() as conn:
        exists = conn.execute(text(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name = 'omop_reject_raw'"
        )).first()
    assert exists is None


def test_local_omop_fixture_loads_from_nested_csv_directory(engine, tmp_path):
    nested = tmp_path / "nested-export" / "files"
    nested.mkdir(parents=True)
    for source in FIXTURE.iterdir():
        if source.name.endswith((".csv", ".csv.gz")):
            if source.name == "person.csv.gz":
                continue
            shutil.copy2(source, nested / source.name)
    with gzip.open(FIXTURE / "person.csv.gz", "rt", encoding="utf-8",
                   newline="") as source, (nested / "person.csv").open(
                       "w", encoding="utf-8-sig", newline="") as target:
        target.write(source.read())

    conn = engine.raw_connection()
    try:
        counts = omop_load.load(conn, tmp_path / "nested-export", "omop_load_test")
    finally:
        conn.close()
    assert counts["person"] == 100
    assert counts["observation_period"] == 100
    with engine.connect() as conn:
        assert conn.execute(text(
            'SELECT count(*) FROM "omop_load_test"."person"'
        )).scalar_one() == 100


def test_replace_failure_rolls_back_and_preserves_previous_schema(engine, tmp_path):
    schema = "omop_load_rollback"
    with engine.begin() as conn:
        conn.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        conn.exec_driver_sql(f'CREATE TABLE "{schema}".sentinel (value integer)')
        conn.exec_driver_sql(f'INSERT INTO "{schema}".sentinel VALUES (73)')

    source = tmp_path / "bad-export"
    source.mkdir()
    for file in FIXTURE.iterdir():
        if not file.name.endswith(".csv.gz") or file.name == "condition_occurrence.csv.gz":
            continue
        shutil.copy2(file, source / file.name)
    event_file = source / "condition_occurrence.csv"
    with gzip.open(FIXTURE / "condition_occurrence.csv.gz", "rt", newline="") as gz:
        rows = list(csv.reader(gz))
    rows[1][rows[0].index("condition_start_date")] = "not-a-date"
    with event_file.open("w", newline="") as out:
        csv.writer(out).writerows(rows)

    conn = engine.raw_connection()
    try:
        with pytest.raises(psycopg.errors.InvalidDatetimeFormat):
            omop_load.load(conn, source, schema, replace=True)
    finally:
        conn.close()
    with engine.connect() as conn:
        assert conn.execute(text(
            f'SELECT value FROM "{schema}".sentinel'
        )).scalar_one() == 73
        assert conn.execute(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = :schema AND table_name = 'person'"),
            {"schema": schema}).first() is None


@pytest.mark.parametrize("malformation", ["short", "long"])
def test_ragged_csv_rejected_and_replace_rolls_back(
        engine, tmp_path, malformation):
    schema = f"omop_ragged_{malformation}"
    with engine.begin() as conn:
        conn.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        conn.exec_driver_sql(f'CREATE TABLE "{schema}".sentinel (value integer)')
        conn.exec_driver_sql(f'INSERT INTO "{schema}".sentinel VALUES (91)')

    source = tmp_path / "ragged-export"
    source.mkdir()
    for file in FIXTURE.iterdir():
        if file.name.endswith(".csv.gz") and file.name != "condition_occurrence.csv.gz":
            shutil.copy2(file, source / file.name)
    with gzip.open(FIXTURE / "condition_occurrence.csv.gz", "rt", newline="") as gz:
        rows = list(csv.reader(gz))
    if malformation == "short":
        rows[1].pop()
    else:
        rows[1].append("unexpected")
    event_file = source / "condition_occurrence.csv"
    with event_file.open("w", newline="") as out:
        csv.writer(out).writerows(rows)

    conn = engine.raw_connection()
    try:
        expected = len(rows[0])
        actual = expected - 1 if malformation == "short" else expected + 1
        with pytest.raises(ValueError, match=(
                rf"condition_occurrence CSV line 2: expected {expected} columns, got {actual}")):
            omop_load.load(conn, source, schema, replace=True)
    finally:
        conn.close()
    with engine.connect() as conn:
        assert conn.execute(text(
            f'SELECT value FROM "{schema}".sentinel'
        )).scalar_one() == 91
        assert conn.execute(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = :schema AND table_name = 'person'"),
            {"schema": schema}).first() is None


def test_resource_connection_keeps_pool_proxy_checked_out(engine, monkeypatch):
    monkeypatch.setattr(db, "get_engine_for_resource", lambda _rid: engine)
    before = engine.pool.checkedout()
    conn = omop_load._connect(argparse.Namespace(url=None, resource_id="aurora"))
    try:
        assert conn is not conn.driver_connection
        assert engine.pool.checkedout() == before + 1
    finally:
        conn.close()
    assert engine.pool.checkedout() == before
