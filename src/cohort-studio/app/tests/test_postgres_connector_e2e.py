import json
import os
import socket
import uuid
import subprocess
from pathlib import Path

import psycopg
import omop_load

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import datasets
import main
import postgres_sources


@pytest.fixture
def postgres_client(monkeypatch, tmp_path):
    port = os.environ.get("STUDIO_LOCAL_PG_PORT")
    port = port or "55433"
    database = "connector_" + uuid.uuid4().hex
    dsn = f"host=127.0.0.1 port={port} user=cohort_local password=cohort_local"
    with psycopg.connect(dsn + " dbname=postgres", autocommit=True) as connection:
        connection.execute('CREATE DATABASE "' + database + '"')
    with psycopg.connect(dsn + " dbname=" + database) as connection:
        omop_load.load(connection, Path(__file__).parent / "fixtures" / "omop", "cdm", log=lambda *_: None)
        connection.execute("CREATE SCHEMA genetics_demo")
        connection.execute("CREATE TABLE genetics_demo.samples AS SELECT person_id, person_id::text AS sample_id FROM cdm.person LIMIT 100")
    monkeypatch.setenv("STUDIO_CONNECTOR_TEST_URL",
                       f"postgresql://cohort_local:cohort_local@127.0.0.1:{port}/{database}")
    monkeypatch.setenv("STUDIO_POSTGRES_SOURCES", json.dumps([
        {"id": "connector-test", "url_env": "STUDIO_CONNECTOR_TEST_URL", "local_test": True}]))
    yield TestClient(main.app)
    datasets._store.clear()
    for engine in postgres_sources._engines.values():
        engine.dispose()
    postgres_sources._engines.clear()
    with psycopg.connect(dsn + " dbname=postgres", autocommit=True) as connection:
        connection.execute('DROP DATABASE "' + database + '" WITH (FORCE)')


def test_postgres_discover_open_join_reopen_and_readonly(postgres_client):
    client = postgres_client
    rid = "postgres:connector-test"
    sources = client.get("/api/datasources").json()["sources"]
    assert any(s["id"] == rid and s["kind"] == "postgres" for s in sources)
    assert "cohort_local:" not in json.dumps(sources)
    listed = client.get("/api/tables", params={"kind": "postgres", "resource_id": rid})
    assert listed.status_code == 200, listed.text
    assert any(t["schema"] == "cdm" and t["table"] == "person" for t in listed.json())
    handles = []
    for schema, table in [("cdm", "person"), ("genetics_demo", "samples")]:
        opened = client.post("/api/datasets/open", json={"source_ref": {
            "kind": "postgres", "resource_id": rid, "schema": schema, "table": table}})
        assert opened.status_code == 200, opened.text
        assert opened.json()["query_scope"] == "database"
        handles.append(opened.json()["dataset_id"])
    joined = client.post("/api/datasets/join", json={
        "left_id": handles[0], "right_id": handles[1],
        "left_on": "person_id", "right_on": "person_id", "how": "inner"})
    assert joined.status_code == 200, joined.text
    assert joined.json()["rows"] == 100
    assert joined.json()["query_scope"] == "database"
    reopened = client.post("/api/datasets/open", json={"source_ref": joined.json()["source_ref"]})
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["rows"] == 100
    omop = client.get(f"/api/omop/{rid}")
    assert omop.status_code == 200 and omop.json()["cdm"], omop.text
    with postgres_sources.engine(rid).connect() as conn:
        assert conn.execute(text("SHOW transaction_read_only")).scalar() == "on"
        with pytest.raises(Exception, match="read-only"):
            conn.execute(text("CREATE TABLE public.connector_must_not_exist (id int)"))


def test_postgres_config_validation_and_unknown_id(monkeypatch):
    monkeypatch.setenv("STUDIO_POSTGRES_SOURCES", '[{"id":"bad","url_env":"A","secret_id":"B"}]')
    with pytest.raises(ValueError, match="configuration"):
        postgres_sources.connections()
    monkeypatch.setenv("STUDIO_POSTGRES_SOURCES", '[]')
    with pytest.raises(ValueError, match="Unknown"):
        postgres_sources.engine("postgres:missing")
