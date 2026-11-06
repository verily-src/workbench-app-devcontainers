import io
import json
import types

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, insert, text

import datasets
import main
import views
from tests.test_saved_snapshots import _join, _open, _wait_job, snapshot_tables  # noqa: F401

api = TestClient(main.app)


def _dataset(title="x", values=("liver",)):
    return {"source": {"kind": "s3", "resource_id": "folder", "table": "x.csv"},
            "title": title,
            "filters": [{"column": "tissue", "kind": "categorical", "values": list(values)}],
            "charts": [{"kind": "bar", "x": "tissue"}]}


def _save(kind, resource_id, name, dataset):
    response = api.post("/api/views", json={
        "kind": kind, "resource_id": resource_id, "name": name, "datasets": [dataset]})
    assert response.status_code == 200, response.text


def _listed(kind, resource_id, name):
    rows = api.get("/api/views", params={"kind": kind, "resource_id": resource_id}).json()
    return next(row for row in rows if row["name"] == name)


def _filters(state):
    return state["datasets"][0]["filters"][0]["values"]


@pytest.fixture
def sqlite_store(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'views.db'}")
    monkeypatch.setattr(views.db, "get_engine_for_resource", lambda rid: engine)
    monkeypatch.setattr(main.lineage, "record", lambda *a, **k: None)
    monkeypatch.setattr(views, "_actor", lambda: "analyst@example.org")
    views._prepared.clear()
    yield engine
    views._prepared.clear()


class _ClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


@pytest.fixture
def s3_store(monkeypatch):
    objects = {}

    class Client:
        def put_object(self, **kwargs):
            if kwargs.get("IfNoneMatch") == "*" and kwargs["Key"] in objects:
                raise _ClientError("PreconditionFailed")
            objects[kwargs["Key"]] = kwargs["Body"]

        def get_object(self, **kwargs):
            if kwargs["Key"] not in objects:
                raise _ClientError("NoSuchKey")
            return {"Body": io.BytesIO(objects[kwargs["Key"]])}

        def delete_object(self, **kwargs):
            objects.pop(kwargs["Key"], None)

        def get_paginator(self, operation):
            return self

        def paginate(self, **kwargs):
            return [{"Contents": [{"Key": key} for key in sorted(objects)
                                  if key.startswith(kwargs["Prefix"])]}]

    import boto3
    monkeypatch.setattr(boto3, "Session", lambda **kwargs: types.SimpleNamespace(
        client=lambda *args, **kwargs: Client()))
    monkeypatch.setattr(views, "_registered_s3_view_location", lambda rid, view: (
        "bucket", f"lake/_studio_views/{view}.json", "lake/_studio_views/", "us-east-1"))
    monkeypatch.setattr(views, "_actor", lambda: "analyst@example.org")
    monkeypatch.setattr(main.lineage, "record", lambda *a, **k: None)
    return objects


