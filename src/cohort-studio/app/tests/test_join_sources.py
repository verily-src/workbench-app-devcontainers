import uuid

import pytest
from sqlalchemy import text

import datasets
import db
import main
import queries
import query_cache
import views


def _contains_transient_id(value):
    if isinstance(value, dict):
        return any(key in {"dataset_id", "base_id", "right_id", "left_id"}
                   or _contains_transient_id(item)
                   for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_transient_id(item) for item in value)
    return False


@pytest.fixture
def source_tables(client, engine, monkeypatch):
    suffix = uuid.uuid4().hex[:8]
    people = f"studio_people_{suffix}"
    detail = f"studio_detail_{suffix}"
    numeric = f"studio_numeric_{suffix}"
    invalid = f"studio_invalid_{suffix}"
    large_ids = f"studio_large_ids_{suffix}"
    padded_ids = f"studio_padded_ids_{suffix}"
    with engine.begin() as conn:
        conn.execute(text(f'DROP TABLE IF EXISTS public."{people}"'))
        conn.execute(text(f'DROP TABLE IF EXISTS public."{detail}"'))
        conn.execute(text(f'DROP TABLE IF EXISTS public."{numeric}"'))
        conn.execute(text(f'DROP TABLE IF EXISTS public."{invalid}"'))
        conn.execute(text(f'DROP TABLE IF EXISTS public."{large_ids}"'))
        conn.execute(text(f'DROP TABLE IF EXISTS public."{padded_ids}"'))
        conn.execute(text(
            f'CREATE TABLE public."{people}" '
            '(person_id integer, status text, score_text text)'))
        conn.execute(text(
            f'CREATE TABLE public."{detail}" '
            '(person_id integer, event text)'))
        conn.execute(text(
            f'CREATE TABLE public."{numeric}" '
            '(person_id integer, score_text text)'))
        conn.execute(text(
            f'CREATE TABLE public."{invalid}" '
            '(person_id integer, score_text text)'))
        conn.execute(text(
            f'CREATE TABLE public."{large_ids}" '
            '(person_id text, label text)'))
        conn.execute(text(
            f'CREATE TABLE public."{padded_ids}" '
            '(person_id text, label text)'))
        conn.execute(text(
            f'INSERT INTO public."{people}" VALUES '
            "(1, 'active', '10'), (1, 'active', '20'), "
            "(2, 'inactive', '30'), (3, 'active', '40')"))
        conn.execute(text(
            f'INSERT INTO public."{detail}" VALUES '
            "(1, 'visit'), (2, 'visit'), (3, 'visit')"))
        conn.execute(text(
            f'INSERT INTO public."{numeric}" VALUES '
            "(1, '10'), (2, '20'), (3, '30')"))
        conn.execute(text(
            f'INSERT INTO public."{invalid}" VALUES '
            "(1, '10'), (2, '20'), (3, 'not-a-number'), "
            "(4, '+Infinity'), (5, '  ')"))
        conn.execute(text(
            f'INSERT INTO public."{large_ids}" VALUES '
            "('9007199254740992', 'first'), "
            "('9007199254740993', 'second')"))
        conn.execute(text(
            f'INSERT INTO public."{padded_ids}" VALUES '
            "('001', 'first'), ('002', 'second')"))
    db.fetch_aurora_table.invalidate()
    datasets._store.clear()
    monkeypatch.setattr(main.lineage, "record",
                        lambda *args, **kwargs: None)
    yield {
        "people": people,
        "detail": detail,
        "numeric": numeric,
        "invalid": invalid,
        "large_ids": large_ids,
        "padded_ids": padded_ids,
        "rid": "omopdb",
        "view_name": f"join-source-{suffix}",
    }
    datasets._store.clear()
    with engine.begin() as conn:
        for table in (people, detail, numeric, invalid, large_ids, padded_ids):
            conn.execute(text(f'DROP TABLE IF EXISTS public."{table}"'))
    db.fetch_aurora_table.invalidate()
    views._prepared.clear()


def _ref(rid, table):
    return {"kind": "aurora", "resource_id": rid, "table": table}


