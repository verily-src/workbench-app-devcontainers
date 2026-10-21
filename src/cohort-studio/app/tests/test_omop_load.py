"""OMOP load source validation, S3 transfer planning, and Postgres load path."""

import argparse
import csv
import gzip
import shutil
import zipfile
from pathlib import Path

import pytest
import psycopg
from sqlalchemy import text

import db
import omop_load

pytest_plugins = ("tests.test_omop",)

FIXTURE = Path(__file__).parent / "fixtures" / "omop"


@pytest.mark.parametrize("path", [
    "", "/absolute/file.zip", "../file.zip", "tables/../../file.zip",
    "tables\\person.csv", "s3://bucket/path", ".", "tables/./input.zip",
])
def test_s3_source_rejects_non_relative_paths(path):
    with pytest.raises(ValueError):
        omop_load.S3Source(resource_id="workspace-folder", path=path)


def test_s3_source_requires_strict_nonempty_values():
    with pytest.raises(ValueError):
        omop_load.S3Source(resource_id=" ", path="data/")
    with pytest.raises(ValueError):
        omop_load.S3Source(resource_id="bucket", path="data/", extra=True)
    with pytest.raises(ValueError):
        omop_load.S3Source(resource_id="bucket", path=3)


def test_open_sources_reads_nested_files_and_detects_duplicate_tables(tmp_path):
    nested = tmp_path / "export" / "clinical"
    nested.mkdir(parents=True)
    (nested / "person.csv").write_text("person_id\n1\n")
    sources = omop_load.open_sources(tmp_path / "export")
    assert list(sources) == ["person"]
    with sources["person"]() as stream:
        assert stream.read() == "person_id\n1\n"

    (tmp_path / "export" / "vocab").mkdir()
    (tmp_path / "export" / "vocab" / "person.csv.gz").write_bytes(b"not gzip")
    with pytest.raises(ValueError, match="Duplicate CSV source"):
        omop_load.open_sources(tmp_path / "export")


def test_open_sources_reads_nested_zip_and_detects_duplicate_tables(tmp_path):
    archive = tmp_path / "export.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("clinical/person.csv", "person_id\n1\n")
        zf.writestr("vocab/concept.csv", "concept_id,concept_name,domain_id\n")
    sources = omop_load.open_sources(archive)
    assert set(sources) == {"person", "concept"}
    with sources["person"]() as stream:
        assert stream.read() == "person_id\n1\n"

    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("a/person.csv", "person_id\n1\n")
        zf.writestr("b/person.csv", "person_id\n2\n")
    with pytest.raises(ValueError, match="Duplicate CSV source"):
        omop_load.open_sources(archive)


def test_s3_download_uses_resource_profile_and_csv_prefix_filters(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(db, "configure_aws_profiles", lambda: calls.append("profiles"))
    monkeypatch.setattr(db, "resolve_s3_uri", lambda rid: f"s3://bucket/{rid}")

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return argparse.Namespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(omop_load.subprocess, "run", fake_run)
    local = omop_load.download_s3_source("resource-1", "synpuf/cdm/", tmp_path)
    assert local == tmp_path / "csv-source"
    assert calls[0] == "profiles"
    args, kwargs = calls[1]
    assert args[:5] == ["aws", "s3", "cp", "s3://bucket/resource-1/synpuf/cdm/",
                        str(local)]
    assert args[args.index("--profile") + 1] == "resource-1"
    assert "--recursive" in args and "--exclude" in args
    assert all(ext in args for ext in (
        "*.[cC][sS][vV]", "*.[cC][sS][vV].[gG][zZ]"))
    assert kwargs["timeout"] == omop_load.S3_DOWNLOAD_TIMEOUT


def test_s3_download_uses_zip_object_path(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "configure_aws_profiles", lambda: None)
    monkeypatch.setattr(db, "resolve_s3_uri", lambda _rid: "s3://bucket/folder/")
    commands = []

    def fake_run(args, **kwargs):
        commands.append(args)
        Path(args[4]).write_bytes(b"zip")
        return argparse.Namespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(omop_load.subprocess, "run", fake_run)
    local = omop_load.download_s3_source("resource-1", "nested/source.zip", tmp_path)
    assert local == tmp_path / "source.zip"
    assert local.read_bytes() == b"zip"
    assert commands[0][3] == "s3://bucket/folder/nested/source.zip"
    assert "--recursive" not in commands[0]


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
