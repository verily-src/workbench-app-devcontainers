"""Saved views keep dashboard filters; pydantic rejects ones the browser can't merge."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

import main

TAB = {"source": {"kind": "s3", "resource_id": "folder", "table": "x.csv"}, "title": "x",
       "filters": [], "charts": []}
SEX = {"column": "sex", "kind": "categorical", "values": ["F"]}


@pytest.fixture
def client(monkeypatch, tmp_path):
    import views
    engine = create_engine(f"sqlite:///{tmp_path/'views.db'}")
    monkeypatch.setattr(main.db, "get_engine_for_resource", lambda rid: engine)
    monkeypatch.setattr(views.db, "get_engine_for_resource", lambda rid: engine)
    monkeypatch.setattr(main.lineage, "record", lambda *a, **k: None)
    views._prepared.clear()
    return TestClient(main.app)


def _save(client, dashboard, name="dash"):
    return client.post("/api/views", json={"kind": "aurora", "resource_id": "db1", "name": name,
                                           "active": 0, "datasets": [TAB], "dashboard_filters": dashboard})


def test_dashboard_filters_round_trip_and_revisions_keep_them(client):
    age = {"column": "age", "kind": "range", "min": 40.0, "max": 60.0}
    when = {"column": "visit_date", "kind": "date", "last": 2, "unit": "year"}
    assert _save(client, [SEX, age, when]).status_code == 200
    got = client.get("/api/views/one?kind=aurora&resource_id=db1&name=dash").json()
    assert got["dashboard_filters"] == [SEX, age, when]
    published = client.post("/api/views/publish", json={"kind": "aurora", "resource_id": "db1", "name": "dash"})
    assert published.status_code == 200, published.text
    revision = client.get("/api/views/revision?kind=aurora&resource_id=db1&name=dash").json()
    assert revision["dashboard_filters"] == [SEX, age, when]
    # Changing only the dashboard filters marks the draft as changed.
    assert _save(client, [SEX]).status_code == 200
    rows = client.get("/api/views", params={"kind": "aurora", "resource_id": "db1"}).json()
    listed = next(v for v in rows if v["name"] == "dash")
    assert listed["draft_changed"] is True


def test_views_without_dashboard_filters_still_save(client):
    saved = client.post("/api/views", json={"kind": "aurora", "resource_id": "db1", "name": "old",
                                            "active": 0, "datasets": [TAB]})
    assert saved.status_code == 200, saved.text
    assert client.get("/api/views/one?kind=aurora&resource_id=db1&name=old").json()["dashboard_filters"] == []


@pytest.mark.parametrize("dashboard, message", [
    ([{"kind": "any", "groups": [[SEX]]}], "criteria group"),
    ([{"column": "age", "kind": "range", "min": 1.0, "max": 2.0, "param": {"min": "lo"}}], "tab parameter"),
    ([SEX, {**SEX, "values": ["M"]}], "one dashboard filter per column"),
    ([{"column": "sex", "kind": "bogus"}], "kind"),
    ([SEX] * 21, "at most 20"),
])
def test_bad_dashboard_filters_are_rejected(client, dashboard, message):
    response = _save(client, dashboard)
    assert response.status_code == 422
    assert message in response.text


def test_compare_stays_inside_the_dashboard_scope(client):
    import pandas as pd
    import datasets
    frame = pd.DataFrame({"site": ["x"] * 6 + ["y"] * 4, "sex": list("FFFMMM") + list("FFMM")})
    opened = datasets.open_dataset(frame, "people")
    body = {"filters_a": [SEX], "filters_b": [], "b_is_rest": True,
            "scope": [{"column": "site", "kind": "categorical", "values": ["x"]}]}
    got = client.post(f"/api/datasets/{opened['dataset_id']}/compare", json=body).json()
    assert (got["a_n"], got["b_n"]) == (3, 3)          # rest = site x minus A, not every other row
    body.update(b_is_rest=False, filters_b=[{"column": "sex", "kind": "categorical", "values": ["M"]}])
    got = client.post(f"/api/datasets/{opened['dataset_id']}/compare", json=body).json()
    assert (got["a_n"], got["b_n"]) == (3, 3)
