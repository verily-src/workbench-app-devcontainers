import time
import uuid

import pytest
from sqlalchemy import text

import datasets


def _wait_job(client, response):
    assert response.status_code == 200, response.text
    job_id = response.json().get("job_id")
    assert job_id
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        current = client.get(f"/api/views/jobs/{job_id}")
        assert current.status_code == 200, current.text
        job = current.json()
        if job["status"] == "complete":
            return job
        if job["status"] == "failed":
            return job
        time.sleep(0.02)
    pytest.fail("Saved view job did not finish.")


def _open(client, resource_id, table):
    response = client.post("/api/datasets/open", json={
        "source_ref": {"kind": "aurora", "resource_id": resource_id,
                       "schema": "public", "table": table},
    })
    assert response.status_code == 200, response.text
    return response.json()


def _join(client, left, right):
    response = client.post("/api/datasets/join", json={
        "left_id": left["dataset_id"], "right_id": right["dataset_id"],
        "left_on": "person_id", "right_on": "person_id", "how": "inner",
    })
    assert response.status_code == 200, response.text
    return response.json()


def _query_entities(client, dataset_id):
    response = client.post(f"/api/datasets/{dataset_id}/query", json={
        "entity_column": "person_id", "page": 0, "page_size": 20,
    })
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def snapshot_tables(client, engine):
    suffix = uuid.uuid4().hex[:10]
    people = f"snapshot_people_{suffix}"
    events = f"snapshot_events_{suffix}"
    doomed = f"snapshot_doomed_{suffix}"
    name = f"snapshot-{suffix}"
    with engine.begin() as conn:
        conn.execute(text(f'CREATE TABLE public."{people}" (person_id integer, label text)'))
        conn.execute(text(f'CREATE TABLE public."{events}" (person_id integer, event text)'))
        conn.execute(text(f'CREATE TABLE public."{doomed}" (person_id integer, marker text)'))
        conn.execute(text(f'INSERT INTO public."{people}" VALUES (1, \'one\'), (2, \'two\')'))
        conn.execute(text(f'INSERT INTO public."{events}" VALUES (1, \'a\'), (2, \'b\')'))
        conn.execute(text(f'INSERT INTO public."{doomed}" VALUES (1, \'x\'), (2, \'y\')'))
    yield {"people": people, "events": events, "doomed": doomed, "name": name,
           "resource_id": "omopdb"}
    datasets._store.clear()
    client.delete("/api/views", params={
        "kind": "aurora", "resource_id": "omopdb", "name": name,
    })
    with engine.begin() as conn:
        conn.execute(text(f'DROP TABLE IF EXISTS public."{people}"'))
        conn.execute(text(f'DROP TABLE IF EXISTS public."{events}"'))
        conn.execute(text(f'DROP TABLE IF EXISTS public."{doomed}"'))


