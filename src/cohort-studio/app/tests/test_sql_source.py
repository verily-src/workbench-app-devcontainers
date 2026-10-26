import uuid

import pytest
from sqlalchemy import text

import datasets
import sql_source


RID = "omopdb"


def test_custom_sql_preview_open_join_and_saved_source_reopen(client, engine):
    suffix = uuid.uuid4().hex[:8]
    table = f"sql_source_{suffix}"
    ids = []
    with engine.begin() as conn:
        conn.execute(text(f'CREATE TABLE public."{table}" '
                          "(person_id integer PRIMARY KEY, sample_id text NOT NULL)"))
        conn.execute(text(f'INSERT INTO public."{table}" '
                          "SELECT n, 'sample-' || n FROM generate_series(1, 100001) n"))
    sql = (f'SELECT person_id, sample_id FROM public."{table}" '
           "WHERE person_id <= 100001 ORDER BY person_id")
    try:
        preview = client.post("/api/sql/preview", json={
            "resource_id": RID, "sql": sql, "name": "Synthetic samples",
        })
        assert preview.status_code == 200, preview.text
        result = preview.json()
        assert result["columns"] == ["person_id", "sample_id"]
        assert result["rows"] == 20 and result["truncated"] is True
        assert len(result["sample"]) == 20
        assert result["source_ref"]["name"] == "Synthetic samples"

        opened = client.post("/api/datasets/open", json={
            "source_ref": result["source_ref"],
        })
        assert opened.status_code == 200, opened.text
        opened = opened.json()
        ids.append(opened["dataset_id"])
        assert opened["rows"] == 100_000
        assert opened["sampled"] is False
        assert opened["query_scope"] == "database"
        assert opened["source_ref"]["kind"] == "sql"

        query = client.post(f"/api/datasets/{opened['dataset_id']}/query", json={
            "page": 0, "page_size": 5, "entity_column": "person_id",
        })
        assert query.status_code == 200, query.text
        assert query.json()["total"] == 100_001
        assert query.json()["entity"]["total"] == 100_001
        assert query.json()["rows"]["data"][0] == [1, "sample-1"]

        descending_sql = sql.removesuffix("ORDER BY person_id") + "ORDER BY person_id DESC"
        descending_preview = client.post("/api/sql/preview", json={
            "resource_id": RID, "sql": descending_sql,
        })
        assert descending_preview.status_code == 200, descending_preview.text
        assert descending_preview.json()["sample"][0] == [100_001, "sample-100001"]
        descending_open = client.post("/api/datasets/open", json={
            "source_ref": descending_preview.json()["source_ref"],
        })
        assert descending_open.status_code == 200, descending_open.text
        ids.append(descending_open.json()["dataset_id"])
        descending_query = client.post(
            f"/api/datasets/{descending_open.json()['dataset_id']}/query", json={
                "page": 0, "page_size": 5,
            })
        assert descending_query.status_code == 200, descending_query.text
        assert descending_query.json()["rows"]["data"][0] == [
            100_001, "sample-100001"]

        people = client.post("/api/datasets/open", json={
            "source_ref": {"kind": "aurora", "resource_id": RID,
                           "schema": "cdm", "table": "person"},
        })
        assert people.status_code == 200, people.text
        ids.append(people.json()["dataset_id"])
        joined = client.post("/api/datasets/join", json={
            "base_id": opened["dataset_id"],
            "steps": [{"right_id": people.json()["dataset_id"], "how": "inner",
                       "conditions": [{"left": "person_id", "op": "=",
                                       "right": "person_id"}]}],
        })
        assert joined.status_code == 200, joined.text
        assert joined.json()["rows"] == 100
        joined_ref = joined.json()["source_ref"]
        assert joined_ref["base"]["kind"] == "sql"
        reopened = client.post("/api/datasets/open", json={"source_ref": joined_ref})
        assert reopened.status_code == 200, reopened.text
        ids.append(reopened.json()["dataset_id"])
        assert reopened.json()["rows"] == 100
        assert reopened.json()["query_scope"] == "database"
    finally:
        for dataset_id in ids:
            datasets.close_dataset(dataset_id)
        with engine.begin() as conn:
            conn.execute(text(f'DROP TABLE IF EXISTS public."{table}"'))


