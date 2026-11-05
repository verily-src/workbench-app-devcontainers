import json

import pytest

import db
import sql_completions
from tests.conftest import RID


@pytest.fixture(autouse=True)
def _fresh_cache():
    sql_completions.invalidate()
    yield
    sql_completions.invalidate()


def _table(body, schema, name):
    return next((t for t in body["tables"] if t["schema"] == schema and t["name"] == name), None)


def test_completions_lists_schemas_tables_and_typed_columns(client):
    resp = client.get("/api/sql/completions", params={"resource_id": RID})
    assert resp.status_code == 200
    body = resp.json()
    assert body["resource_id"] == RID
    assert set(body) == {"resource_id", "schemas", "tables", "column_count", "truncated", "limits"}
    assert body["truncated"] is False
    assert body["limits"] == {"tables": sql_completions.MAX_TABLES,
                              "columns": sql_completions.MAX_COLUMNS}
    person = _table(body, "cdm", "person")
    assert person["kind"] == "table" and person["omop"] is True
    columns = {c["name"]: c["type"] for c in person["columns"]}
    assert columns["person_id"] in {"integer", "bigint"}
    assert "year_of_birth" in columns
    # Columns keep their table order and every column is typed.
    assert person["columns"][0]["name"] == "person_id"
    assert all(set(c) == {"name", "type"} and c["type"] for t in body["tables"] for c in t["columns"])
    assert body["column_count"] == sum(len(t["columns"]) for t in body["tables"])
    assert len({(t["schema"], t["name"]) for t in body["tables"]}) == len(body["tables"])


def test_completions_mark_omop_cdm_schema(client):
    body = client.get("/api/sql/completions", params={"resource_id": RID}).json()
    cdm = next(s for s in body["schemas"] if s["name"] == "cdm")
    assert cdm["omop"]["role"] == "cdm" and cdm["omop"]["default"] is True
    assert cdm["omop"]["vocab_schema"] == "cdm"
    # OMOP schemas come first, non-OMOP schemas are not marked.
    assert body["schemas"][0]["name"] == "cdm"
    assert all("omop" not in s for s in body["schemas"] if s["name"] != "cdm")


def test_completions_exclude_system_internal_tables_and_data(client, engine):
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE public._studio_mv_secret (secret_value text)")
        conn.exec_driver_sql("CREATE TABLE public._lineage_event (secret_value text)")
        conn.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS _studio_private")
        conn.exec_driver_sql("CREATE TABLE _studio_private.hidden (secret_value text)")
        conn.exec_driver_sql("CREATE TABLE public.visible_notes (note text)")
        conn.exec_driver_sql("INSERT INTO public.visible_notes VALUES ('DATA-VALUE-SENTINEL')")
    try:
        body = client.get("/api/sql/completions", params={"resource_id": RID}).json()
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql("DROP TABLE public._studio_mv_secret")
            conn.exec_driver_sql("DROP TABLE public._lineage_event")
            conn.exec_driver_sql("DROP SCHEMA _studio_private CASCADE")
            conn.exec_driver_sql("DROP TABLE public.visible_notes")
    names = {(t["schema"], t["name"]) for t in body["tables"]}
    assert ("public", "visible_notes") in names
    assert not any(t.startswith("_studio_mv_") or t == "_lineage_event" for _, t in names)
    schemas = {s["name"] for s in body["schemas"]}
    assert not any(s.startswith(("pg_", "_studio_")) or s == "information_schema"
                   for s in schemas | {schema for schema, _ in names})
    raw = json.dumps(body)
    assert "DATA-VALUE-SENTINEL" not in raw and "secret_value" not in raw
    # Person rows (fixture values) never appear: only metadata keys are present.
    assert all(set(t) <= {"schema", "name", "kind", "columns", "omop"} for t in body["tables"])


def test_completions_are_bounded(engine):
    full = sql_completions.load(engine)
    assert full["truncated"] is False and full["column_count"] > 10
    bounded = sql_completions.load(engine, max_columns=10)
    assert bounded["truncated"] is True and bounded["column_count"] == 10
    few_tables = sql_completions.load(engine, max_tables=2)
    assert few_tables["truncated"] is True and len(few_tables["tables"]) == 2


def test_completions_prioritize_omop_schema_within_bounds(client, engine):
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE SCHEMA aaa_first")
        conn.exec_driver_sql("CREATE TABLE aaa_first.wide (a int, b int, c int)")
    try:
        bounded = sql_completions.load(engine, RID, max_columns=5)
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql("DROP SCHEMA aaa_first CASCADE")
    assert bounded["truncated"] is True
    assert {t["schema"] for t in bounded["tables"] if t["columns"]} == {"cdm"}


def test_completions_are_cached_and_refreshable(client, engine, monkeypatch):
    calls = []
    real = sql_completions.load
    monkeypatch.setattr(sql_completions, "load",
                        lambda *a, **k: calls.append(1) or real(*a, **k))
    client.get("/api/sql/completions", params={"resource_id": RID})
    client.get("/api/sql/completions", params={"resource_id": RID})
    assert len(calls) == 1
    client.get("/api/sql/completions", params={"resource_id": RID, "refresh": True})
    assert len(calls) == 2


def test_completions_use_read_only_transaction(engine):
    statements = []
    from sqlalchemy import event

    def before(conn, cursor, statement, *args):
        statements.append(statement)
    event.listen(engine, "before_cursor_execute", before)
    try:
        sql_completions.load(engine)
    finally:
        event.remove(engine, "before_cursor_execute", before)
    assert any("READ ONLY" in s for s in statements)
    assert any("statement_timeout" in s for s in statements)


def test_completions_unknown_and_non_postgres_resources(client, monkeypatch):
    assert client.get("/api/sql/completions", params={"resource_id": "nope"}).status_code == 404
    assert client.get("/api/sql/completions").status_code == 422
    from sqlalchemy import create_engine
    monkeypatch.setattr(db, "get_engine_for_resource", lambda rid: create_engine("sqlite://"))
    resp = client.get("/api/sql/completions", params={"resource_id": RID})
    assert resp.status_code == 400 and "PostgreSQL" in resp.json()["detail"]