def test_saved_snapshot_save_open_cache_refresh_failure_and_delete(
        client, engine, snapshot_tables, monkeypatch):
    people = snapshot_tables["people"]
    events = snapshot_tables["events"]
    doomed = snapshot_tables["doomed"]
    name = snapshot_tables["name"]
    resource_id = snapshot_tables["resource_id"]
    opened_people = _open(client, resource_id, people)
    opened_events = _open(client, resource_id, events)
    joined = _join(client, opened_people, opened_events)
    declared = {"entity": "person", "keys": ["person_id"]}
    configured = client.put(f"/api/datasets/{joined['dataset_id']}/grain", json=declared)
    assert configured.status_code == 200, configured.text
    joined["source_ref"] = configured.json()["source_ref"]
    saved = client.post("/api/views", json={
        "kind": "aurora", "resource_id": resource_id, "name": name,
        "datasets": [{"source": joined["source_ref"], "title": "Joined data"}],
    })
    completed = _wait_job(client, saved)
    assert completed["status"] == "complete", completed
    assert completed["completed_sources"] == completed["total_sources"] == 1
    owner_cookies = dict(client.cookies)
    client.cookies.clear()
    try:
        hidden_job = client.get(f"/api/views/jobs/{completed['job_id']}")
        assert hidden_job.status_code == 404
    finally:
        client.cookies.clear()
        client.cookies.update(owner_cookies)


    saved_state = client.get("/api/views/one", params={
        "kind": "aurora", "resource_id": resource_id, "name": name,
    })
    assert saved_state.status_code == 200, saved_state.text
    materialized_ref = saved_state.json()["datasets"][0]["source"]
    assert materialized_ref["kind"] == "materialized"
    assert materialized_ref["grain"] == declared
    opened_snapshot = client.post("/api/datasets/open", json={
        "source_ref": materialized_ref,
    })
    assert opened_snapshot.status_code == 200, opened_snapshot.text
    snapshot_id = opened_snapshot.json()["dataset_id"]
    import boto3
    import io
    import types
    import views
    s3_objects = {}
    def put_object(**values):
        s3_objects[values["Key"]] = values["Body"]
    transport = types.SimpleNamespace(
        put_object=put_object,
        get_object=lambda **values: {"Body": io.BytesIO(s3_objects[values["Key"]])})
    monkeypatch.setattr(views, "_registered_s3_view_location",
                        lambda rid, view: ("fixture-bucket", view + ".json", "", "us-east-1"))
    monkeypatch.setattr(boto3, "Session", lambda **kwargs: types.SimpleNamespace(
        client=lambda *args, **kwargs: transport))
    portable = client.post("/api/views", json={
        "kind": "s3", "resource_id": "s3:fixture", "name": name,
        "datasets": [{"source": materialized_ref, "title": "Portable join"}],
    })
    assert portable.status_code == 200, portable.text
    portable_state = client.get("/api/views/one", params={
        "kind": "s3", "resource_id": "s3:fixture", "name": name}).json()
    assert portable_state["datasets"][0]["source"]["kind"] == "join"
    assert "materialized_id" not in str(portable_state)
    assert portable_state["datasets"][0]["source"]["grain"] == declared
    first_query = _query_entities(client, snapshot_id)
    assert first_query["entity"]["total"] == 2
    assert first_query["cache"]["hit"] is False

    with engine.begin() as conn:
        conn.execute(text(f'INSERT INTO public."{people}" VALUES (3, \'three\')'))
        conn.execute(text(f'INSERT INTO public."{events}" VALUES (3, \'c\')'))
    cached_query = _query_entities(client, snapshot_id)
    assert cached_query["entity"]["total"] == 2
    assert cached_query["cache"]["hit"] is True

    refreshed = client.post("/api/views/refresh", json={
        "kind": "aurora", "resource_id": resource_id, "name": name,
    })
    refresh_job = _wait_job(client, refreshed)
    assert refresh_job["status"] == "complete", refresh_job
    updated_query = _query_entities(client, snapshot_id)
    assert updated_query["entity"]["total"] == 3
    assert updated_query["cache"]["hit"] is False

    with engine.begin() as conn:
        conn.exec_driver_sql(f'ALTER TABLE public."{events}" ENABLE ROW LEVEL SECURITY')
    try:
        failed_refresh = _wait_job(client, client.post("/api/views/refresh", json={
            "kind": "aurora", "resource_id": resource_id, "name": name,
        }))
        assert failed_refresh["status"] == "failed"
        assert "row-level security" in failed_refresh["error"]
        assert _query_entities(client, snapshot_id)["entity"]["total"] == 3
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql(f'ALTER TABLE public."{events}" DISABLE ROW LEVEL SECURITY')

    shared_name = name + "-shared"
    shared_save = client.post("/api/views", json={
        "kind": "aurora", "resource_id": resource_id, "name": shared_name,
        "datasets": [{"source": materialized_ref, "title": "Shared snapshot"}],
    })
    assert _wait_job(client, shared_save)["status"] == "complete"
    deleted_shared = client.delete("/api/views", params={
        "kind": "aurora", "resource_id": resource_id, "name": shared_name,
    })
    assert deleted_shared.status_code == 200, deleted_shared.text
    reopened = client.post("/api/datasets/open", json={"source_ref": materialized_ref})
    assert reopened.status_code == 200, reopened.text
    assert _query_entities(client, reopened.json()["dataset_id"])["entity"]["total"] == 3

    opened_doomed = _open(client, resource_id, doomed)
    failed_join = _join(client, opened_people, opened_doomed)
    assert failed_join["query_scope"] == "database"
    with engine.begin() as conn:
        conn.execute(text(f'DROP TABLE public."{doomed}"'))
    failed_save = client.post("/api/views", json={
        "kind": "aurora", "resource_id": resource_id, "name": name,
        "datasets": [{"source": failed_join["source_ref"], "title": "Broken input"}],
    })
    failure_job = _wait_job(client, failed_save)
    assert failure_job["status"] == "failed"
    still_saved = client.get("/api/views/one", params={
        "kind": "aurora", "resource_id": resource_id, "name": name,
    })
    assert still_saved.status_code == 200, still_saved.text
    assert still_saved.json()["datasets"][0]["source"] == materialized_ref

    with engine.connect() as conn:
        physical_name = conn.execute(text(
            "SELECT physical_name FROM public._studio_materialized_sources "
            "WHERE resource_id = :resource_id AND materialized_id = :id"), {
                "resource_id": resource_id,
                "id": materialized_ref["materialized_id"],
            }).scalar_one()
    blocked_table = client.post("/api/datasets/open", json={"source_ref": {
        "kind": "aurora", "resource_id": resource_id, "schema": "public",
        "table": physical_name}})
    assert blocked_table.status_code in {400, 422}, blocked_table.text
    blocked_sql = client.post("/api/datasets/open", json={"source_ref": {
        "kind": "sql", "resource_id": resource_id,
        "sql": f'SELECT * FROM public."{physical_name}"'}})
    assert blocked_sql.status_code in {400, 422}, blocked_sql.text
    import main
    listed = main.db.list_aurora_tables(resource_id)
    assert physical_name not in str(listed)
    datasets._store.clear()
    deleted = client.delete("/api/views", params={
        "kind": "aurora", "resource_id": resource_id, "name": name,
    })
    assert deleted.status_code == 200, deleted.text
    with engine.connect() as conn:
        assert conn.execute(text("SELECT pg_catalog.to_regclass(:name)"), {
            "name": f'public."{physical_name}"',
        }).scalar_one() is None
        assert conn.execute(text(
            "SELECT count(*) FROM public._studio_materialized_sources "
            "WHERE resource_id = :resource_id AND materialized_id = :id"), {
                "resource_id": resource_id,
                "id": materialized_ref["materialized_id"],
            }).scalar_one() == 0
    portable_open = client.post("/api/datasets/open", json={
        "source_ref": portable_state["datasets"][0]["source"]})
    assert portable_open.status_code == 200, portable_open.text
    assert _query_entities(client, portable_open.json()["dataset_id"])["entity"]["total"] == 3