def test_jsonb_table_opens_profiles_and_returns_structured_values(client, engine):
    schema = f"genetics_jsonb_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        conn.exec_driver_sql(f'''CREATE TABLE "{schema}".import_metadata (
            metadata jsonb, items jsonb, absent jsonb
        )''')
        conn.exec_driver_sql(
            f'''INSERT INTO "{schema}".import_metadata VALUES (
                '{{"nested":{{"n":7}}}}'::jsonb, '[1,2]'::jsonb, NULL
            )''')
    try:
        opened = client.post("/api/datasets/open", json={
            "source_ref": {"kind": "aurora", "resource_id": RID,
                           "schema": schema, "table": "import_metadata"},
        })
        assert opened.status_code == 200, opened.text
        body = opened.json()
        try:
            assert {column["name"]: column["filter_kind"] for column in body["columns"]} == {
                "metadata": "none", "items": "none", "absent": "none",
            }

            rows = client.post(f"/api/datasets/{body['dataset_id']}/query", json={
                "page": 0, "page_size": 5,
            })
            assert rows.status_code == 200, rows.text
            assert rows.json()["rows"]["data"] == [[{"nested": {"n": 7}}, [1, 2], None]]
        finally:
            datasets.close_dataset(body["dataset_id"])
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


@pytest.mark.parametrize("sql", [
    "SELECT " + "(" * 500 + "1" + ")" * 500,
    "SELECT 1 " + "UNION ALL SELECT 1 " * 500,
    "DELETE FROM public.t",
    "CREATE TABLE public.t (id integer)",
    "SELECT 1; SELECT 2",
    "WITH changed AS (DELETE FROM public.t RETURNING *) SELECT * FROM changed",
    "SELECT * INTO public.t FROM cdm.person",
    "SELECT * FROM cdm.person FOR UPDATE",
    "SELECT * FROM pg_catalog.pg_class",
    "SELECT * FROM person",
    "SELECT public.lower('x')",
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT pg_catalog.set_config('search_path', 'public', false)",
    "SELECT 1 OPERATOR(public.+) 2 FROM cdm.person",
    "SELECT CAST('x' AS cdm.some_type) FROM cdm.person",
    "SELECT * FROM otherdb.cdm.person",
    "SELECT * FROM generate_series(1, 3)",
])
def test_preview_rejects_mutating_or_unsafe_sql(client, sql):
    response = client.post("/api/sql/preview", json={
        "resource_id": RID, "sql": sql,
    })
    assert response.status_code == 422, response.text


def test_preview_rejects_mutation_before_any_database_change(client, engine):
    with engine.connect() as conn:
        before = conn.execute(text("SELECT count(*) FROM cdm.person")).scalar_one()
    response = client.post("/api/sql/preview", json={
        "resource_id": RID, "sql": "DELETE FROM cdm.person RETURNING person_id",
    })
    assert response.status_code == 422, response.text
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM cdm.person")).scalar_one() == before


def test_cte_name_is_only_allowed_in_lexical_scope():
    sql = ("WITH unused AS (WITH pg_class AS (SELECT 1 AS x) "
           "SELECT * FROM pg_class) SELECT count(*) FROM pg_class")
    with pytest.raises(ValueError, match="schema-qualified"):
        sql_source.normalize(sql)


def test_exists_subquery_is_allowed_but_nested_unsafe_functions_are_not():
    normalized = sql_source.normalize(
        "SELECT EXISTS (SELECT 1 FROM cdm.person)")
    assert "EXISTS" in normalized.upper()
    with pytest.raises(ValueError, match="pg_read_file.*not allowed"):
        sql_source.normalize(
            "SELECT EXISTS (SELECT pg_read_file('/etc/passwd') FROM cdm.person)")


def test_custom_sql_obeys_database_statement_timeout(client, monkeypatch):
    monkeypatch.setattr(sql_source, "SQL_TIMEOUT_MS", 20)
    sql = ("WITH RECURSIVE n(x) AS (VALUES (1) UNION ALL "
           "SELECT x + 1 FROM n WHERE x < 100000000) SELECT count(*) FROM n")
    response = client.post("/api/sql/preview", json={
        "resource_id": RID, "sql": sql,
    })
    assert response.status_code == 504, response.text