def test_join_source_is_durable_and_restores_saved_view(
        client, source_tables, engine, monkeypatch):
    rid = source_tables["rid"]
    view_name = source_tables["view_name"]
    people_ref = _ref(rid, source_tables["people"])
    detail_ref = _ref(rid, source_tables["detail"])
    legacy = client.post("/api/datasets/open", json=people_ref)
    assert legacy.status_code == 200, legacy.text

    people = client.post("/api/datasets/open", json={"source_ref": people_ref})
    detail = client.post("/api/datasets/open", json={"source_ref": detail_ref})
    assert people.status_code == detail.status_code == 200
    joined = client.post("/api/datasets/join", json={
        "left_id": people.json()["dataset_id"],
        "right_id": detail.json()["dataset_id"],
        "left_on": "person_id", "right_on": "person_id", "how": "inner",
    })
    assert joined.status_code == 200, joined.text
    joined_body = joined.json()
    assert joined_body["query_scope"] == "database"
    source_ref = {
        **joined_body["source_ref"],
        "settings": [{"name": "status", "label": "Review status",
                      "filter_kind": "categorical"}],
    }
    assert source_ref["kind"] == "join"
    assert not _contains_transient_id(source_ref)

    save = client.post("/api/views", json={
        "kind": "aurora", "resource_id": rid, "name": view_name,
        "active": 0,
        "datasets": [{
            "source": source_ref,
            "title": "joined people",
            "entity_column": "person_id",
            "filters": [], "charts": [], "cohorts": [],
        }],
    })
    assert save.status_code == 200, save.text
    saved = client.get("/api/views/one", params={
        "kind": "aurora", "resource_id": rid,
        "name": view_name,
    })
    assert saved.status_code == 200, saved.text
    saved_source = saved.json()["datasets"][0]["source"]
    assert saved_source == source_ref
    assert saved.json()["datasets"][0]["entity_column"] == "person_id"

    datasets._store.clear()
    reopened = client.post("/api/datasets/open", json={
        "source_ref": saved_source,
    })
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["query_scope"] == "database"
    queried = client.post(
        f"/api/datasets/{reopened.json()['dataset_id']}/query",
        json={"entity_column": "person_id", "filters": [{
            "column": "status", "kind": "categorical", "values": ["active"],
        }], "page": 0, "page_size": 20},
    )
    assert queried.status_code == 200, queried.text
    result = queried.json()
    assert result["scope"] == "database"
    assert result["entity"] == {
        "column": "person_id", "total": 3, "filtered": 2,
    }
    assert result["total"] == 4
    assert result["filtered"] == 3
    assert not _contains_transient_id(saved.json())
    client.delete("/api/views", params={
        "kind": "aurora", "resource_id": rid,
        "name": view_name,
    })


def test_column_override_uses_postgres_storage_values(
        client, source_tables, engine, monkeypatch):
    rid = source_tables["rid"]
    opened = client.post("/api/datasets/open", json={
        "source_ref": _ref(rid, source_tables["numeric"]),
    })
    assert opened.status_code == 200, opened.text
    dataset_id = opened.json()["dataset_id"]
    profile = {c["name"]: c for c in opened.json()["columns"]}
    assert profile["score_text"]["filter_kind"] == "categorical"

    changed = client.patch(f"/api/datasets/{dataset_id}/columns", json={
        "columns": [{"name": "score_text", "logical_type": "number",
                     "label": "Score", "filter_kind": "range"}],
    })
    assert changed.status_code == 200, changed.text
    queried = client.post(f"/api/datasets/{dataset_id}/query", json={
        "filters": [{"column": "score_text", "kind": "range",
                     "min": 15, "max": 25}],
        "page": 0, "page_size": 20,
    })
    assert queried.status_code == 200, queried.text
    assert queried.json()["filtered"] == 1
    assert [row[0] for row in queried.json()["rows"]["data"]] == [2]

    monkeypatch.setattr(queries, "ROW_CAP", 1)
    bad = client.post("/api/datasets/open", json={
        "source_ref": _ref(rid, source_tables["invalid"]),
    })
    assert bad.status_code == 200, bad.text
    assert bad.json()["rows"] == 1
    # Each invalid value is beyond the one-row preview. The validation must
    # inspect the live PostgreSQL source, including valid-but-nonfinite values.
    for value in ("not-a-number", "+Infinity", "  "):
        with engine.begin() as conn:
            conn.execute(text(
                f'UPDATE public."{source_tables["invalid"]}" '
                "SET score_text = :value WHERE person_id = 2"),
                {"value": value})
        rejected = client.patch(
            f"/api/datasets/{bad.json()['dataset_id']}/columns", json={
                "columns": [{"name": "score_text", "logical_type": "number",
                             "filter_kind": "range"}],
            })
        assert rejected.status_code == 400, (value, rejected.text)
        with engine.begin() as conn:
            conn.execute(text(
                f'UPDATE public."{source_tables["invalid"]}" '
                "SET score_text = '20' WHERE person_id = 2"))
    # A failed full-source validation must not apply the logical override or
    # mutate the loaded frame.
    retained = datasets.get(bad.json()["dataset_id"])
    assert retained["df"]["score_text"].tolist() == ["10"]
    assert retained.get("column_settings", []) == []
    assert retained["source_ref"].get("settings", []) == []


