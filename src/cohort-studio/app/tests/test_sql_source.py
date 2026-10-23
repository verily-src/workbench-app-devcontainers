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
        assert opened["sampled"] is True
        assert opened["query_scope"] == "database"
        assert opened["source_ref"]["kind"] == "sql"

        query = client.post(f"/api/datasets/{opened['dataset_id']}/query", json={
            "page": 0, "page_size": 5, "entity_column": "person_id",
        })
        assert query.status_code == 200, query.text
        assert query.json()["total"] == 100_001
        assert query.json()["entity"]["total"] == 100_001
        assert query.json()["rows"]["data"][0] == [1, "sample-1"]

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


def test_custom_sql_obeys_database_statement_timeout(client, monkeypatch):
    monkeypatch.setattr(sql_source, "SQL_TIMEOUT_MS", 20)
    sql = ("WITH RECURSIVE n(x) AS (VALUES (1) UNION ALL "
           "SELECT x + 1 FROM n WHERE x < 100000000) SELECT count(*) FROM n")
    response = client.post("/api/sql/preview", json={
        "resource_id": RID, "sql": sql,
    })
    assert response.status_code == 504, response.text