@pytest.mark.parametrize("store", ["sqlite_store", "s3_store"])
def test_publish_view_and_rollback_draft(request, store):
    request.getfixturevalue(store)
    kind, resource_id = ("aurora", "db1") if store == "sqlite_store" else ("s3", "s3:lake")
    name = "liver cohort"
    _save(kind, resource_id, name, _dataset())
    assert _listed(kind, resource_id, name)["published_revision"] is None

    published = api.post("/api/views/publish", json={
        "kind": kind, "resource_id": resource_id, "name": name, "note": "  Approved  "})
    assert published.status_code == 200, published.text
    first = published.json()
    assert first["revision"] == 1 and first["note"] == "Approved"
    assert first["published_by"] == "analyst@example.org" and first["published_at"]
    row = _listed(kind, resource_id, name)
    assert (row["published_revision"], row["draft_changed"]) == (1, False)

    _save(kind, resource_id, name, _dataset(values=("lung",)))
    row = _listed(kind, resource_id, name)
    assert (row["published_revision"], row["draft_changed"]) == (1, True)
    latest = api.get("/api/views/revision", params={
        "kind": kind, "resource_id": resource_id, "name": name}).json()
    assert _filters(latest) == ["liver"]
    assert latest["published"]["revision"] == 1 and "created_by" not in latest

    second = api.post("/api/views/publish", json={
        "kind": kind, "resource_id": resource_id, "name": name}).json()
    assert second["revision"] == 2 and second["note"] is None
    revisions = api.get("/api/views/revisions", params={
        "kind": kind, "resource_id": resource_id, "name": name}).json()["revisions"]
    assert [item["revision"] for item in revisions] == [2, 1]
    assert revisions[1]["note"] == "Approved"
    old = api.get("/api/views/revision", params={
        "kind": kind, "resource_id": resource_id, "name": name, "revision": "1"}).json()
    assert _filters(old) == ["liver"]

    rolled = api.post("/api/views/rollback", json={
        "kind": kind, "resource_id": resource_id, "name": name, "revision": 1})
    assert rolled.status_code == 200, rolled.text
    draft = api.get("/api/views/one", params={
        "kind": kind, "resource_id": resource_id, "name": name}).json()
    assert _filters(draft) == ["liver"]
    row = _listed(kind, resource_id, name)
    assert (row["published_revision"], row["draft_changed"]) == (2, True)
    for revision, values in ((1, ["liver"]), (2, ["lung"])):
        assert _filters(api.get("/api/views/revision", params={
            "kind": kind, "resource_id": resource_id, "name": name,
            "revision": revision}).json()) == values

    api.delete("/api/views", params={"kind": kind, "resource_id": resource_id, "name": name})
    gone = api.get("/api/views/revision", params={
        "kind": kind, "resource_id": resource_id, "name": name})
    assert gone.status_code == 404
    _save(kind, resource_id, name, _dataset())
    assert _listed(kind, resource_id, name)["published_revision"] is None


def test_publish_validation_and_immutability(sqlite_store):
    _save("aurora", "db1", "report", _dataset())
    base = {"kind": "aurora", "resource_id": "db1", "name": "report"}
    assert api.post("/api/views/publish", json=base).status_code == 200

    invalid = [
        ("post", "/api/views/publish", {"json": {**base, "note": "x" * 501}}),
        ("post", "/api/views/publish", {"json": {**base, "note": "bad\x00note"}}),
        ("post", "/api/views/publish", {"json": {**base, "revision": 1}}),
        ("post", "/api/views/publish", {"json": {**base, "name": "../escape"}}),
        ("post", "/api/views/publish", {"json": {**base, "kind": "bigquery"}}),
        ("post", "/api/views/rollback", {"json": {**base, "revision": 0}}),
        ("post", "/api/views/rollback", {"json": {**base, "revision": "1"}}),
        ("post", "/api/views/rollback", {"json": base}),
        ("get", "/api/views/revision", {"params": {**base, "revision": "abc"}}),
        ("get", "/api/views/revision", {"params": {**base, "revision": "0"}}),
        ("get", "/api/views/revision", {"params": {**base, "state": "{}"}}),
        ("get", "/api/views/revisions", {"params": {"kind": "aurora", "name": "report"}}),
    ]
    for method, url, kwargs in invalid:
        response = getattr(api, method)(url, **kwargs)
        assert response.status_code == 422, (url, kwargs, response.text)

    missing = api.post("/api/views/publish", json={**base, "name": "nope"})
    assert missing.status_code == 404 and "not found" in missing.json()["detail"]
    assert api.get("/api/views/revision", params={**base, "revision": 9}).status_code == 404
    assert api.post("/api/views/rollback", json={**base, "revision": 9}).status_code == 404

    for method in ("put", "patch", "delete"):
        assert getattr(api, method)("/api/views/revision", params={
            **base, "revision": 1}).status_code == 405
    assert api.put("/api/views/publish", json=base).status_code == 405

    with sqlite_store.begin() as conn:
        conn.execute(insert(views.revision_table).values(
            view_name="report", revision=2, published_at=views.datetime.now(views.timezone.utc),
            state_hash="x", state="{}"))
    from sqlalchemy import func
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(views, "func", types.SimpleNamespace(
            max=lambda column: func.max(column) - 1))
        conflict = api.post("/api/views/publish", json=base)
    assert conflict.status_code == 409 and "Another publish" in conflict.json()["detail"]