def test_source_ref_rejects_sql_and_unknown_fields(client, source_tables):
    rid = source_tables["rid"]
    people_ref = _ref(rid, source_tables["people"])
    detail_ref = _ref(rid, source_tables["detail"])
    step = {"source": detail_ref, "how": "inner", "alias": "detail",
            "conditions": [{"left": "person_id", "right": "person_id"}]}
    for ref in (
        {**people_ref, "sql": "SELECT 1"},
        {**people_ref, "unexpected": True},
        {"kind": "join", "base": people_ref,
         "steps": [step], "sql": "SELECT 1"},
        {"kind": "join", "base": {**people_ref, "sql": "SELECT 1"},
         "steps": [step]},
    ):
        response = client.post("/api/datasets/open", json={"source_ref": ref})
        assert response.status_code == 422, response.text


def test_numeric_override_preserves_adjacent_large_entity_ids(
        client, source_tables):
    opened = client.post("/api/datasets/open", json={"source_ref":
        _ref(source_tables["rid"], source_tables["large_ids"])})
    assert opened.status_code == 200, opened.text
    dataset_id = opened.json()["dataset_id"]
    converted = client.patch(f"/api/datasets/{dataset_id}/columns", json={
        "columns": [{"name": "person_id", "logical_type": "number",
                     "filter_kind": "none"}],
    })
    assert converted.status_code == 200, converted.text
    queried = client.post(f"/api/datasets/{dataset_id}/query", json={
        "entity_column": "person_id", "page": 0, "page_size": 20,
    })
    assert queried.status_code == 200, queried.text
    assert queried.json()["entity"] == {
        "column": "person_id", "total": 2, "filtered": 2,
    }


def test_saved_final_text_override_reopens_with_leading_zeroes(
        client, source_tables):
    rid = source_tables["rid"]
    opened = client.post("/api/datasets/open", json={"source_ref":
        _ref(rid, source_tables["padded_ids"])})
    assert opened.status_code == 200, opened.text
    dataset_id = opened.json()["dataset_id"]
    for logical_type in ("number", "text"):
        converted = client.patch(f"/api/datasets/{dataset_id}/columns", json={
            "columns": [{"name": "person_id", "logical_type": logical_type,
                         "filter_kind": "none"}],
        })
        assert converted.status_code == 200, converted.text
    assert datasets.get(dataset_id)["df"]["person_id"].tolist() == ["001", "002"]
    source_ref = converted.json()["source_ref"]

    name = source_tables["view_name"]
    saved = client.post("/api/views", json={
        "kind": "aurora", "resource_id": rid, "name": name,
        "datasets": [{"source": source_ref, "title": "padded IDs"}],
    })
    assert saved.status_code == 200, saved.text
    view = client.get("/api/views/one", params={
        "kind": "aurora", "resource_id": rid, "name": name,
    })
    assert view.status_code == 200, view.text
    reopened = client.post("/api/datasets/open", json={
        "source_ref": view.json()["datasets"][0]["source"],
    })
    assert reopened.status_code == 200, reopened.text
    queried = client.post(f"/api/datasets/{reopened.json()['dataset_id']}/query", json={
        "page": 0, "page_size": 20,
    })
    assert queried.status_code == 200, queried.text
    result = queried.json()
    id_index = result["rows"]["columns"].index("person_id")
    assert [row[id_index] for row in result["rows"]["data"]] == ["001", "002"]
    client.delete("/api/views", params={
        "kind": "aurora", "resource_id": rid, "name": name,
    })


