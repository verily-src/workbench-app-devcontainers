import uuid

import pytest
from sqlalchemy import text

import datasets
import db


@pytest.fixture
def schema_tables(client, engine):
    suffix = uuid.uuid4().hex[:10]
    schema = f"studio_schema_{suffix}"
    table = f"probe_{suffix}"
    events = f"events_{suffix}"
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        conn.execute(text(f'CREATE TABLE public."{table}" '
                          '(person_id integer, marker text)'))
        conn.execute(text(f'CREATE TABLE "{schema}"."{table}" '
                          '(person_id integer, marker text)'))
        conn.execute(text(f'CREATE TABLE "{schema}"."{events}" '
                          '(person_id integer, event_name text)'))
        conn.execute(text(f'INSERT INTO public."{table}" VALUES (90, \'public\')'))
        conn.execute(text(f'INSERT INTO "{schema}"."{table}" VALUES '
                          "(1, 'private-one'), (2, 'private-two')"))
        conn.execute(text(f'INSERT INTO "{schema}"."{events}" VALUES '
                          "(1, 'visit-one'), (2, 'visit-two')"))
    db.list_aurora_tables.invalidate()
    db.fetch_aurora_table.invalidate()
    datasets._store.clear()
    yield {"schema": schema, "table": table, "events": events,
           "resource_id": "omopdb", "view_name": f"schema-source-{suffix}"}
    datasets._store.clear()
    with engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        conn.execute(text(f'DROP TABLE IF EXISTS public."{table}"'))
    db.list_aurora_tables.invalidate()
    db.fetch_aurora_table.invalidate()


def _query_rows(client, dataset_id):
    response = client.post(f"/api/datasets/{dataset_id}/query", json={
        "page": 0, "page_size": 20,
    })
    assert response.status_code == 200, response.text
    result = response.json()
    marker = result["rows"]["columns"].index("marker")
    return [row[marker] for row in result["rows"]["data"]]


def test_nonpublic_schema_survives_listing_join_and_saved_reopen(
        client, engine, schema_tables):
    schema = schema_tables["schema"]
    table = schema_tables["table"]
    rid = schema_tables["resource_id"]
    listed = client.get("/api/tables", params={
        "kind": "aurora", "resource_id": rid,
    })
    assert listed.status_code == 200, listed.text
    entries = listed.json()
    public_entry = next(item for item in entries
                        if item["table"] == table and item["schema"] == "public")
    private_entry = next(item for item in entries
                         if item["table"] == table and item["schema"] == schema)
    assert public_entry["name"] == table
    assert private_entry["name"] == f"{schema}.{table}"
    assert public_entry["name"] != private_entry["name"]

    base_ref = {"kind": "aurora", "resource_id": rid,
                "table": table, "schema": schema}
    event_ref = {"kind": "aurora", "resource_id": rid,
                 "table": schema_tables["events"], "schema": schema}
    base = client.post("/api/datasets/open", json={"source_ref": base_ref})
    event = client.post("/api/datasets/open", json={"source_ref": event_ref})
    assert base.status_code == event.status_code == 200, (base.text, event.text)
    assert base.json()["source_ref"]["schema"] == schema
    assert base.json()["rows"] == 2
    assert base.json()["source"] == f"omopdb / {schema}.{table}"

    joined = client.post("/api/datasets/join", json={
        "left_id": base.json()["dataset_id"],
        "right_id": event.json()["dataset_id"],
        "left_on": "person_id", "right_on": "person_id", "how": "inner",
    })
    assert joined.status_code == 200, joined.text
    ref = joined.json()["source_ref"]
    assert ref["kind"] == "join"
    assert ref["base"]["schema"] == schema
    assert ref["steps"][0]["source"]["schema"] == schema

    saved = client.post("/api/views", json={
        "kind": "aurora", "resource_id": rid,
        "name": schema_tables["view_name"],
        "datasets": [{"source": ref, "title": "Private schema join"}],
    })
    assert saved.status_code == 200, saved.text
    view = client.get("/api/views/one", params={
        "kind": "aurora", "resource_id": rid,
        "name": schema_tables["view_name"],
    })
    assert view.status_code == 200, view.text
    saved_ref = view.json()["datasets"][0]["source"]
    assert saved_ref == ref

    datasets._store.clear()
    reopened = client.post("/api/datasets/open", json={"source_ref": saved_ref})
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["query_scope"] == "database"
    assert reopened.json()["source_ref"]["base"]["schema"] == schema
    assert reopened.json()["source_ref"]["steps"][0]["source"]["schema"] == schema
    assert reopened.json()["rows"] == 2
    assert _query_rows(client, reopened.json()["dataset_id"]) == [
        "private-one", "private-two",
    ]
    client.delete("/api/views", params={
        "kind": "aurora", "resource_id": rid,
        "name": schema_tables["view_name"],
    })