def test_existing_views_list_as_unpublished_drafts(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    views.view_table.create(engine)
    with engine.begin() as conn:
        conn.execute(insert(views.view_table).values(
            name="legacy", created_by="old", state=json.dumps({"version": 2, "datasets": []})))
    monkeypatch.setattr(views.db, "get_engine_for_resource", lambda rid: engine)
    views._prepared.clear()
    rows = views.list_views("aurora", "db1")
    assert rows[0]["name"] == "legacy"
    assert rows[0]["published_revision"] is None and rows[0]["draft_changed"] is None


def test_s3_publish_conflict_returns_409(s3_store, monkeypatch):
    _save("s3", "s3:lake", "report", _dataset())
    base = {"kind": "s3", "resource_id": "s3:lake", "name": "report"}
    assert api.post("/api/views/publish", json=base).json()["revision"] == 1
    monkeypatch.setattr(views, "_s3_revision_numbers", lambda root, name=None: {})
    conflict = api.post("/api/views/publish", json=base)
    assert conflict.status_code == 409, conflict.text
    assert list(k for k in s3_store if "_revisions" in k) == [
        "lake/_studio_views/_revisions/report/000001.json"]
    assert json.loads(s3_store["lake/_studio_views/_revisions/report/000001.json"])[
        "revision"] == 1


def test_publish_and_rollback_wait_for_running_draft_job(sqlite_store, monkeypatch):
    _save("aurora", "db1", "report", _dataset())
    base = {"kind": "aurora", "resource_id": "db1", "name": "report"}
    assert api.post("/api/views/publish", json=base).status_code == 200
    monkeypatch.setattr(main.view_jobs, "running", lambda key: key == "db1:report")
    for url, body in (("/api/views/publish", base),
                      ("/api/views/rollback", {**base, "revision": 1})):
        blocked = api.post(url, json=body)
        assert blocked.status_code == 409 and "still running" in blocked.json()["detail"]
    assert len(views.list_revisions("aurora", "db1", "report")) == 1


def test_s3_revision_failure_reports_unknown_status(s3_store, monkeypatch):
    _save("s3", "s3:lake", "report", _dataset())
    def fail(*args, **kwargs):
        raise RuntimeError("S3 view revisions could not be listed.")
    monkeypatch.setattr(views, "_s3_revision_numbers", fail)
    row = views.list_views("s3", "s3:lake")[0]
    assert row["name"] == "report" and row["publication_unknown"] is True
    assert row["published_revision"] is None


def test_s3_cli_publish_uses_conditional_put(monkeypatch):
    calls = []
    draft = json.dumps({"version": 2, "datasets": [], "created_by": "a"})

    def run(args, **kwargs):
        calls.append(args)
        if args[:3] == ["aws", "s3", "cp"]:
            return types.SimpleNamespace(returncode=0, stdout=draft, stderr="")
        if args[:3] == ["aws", "s3api", "list-objects-v2"]:
            return types.SimpleNamespace(returncode=0, stdout=json.dumps({"Contents": [
                {"Key": "views/_studio_views/_revisions/r/000004.json"}]}), stderr="")
        return types.SimpleNamespace(
            returncode=254, stdout="",
            stderr="An error occurred (PreconditionFailed) when calling PutObject")

    monkeypatch.setattr(views, "_registered_s3_view_location", lambda rid, view: None)
    monkeypatch.setattr(views.db, "resolve_s3_uri", lambda rid: "s3://bucket/views")
    monkeypatch.setattr(views.cloud_cli, "run", run)
    monkeypatch.setattr(views, "_actor", lambda: "a")
    with pytest.raises(views.RevisionConflict):
        views.publish_view("s3", "lake", "r", None)
    put = next(args for args in calls if args[:3] == ["aws", "s3api", "put-object"])
    assert put[put.index("--key") + 1] == "views/_studio_views/_revisions/r/000005.json"
    assert put[put.index("--if-none-match") + 1] == "*"
    assert put[put.index("--bucket") + 1] == "bucket"


def test_s3_cli_delete_keeps_draft_when_revision_delete_fails(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if args[:3] == ["aws", "s3api", "list-objects-v2"]:
            return types.SimpleNamespace(returncode=0, stdout=json.dumps({"Contents": [
                {"Key": "views/_studio_views/_revisions/r/000001.json"}]}), stderr="")
        return types.SimpleNamespace(returncode=1, stdout="", stderr="AccessDenied")

    monkeypatch.setattr(views, "_registered_s3_view_location", lambda rid, view: None)
    monkeypatch.setattr(views.db, "resolve_s3_uri", lambda rid: "s3://bucket/views")
    monkeypatch.setattr(views.cloud_cli, "run", run)
    response = api.delete("/api/views", params={"kind": "s3", "resource_id": "lake", "name": "r"})
    assert response.status_code == 502 and "could not be deleted" in response.json()["detail"]
    assert ["aws", "s3", "rm", "s3://bucket/views/_studio_views/r.json",
            "--profile", "lake"] not in calls


def _snapshot_exists(engine, resource_id, materialized_id):
    with engine.connect() as conn:
        return conn.execute(text(
            "SELECT count(*) FROM public._studio_materialized_sources "
            "WHERE resource_id = :resource_id AND materialized_id = :id"),
            {"resource_id": resource_id, "id": materialized_id}).scalar_one() == 1


def test_published_revision_pins_its_snapshot(client, engine, snapshot_tables, monkeypatch):
    monkeypatch.setattr(main.lineage, "record", lambda *a, **k: None)
    name, resource_id = snapshot_tables["name"], snapshot_tables["resource_id"]
    people = _open(client, resource_id, snapshot_tables["people"])
    events = _open(client, resource_id, snapshot_tables["events"])
    join_ref = _join(client, people, events)["source_ref"]
    body = {"kind": "aurora", "resource_id": resource_id, "name": name,
            "datasets": [{"source": join_ref, "title": "Joined"}]}
    assert _wait_job(client, client.post("/api/views", json=body))["status"] == "complete"
    view = {"kind": "aurora", "resource_id": resource_id, "name": name}
    first_ref = client.get("/api/views/one", params=view).json()["datasets"][0]["source"]
    assert first_ref["kind"] == "materialized"
    published = client.post("/api/views/publish", json={**view, "note": "v1"})
    assert published.status_code == 200, published.text

    datasets._store.clear()
    assert _wait_job(client, client.post("/api/views", json=body))["status"] == "complete"
    second_ref = client.get("/api/views/one", params=view).json()["datasets"][0]["source"]
    assert second_ref["materialized_id"] != first_ref["materialized_id"]
    assert _snapshot_exists(engine, resource_id, first_ref["materialized_id"])
    listed = next(row for row in client.get("/api/views", params={
        "kind": "aurora", "resource_id": resource_id}).json() if row["name"] == name)
    assert listed["published_revision"] == 1 and listed["draft_changed"] is True

    revision = client.get("/api/views/revision", params=view).json()
    assert revision["datasets"][0]["source"] == first_ref
    reopened = client.post("/api/datasets/open", json={"source_ref": first_ref})
    assert reopened.status_code == 200, reopened.text

    datasets._store.clear()
    rolled = client.post("/api/views/rollback", json={**view, "revision": 1})
    assert rolled.status_code == 200, rolled.text
    draft = client.get("/api/views/one", params=view).json()
    assert draft["datasets"][0]["source"] == first_ref
    assert draft["datasets"][0]["snapshot"]["status"] == "materialized"
    assert not _snapshot_exists(engine, resource_id, second_ref["materialized_id"])
    listed = next(row for row in client.get("/api/views", params={
        "kind": "aurora", "resource_id": resource_id}).json() if row["name"] == name)
    assert listed["draft_changed"] is False

    assert client.delete("/api/views", params=view).status_code == 200
    assert not _snapshot_exists(engine, resource_id, first_ref["materialized_id"])
    with engine.connect() as conn:
        assert conn.execute(text(
            "SELECT count(*) FROM public._studio_view_revisions WHERE view_name = :name"),
            {"name": name}).scalar_one() == 0