def test_live_join_export_filters_full_source_and_enforces_row_limit(
        client, source_tables, monkeypatch):
    rid = source_tables["rid"]
    left = client.post("/api/datasets/open", json={"source_ref":
        _ref(rid, source_tables["people"])})
    right = client.post("/api/datasets/open", json={"source_ref":
        _ref(rid, source_tables["detail"])})
    assert left.status_code == right.status_code == 200
    joined = client.post("/api/datasets/join", json={
        "left_id": left.json()["dataset_id"],
        "right_id": right.json()["dataset_id"],
        "left_on": "person_id", "right_on": "person_id", "how": "inner",
    })
    assert joined.status_code == 200, joined.text
    dataset_id = joined.json()["dataset_id"]

    # Make the in-memory sample smaller than the live filtered result. Export
    # must query the source reference, not export only this sample.
    datasets.get(dataset_id)["df"] = datasets.get(dataset_id)["df"].head(1)
    monkeypatch.setattr(queries, "ROW_CAP", 3)
    filtered = client.post(f"/api/datasets/{dataset_id}/export", json={
        "filters": [{"column": "status", "kind": "categorical",
                    "values": ["active"]}],
    })
    assert filtered.status_code == 200, filtered.text
    assert len(filtered.text.splitlines()) == 4  # header + all three active rows
    assert "inactive" not in filtered.text

    monkeypatch.setattr(queries, "ROW_CAP", 2)
    oversized = client.post(f"/api/datasets/{dataset_id}/export", json={
        "filters": [{"column": "status", "kind": "categorical",
                    "values": ["active"]}],
    })
    assert oversized.status_code == 400, oversized.text
    assert "more than 2 rows" in oversized.json()["detail"].lower()


def test_database_scoped_chat_is_guarded(client, source_tables):
    rid = source_tables["rid"]
    left = client.post("/api/datasets/open", json={"source_ref":
        _ref(rid, source_tables["people"])})
    right = client.post("/api/datasets/open", json={"source_ref":
        _ref(rid, source_tables["detail"])})
    assert left.status_code == right.status_code == 200
    joined = client.post("/api/datasets/join", json={
        "left_id": left.json()["dataset_id"],
        "right_id": right.json()["dataset_id"],
        "left_on": "person_id", "right_on": "person_id", "how": "inner",
    })
    assert joined.status_code == 200, joined.text
    dataset_id = joined.json()["dataset_id"]

    response = client.post(f"/api/datasets/{dataset_id}/chat", json={
        "message": "Describe this dataset.",
    })
    assert response.status_code == 400, response.text
    assert "database-scoped" in response.json()["detail"]


def test_live_query_cache_refreshes_rows_entities_and_profiles(
        client, source_tables, engine, monkeypatch):
    rid = source_tables["rid"]
    query_cache.cache.clear()
    monkeypatch.setattr(query_cache, "_ttl", lambda: 60)
    left = client.post("/api/datasets/open", json={"source_ref":
        _ref(rid, source_tables["people"])})
    right = client.post("/api/datasets/open", json={"source_ref":
        _ref(rid, source_tables["detail"])})
    assert left.status_code == right.status_code == 200
    joined = client.post("/api/datasets/join", json={
        "left_id": left.json()["dataset_id"],
        "right_id": right.json()["dataset_id"],
        "left_on": "person_id", "right_on": "person_id", "how": "inner",
    })
    assert joined.status_code == 200, joined.text
    dataset_id = joined.json()["dataset_id"]
    query_url = f"/api/datasets/{dataset_id}/query"
    request = {"entity_column": "person_id", "page": 0, "page_size": 20}

    miss = client.post(query_url, json=request)
    assert miss.status_code == 200, miss.text
    assert miss.json()["cache"]["hit"] is False
    assert miss.json()["total"] == 4
    assert miss.json()["entity"]["total"] == 3

    hit = client.post(query_url, json=request)
    assert hit.status_code == 200, hit.text
    assert hit.json()["cache"]["hit"] is True
    assert hit.json()["entity"]["total"] == 3

    with engine.begin() as conn:
        conn.execute(text(
            f'INSERT INTO public."{source_tables["people"]}" '
            "VALUES (4, 'new', '50')"))
        conn.execute(text(
            f'INSERT INTO public."{source_tables["detail"]}" '
            "VALUES (4, 'new_visit')"))

    stale = client.post(query_url, json=request)
    assert stale.status_code == 200, stale.text
    assert stale.json()["cache"]["hit"] is True
    assert stale.json()["total"] == 4
    assert stale.json()["entity"]["total"] == 3

    refreshed = client.post(query_url, json={**request, "refresh": True})
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["cache"]["hit"] is False
    assert refreshed.json()["total"] == 5
    assert refreshed.json()["entity"]["total"] == 4
    status = next(c for c in refreshed.json()["columns"]
                  if c["name"] == "status")
    assert "new" in status["values"]

    fresh_hit = client.post(query_url, json=request)
    assert fresh_hit.status_code == 200, fresh_hit.text
    assert fresh_hit.json()["cache"]["hit"] is True
    assert fresh_hit.json()["total"] == 5
    assert fresh_hit.json()["entity"]["total"] == 4

    invalid = client.post(query_url, json={**request, "refresh": "true"})
    assert invalid.status_code == 422, invalid.text
    query_cache.cache.clear()
