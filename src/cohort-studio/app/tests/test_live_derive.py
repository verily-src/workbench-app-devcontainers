import copy
import uuid

import pandas as pd
import pytest
from sql_utils import statement as text

import datasets
import db
import main
import query_cache
import views


@pytest.fixture
def live_derive_tables(client, engine, monkeypatch):
    suffix = uuid.uuid4().hex[:8]
    people = f"studio_derive_people_{suffix}"
    detail = f"studio_derive_detail_{suffix}"
    view_name = f"derive-source-{suffix}"
    needle = "x' OR '1'='1 --"
    with engine.begin() as conn:
        conn.execute(text(f'DROP TABLE IF EXISTS public."{people}"'))
        conn.execute(text(f'DROP TABLE IF EXISTS public."{detail}"'))
        conn.execute(text(
            f'CREATE TABLE public."{people}" '
            '(person_id integer PRIMARY KEY, value_text text, mapping_text text, '
            '"mapping :ghost" text)'))
        conn.execute(text(
            f'CREATE TABLE public."{detail}" '
            '(person_id integer PRIMARY KEY, visit text)'))
        conn.execute(text(
            f'INSERT INTO public."{people}" '
            'SELECT person_id, '
            "CASE WHEN person_id = 4 THEN NULL "
            "WHEN person_id = 1 THEN '0' "
            "WHEN person_id = 2 THEN '10' "
            "WHEN person_id = 3 THEN '20' "
            "WHEN person_id = 100005 THEN '999' ELSE '5' END, "
            "CASE WHEN person_id = 100005 THEN :needle ELSE 'plain' END "
            ", CASE WHEN person_id = 100005 THEN :needle ELSE 'plain' END "
            'FROM generate_series(1, 100005) AS g(person_id)'),
            {"needle": needle})
        conn.execute(text(
            f'INSERT INTO public."{detail}" '
            "SELECT person_id, 'visit' FROM generate_series(1, 100005) "
            "AS g(person_id)"))
    db.fetch_aurora_table.invalidate()
    datasets._store.clear()
    query_cache.invalidate_resource("omopdb")
    monkeypatch.setattr(main.lineage, "record", lambda *args, **kwargs: None)
    yield {"people": people, "detail": detail, "needle": needle,
           "rid": "omopdb", "view_name": view_name}
    datasets._store.clear()
    query_cache.invalidate_resource("omopdb")
    try:
        views._aurora_delete("omopdb", view_name)
    except Exception:
        pass
    with engine.begin() as conn:
        conn.execute(text(f'DROP TABLE IF EXISTS public."{people}"'))
        conn.execute(text(f'DROP TABLE IF EXISTS public."{detail}"'))
    db.fetch_aurora_table.invalidate()
    views._prepared.clear()


def _column(result, name):
    return result["rows"]["columns"].index(name)


def _query(client, dataset_id, ids):
    return client.post(f"/api/datasets/{dataset_id}/query", json={
        "filters": [{"column": "person_id", "kind": "categorical",
                     "values": [str(value) for value in ids]}],
        "entity_column": "person_id", "page": 0, "page_size": 20,
    })