def test_omop_join_snapshot_save_reopen_refresh(client, engine, info, snapshot_tables):
    import omop

    name = snapshot_tables["name"]
    events = snapshot_tables["events"]
    spec = {"criteria": [{"domain": "condition", "concept_ids": [192671],
                          "descendants": False}]}
    genotypes = snapshot_tables["doomed"]
    expected = omop.count(engine, info, spec)["persons"]
    assert expected > 0
    with engine.begin() as conn:
        conn.execute(text(f'DELETE FROM public."{events}"'))
        conn.execute(text(f'INSERT INTO public."{events}" '
                          "SELECT person_id, 'sample' FROM cdm.person"))
        conn.execute(text(f'DELETE FROM public."{genotypes}"'))
        conn.execute(text(f'INSERT INTO public."{genotypes}" '
                          "SELECT person_id, 'genotype' FROM cdm.person"))
    opened = client.post("/api/datasets/open", json={"source_ref": {
        "kind": "omop_cohort", "resource_id": "omopdb", "spec": spec}})
    assert opened.status_code == 200, opened.text
    joined = _join(client, opened.json(), _open(client, "omopdb", events))
    joined = _join(client, joined, _open(client, "omopdb", genotypes))
    assert joined["query_scope"] == "database"
    job = _wait_job(client, client.post("/api/views", json={
        "kind": "aurora", "resource_id": "omopdb", "name": name,
        "datasets": [{"source": joined["source_ref"], "title": "OMOP samples"}],
    }))
    assert job["status"] == "complete", job
    assert job["materialized_sources"] == 1
    state = client.get("/api/views/one", params={
        "kind": "aurora", "resource_id": "omopdb", "name": name}).json()
    ref = state["datasets"][0]["source"]
    assert ref["kind"] == "materialized"
    datasets._store.clear()
    reopened = client.post("/api/datasets/open", json={"source_ref": ref})
    assert reopened.status_code == 200, reopened.text
    dataset_id = reopened.json()["dataset_id"]
    assert _query_entities(client, dataset_id)["entity"]["total"] == expected
    derived = client.post(f"/api/datasets/{dataset_id}/derive", json={
        "op": "formula", "name": "person_plus_one", "left": "person_id",
        "operator": "+", "right": "1"})
    assert derived.status_code == 200, derived.text
    assert _query_entities(client, dataset_id)["entity"]["total"] == expected
    joined_snapshot = _join(client, {"dataset_id": dataset_id}, _open(client, "omopdb", events))
    saved_again = _wait_job(client, client.post("/api/views", json={
        "kind": "aurora", "resource_id": "omopdb", "name": name,
        "datasets": [{"source": joined_snapshot["source_ref"], "title": "Snapshot derived join"}],
    }))
    assert saved_again["status"] == "complete", saved_again
    assert saved_again["materialized_sources"] == 1
    with engine.begin() as conn:
        conn.execute(text(f'DELETE FROM public."{events}"'))
    refresh = _wait_job(client, client.post("/api/views/refresh", json={
        "kind": "aurora", "resource_id": "omopdb", "name": name,
    }))
    assert refresh["status"] == "complete", refresh
    assert _query_entities(client, dataset_id)["entity"]["total"] == 0