def test_derived_live_source_covers_full_database_and_reopens_recipe(
        client, engine, live_derive_tables):
    rid = live_derive_tables["rid"]
    people = client.post("/api/datasets/open", json={"kind": "aurora",
        "resource_id": rid, "table": live_derive_tables["people"]})
    detail = client.post("/api/datasets/open", json={"kind": "aurora",
        "resource_id": rid, "table": live_derive_tables["detail"]})
    assert people.status_code == detail.status_code == 200
    joined = client.post("/api/datasets/join", json={
        "left_id": people.json()["dataset_id"],
        "right_id": detail.json()["dataset_id"],
        "left_on": "person_id", "right_on": "person_id", "how": "inner",
    })
    assert joined.status_code == 200, joined.text
    dataset_id = joined.json()["dataset_id"]
    assert joined.json()["rows"] == 100_000
    assert joined.json()["sampled"] is True

    mapped = client.post(f"/api/datasets/{dataset_id}/derive", json={
        "op": "map", "name": "mapped_text", "column": "mapping :ghost",
        "mapping": {live_derive_tables["needle"]: "matched safely"},
        "default": "other",
    })
    assert mapped.status_code == 200, mapped.text
    assert mapped.json()["query_scope"] == "database"
    assert mapped.json()["sampled"] is True
    late = _query(client, dataset_id, [100005])
    assert late.status_code == 200, late.text
    assert late.json()["total"] == 100_005
    assert late.json()["entity"] == {
        "column": "person_id", "total": 100_005, "filtered": 1,
    }
    assert late.json()["rows"]["data"][0][_column(late.json(), "mapped_text")] == "matched safely"

    configured = client.patch(f"/api/datasets/{dataset_id}/columns", json={
        "columns": [{"name": "value_text", "logical_type": "number",
                     "filter_kind": "range"}],
    })
    assert configured.status_code == 200, configured.text
    chained_join = client.post("/api/datasets/join", json={
        "base_id": dataset_id,
        "steps": [{"right_id": detail.json()["dataset_id"],
                   "how": "inner", "alias": "details",
                   "conditions": [{"left": "person_id", "right": "person_id"}],
                   "columns": ["visit"]}],
    })
    assert chained_join.status_code == 200, chained_join.text
    joined_late = _query(client, chained_join.json()["dataset_id"], [100005])
    assert joined_late.status_code == 200, joined_late.text
    joined_result = joined_late.json()
    assert joined_result["entity"]["total"] == 100_005
    assert joined_result["rows"]["data"][0][
        _column(joined_result, "mapped_text")] == "matched safely"

    binned = client.post(f"/api/datasets/{dataset_id}/derive", json={
        "op": "bin", "name": "value_bin", "column": "value_text",
        "breaks": [0, 10, 20], "labels": ["low", "high"],
    })
    assert binned.status_code == 200, binned.text
    edge_rows = _query(client, dataset_id, [1, 2, 3, 4, 100005])
    assert edge_rows.status_code == 200, edge_rows.text
    rows = edge_rows.json()
    by_id = {row[_column(rows, "person_id")]: row for row in rows["rows"]["data"]}
    bucket = _column(rows, "value_bin")
    assert by_id[1][bucket] == "low"
    assert by_id[2][bucket] == "low"
    assert by_id[3][bucket] == "high"
    assert by_id[4][bucket] is None
    assert by_id[100005][bucket] is None

    formula = client.post(f"/api/datasets/{dataset_id}/derive", json={
        "op": "formula", "name": "ratio", "left": "value_text",
        "operator": "/", "right": "value_text",
    })
    assert formula.status_code == 200, formula.text
    formula_rows = _query(client, dataset_id, [1, 2, 4])
    assert formula_rows.status_code == 200, formula_rows.text
    result = formula_rows.json()
    by_id = {row[_column(result, "person_id")]: row for row in result["rows"]["data"]}
    ratio = _column(result, "ratio")
    assert by_id[1][ratio] is None
    assert by_id[2][ratio] == 1.0
    assert by_id[4][ratio] is None

    before = datasets.get(dataset_id)
    old_frame = before["df"].copy(deep=True)
    old_live = copy.deepcopy(before["live_source"])
    old_ref = copy.deepcopy(before["source_ref"])
    invalid = client.post(f"/api/datasets/{dataset_id}/derive", json={
        "op": "formula", "name": "bad_result", "left": "missing",
        "operator": "+", "right": "1",
    })
    assert invalid.status_code == 400, invalid.text
    after = datasets.get(dataset_id)
    pd.testing.assert_frame_equal(after["df"], old_frame)
    assert after["live_source"] == old_live
    assert after["source_ref"] == old_ref
    nonfinite = client.post(f"/api/datasets/{dataset_id}/derive", json={
        "op": "formula", "name": "bad_constant", "left": "value_text",
        "operator": "+", "right": "Infinity",
    })
    assert nonfinite.status_code == 400, nonfinite.text
    after_nonfinite = datasets.get(dataset_id)
    pd.testing.assert_frame_equal(after_nonfinite["df"], old_frame)
    assert after_nonfinite["live_source"] == old_live
    assert after_nonfinite["source_ref"] == old_ref

    saved = client.post("/api/views", json={
        "kind": "aurora", "resource_id": rid,
        "name": live_derive_tables["view_name"],
        "datasets": [{"source": formula.json()["source_ref"],
                      "title": "derived full source",
                      "entity_column": "person_id"}],
    })
    assert saved.status_code == 200, saved.text
    state = client.get("/api/views/one", params={
        "kind": "aurora", "resource_id": rid,
        "name": live_derive_tables["view_name"],
    })
    assert state.status_code == 200, state.text
    datasets._store.clear()
    reopened = client.post("/api/datasets/open", json={
        "source_ref": state.json()["datasets"][0]["source"],
    })
    assert reopened.status_code == 200, reopened.text
    restored = _query(client, reopened.json()["dataset_id"], [100005])
    assert restored.status_code == 200, restored.text
    assert restored.json()["entity"]["total"] == 100_005
    assert restored.json()["rows"]["data"][0][
        _column(restored.json(), "mapped_text")] == "matched safely"

    settings_source = client.post("/api/datasets/open", json={
        "kind": "aurora", "resource_id": rid,
        "table": live_derive_tables["people"],
    })
    assert settings_source.status_code == 200, settings_source.text
    settings_dataset_id = settings_source.json()["dataset_id"]
    settings = client.patch(f"/api/datasets/{settings_dataset_id}/columns", json={
        "columns": [
            {"name": "person_id", "label": "Person ID", "logical_type": "number",
             "filter_kind": "range"},
            {"name": "value_text", "logical_type": "number", "filter_kind": "range"},
            {"name": "mapping :ghost", "label": "Source map"},
        ],
    })
    assert settings.status_code == 200, settings.text
    replaced = client.post(
        f"/api/datasets/{settings_dataset_id}/derive", json={
            "op": "map", "name": "value_text", "column": "mapping :ghost",
            "mapping": {live_derive_tables["needle"]: "matched safely"},
            "default": "other",
        })
    assert replaced.status_code == 200, replaced.text
    replaced_profile = next(c for c in replaced.json()["columns"]
                            if c["name"] == "value_text")
    assert replaced_profile["logical_type"] is None
    derived_ref = replaced.json()["source_ref"]
    datasets._store.clear()
    reopened_again = client.post("/api/datasets/open", json={
        "source_ref": derived_ref,
    })
    assert reopened_again.status_code == 200, reopened_again.text
    profiles = {c["name"]: c for c in reopened_again.json()["columns"]}
    assert profiles["person_id"]["label"] == "Person ID"
    assert profiles["mapping :ghost"]["label"] == "Source map"
    assert profiles["value_text"]["logical_type"] is None
    replaced_late = _query(client, reopened_again.json()["dataset_id"], [100005])
    assert replaced_late.status_code == 200, replaced_late.text
    assert replaced_late.json()["rows"]["data"][0][
        _column(replaced_late.json(), "value_text")] == "matched safely"

    labeled = client.patch(
        f"/api/datasets/{reopened_again.json()['dataset_id']}/columns", json={
            "columns": [{"name": "value_text", "label": "Mapped output"}],
        })
    assert labeled.status_code == 200, labeled.text
    datasets._store.clear()
    reopened_final = client.post("/api/datasets/open", json={
        "source_ref": labeled.json()["source_ref"],
    })
    assert reopened_final.status_code == 200, reopened_final.text
    profiles = {c["name"]: c for c in reopened_final.json()["columns"]}
    assert profiles["person_id"]["label"] == "Person ID"
    assert profiles["mapping :ghost"]["label"] == "Source map"
    assert profiles["value_text"]["label"] == "Mapped output"

    reopened_id = reopened_final.json()["dataset_id"]
    prior = datasets.get(reopened_id)
    old_frame = prior["df"].copy(deep=True)
    old_live = copy.deepcopy(prior["live_source"])
    old_ref = copy.deepcopy(prior["source_ref"])
    with engine.begin() as conn:
        conn.execute(text(f'DROP TABLE public."{live_derive_tables["people"]}"'))
    failed = client.post(f"/api/datasets/{reopened_id}/derive", json={
        "op": "formula", "name": "db_failure", "left": "value_text",
        "operator": "+", "right": "1",
    })
    assert failed.status_code == 502, failed.text
    after = datasets.get(reopened_id)
    pd.testing.assert_frame_equal(after["df"], old_frame)
    assert after["live_source"] == old_live
    assert after["source_ref"] == old_ref
