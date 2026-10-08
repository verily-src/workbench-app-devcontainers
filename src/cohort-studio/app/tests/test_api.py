"""API tests: the full upload → profile → cross-filter → export loop
against the real FastAPI app, no workspace needed."""

from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import main

FIXTURE = Path(__file__).parent / "fixtures" / "samples.csv"
client = TestClient(main.app)


def _open_fixture() -> dict:
    with open(FIXTURE, "rb") as f:
        resp = client.post("/api/datasets/upload",
                           files={"file": ("samples.csv", f, "text/csv")})
    assert resp.status_code == 200
    return resp.json()


def test_health():
    assert client.get("/api/health").json() == {"ok": True}


def test_upload_profiles_columns():
    body = _open_fixture()
    assert body["rows"] == 100
    cols = {c["name"]: c for c in body["columns"]}
    assert cols["tissue"]["filter_kind"] == "categorical"
    assert sorted(cols["tissue"]["values"]) == ["heart", "liver", "lung", "skin"]
    assert cols["rin_score"]["filter_kind"] == "range"
    assert cols["sample_id"]["filter_kind"] == "none"


def test_query_crossfilters_charts_and_rows():
    body = _open_fixture()
    resp = client.post(f"/api/datasets/{body['dataset_id']}/query", json={
        "filters": [{"column": "tissue", "kind": "categorical",
                     "values": ["liver"]}],
        "charts": [{"kind": "bar", "x": "tissue"},
                   {"kind": "histogram", "x": "rin_score"}],
        "page": 0, "page_size": 10,
    })
    assert resp.status_code == 200
    out = resp.json()
    assert out["total"] == 100
    assert out["filtered"] == 25
    bar = out["charts"][0]
    by_cat = {r["category"]: r for r in bar["data"]}
    assert by_cat["liver"] == {"category": "liver", "all": 25, "selected": 25}
    assert by_cat["lung"]["selected"] == 0
    hist = out["charts"][1]
    assert sum(b["all"] for b in hist["data"]) == 100
    assert sum(b["selected"] for b in hist["data"]) == 25
    assert len(out["rows"]["data"]) == 10


def test_export_respects_filters():
    body = _open_fixture()
    resp = client.post(f"/api/datasets/{body['dataset_id']}/export", json={
        "filters": [{"column": "tissue", "kind": "categorical",
                     "values": ["liver"]}]})
    assert resp.status_code == 200
    lines = resp.text.strip().split("\n")
    assert len(lines) == 26  # header + 25 liver rows


def test_unknown_dataset_is_404():
    resp = client.post("/api/datasets/nope/query", json={})
    assert resp.status_code == 404


def test_ingest_dataframe_roundtrips_to_sqlite():
    import queries
    from sqlalchemy import create_engine
    df = pd.read_csv(FIXTURE)
    engine = create_engine("sqlite:///:memory:")
    n = queries.ingest_dataframe(engine, df, "my_cohort")
    assert n == 100
    back = pd.read_sql_query("SELECT * FROM my_cohort", engine)
    assert len(back) == 100
    assert list(back.columns) == list(df.columns)


def test_ingest_dataframe_rejects_bad_name():
    import queries
    from sqlalchemy import create_engine
    with pytest.raises(ValueError):
        queries.ingest_dataframe(create_engine("sqlite:///:memory:"),
                                 pd.DataFrame({"a": [1]}),
                                 "bad name; DROP TABLE x")


def test_materialize_endpoint(monkeypatch):
    import main
    import queries
    captured = {}

    def fake_ingest(engine, df, name, if_exists="replace"):
        captured["name"] = name
        captured["rows"] = len(df)
        return len(df)

    monkeypatch.setattr(queries, "ingest_dataframe", fake_ingest)
    monkeypatch.setattr(main.db, "get_engine_for_resource", lambda rid: object())
    monkeypatch.setattr(main.db.list_aurora_tables, "invalidate", lambda: None)
    monkeypatch.setattr(main.db.fetch_aurora_table, "invalidate", lambda: None)
    monkeypatch.setattr(main.lineage, "record", lambda *a, **k: None)

    with open(FIXTURE, "rb") as f:
        dataset_id = client.post("/api/datasets/upload",
            files={"file": ("samples.csv", f, "text/csv")}).json()["dataset_id"]
    resp = client.post(f"/api/datasets/{dataset_id}/materialize",
                       json={"resource_id": "db1", "table": "saved_cohort"})
    assert resp.status_code == 200
    assert resp.json() == {"table": "saved_cohort", "resource_id": "db1",
                           "rows": 100}
    assert captured == {"name": "saved_cohort", "rows": 100}


def test_upload_rejects_unsupported_file():
    resp = client.post("/api/datasets/upload", files={
        "file": ("reads.bam", b"BAM\x01binary", "application/octet-stream")})
    assert resp.status_code == 400
    assert "BAM" in resp.json()["detail"]


def test_views_aurora_roundtrip(monkeypatch, tmp_path):
    import views
    from sqlalchemy import create_engine
    import main
    # File-based SQLite stands in for Aurora: a shared DB across
    # connections (unlike :memory:, which is per-connection).
    engine = create_engine(f"sqlite:///{tmp_path/'views.db'}")
    monkeypatch.setattr(main.db, "get_engine_for_resource", lambda rid: engine)
    monkeypatch.setattr(views.db, "get_engine_for_resource", lambda rid: engine)
    monkeypatch.setattr(main.lineage, "record", lambda *a, **k: None)
    views._prepared.clear()

    ds = {"source": {"kind": "s3", "resource_id": "folder", "table": "x.csv"},
          "title": "x",
          "filters": [{"column": "tissue", "kind": "categorical",
                       "values": ["liver"]}],
          "charts": [{"kind": "bar", "x": "tissue"}]}
    save = client.post("/api/views", json={
        "kind": "aurora", "resource_id": "db1", "name": "liver cohort",
        "active": 0, "datasets": [ds, {**ds, "source":
            {"kind": "aurora", "resource_id": "db1", "table": "t2"},
            "title": "t2"}]})
    assert save.status_code == 200

    listed = client.get("/api/views?kind=aurora&resource_id=db1").json()
    assert [v["name"] for v in listed] == ["liver cohort"]

    got = client.get(
        "/api/views/one?kind=aurora&resource_id=db1&name=liver%20cohort").json()
    assert got["version"] == 2
    assert len(got["datasets"]) == 2
    assert got["datasets"][0]["filters"] == ds["filters"]
    assert got["datasets"][0]["charts"] == ds["charts"]
    assert got["datasets"][1]["source"]["table"] == "t2"

    client.delete("/api/views?kind=aurora&resource_id=db1&name=liver%20cohort")
    assert client.get("/api/views?kind=aurora&resource_id=db1").json() == []


def test_view_name_validation():
    import views
    import pytest as _pytest
    with _pytest.raises(ValueError):
        views._validate("bad/name.json; rm -rf")


def test_save_view_rejects_bad_backend():
    resp = client.post("/api/views", json={
        "kind": "bq", "resource_id": "d", "name": "v", "active": 0,
        "datasets": [{"source": {"kind": "bq", "resource_id": "d",
                                 "table": "t"}, "title": "t"}]})
    assert resp.status_code in (400, 502)


def test_save_view_rejects_empty():
    resp = client.post("/api/views", json={
        "kind": "aurora", "resource_id": "db1", "name": "v",
        "active": 0, "datasets": []})
    assert resp.status_code == 400


def test_join_datasets():
    import pandas as pd
    import datasets as ds_mod
    left = ds_mod.open_dataset(pd.DataFrame({
        "sample_id": ["a", "b", "c"], "tissue": ["liver", "lung", "skin"]}),
        "left")
    right = ds_mod.open_dataset(pd.DataFrame({
        "sample_id": ["a", "b"], "rin": [7.1, 8.2]}), "right")
    resp = client.post("/api/datasets/join", json={
        "left_id": left["dataset_id"], "right_id": right["dataset_id"],
        "left_on": "sample_id", "right_on": "sample_id", "how": "inner"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["rows"] == 2  # inner join keeps a, b
    cols = {c["name"] for c in body["columns"]}
    assert {"tissue", "rin"} <= cols

    # bad key -> 400
    bad = client.post("/api/datasets/join", json={
        "left_id": left["dataset_id"], "right_id": right["dataset_id"],
        "left_on": "nope", "right_on": "sample_id", "how": "inner"})
    assert bad.status_code == 400


def test_join_rejects_bad_how():
    import pandas as pd
    import datasets as ds_mod
    d = ds_mod.open_dataset(pd.DataFrame({"k": [1]}), "d")
    resp = client.post("/api/datasets/join", json={
        "left_id": d["dataset_id"], "right_id": d["dataset_id"],
        "left_on": "k", "right_on": "k", "how": "cross-sideways"})
    assert resp.status_code == 400


def test_numeric_chart_on_categorical_column_does_not_500():
    # A histogram/scatter chart spec pointed at a categorical column (e.g.
    # a chart type switched to one that needs numbers) must coerce to an
    # empty aggregate, never raise and 500 the whole query round-trip.
    import pandas as pd
    import datasets as ds_mod
    opened = ds_mod.open_dataset(pd.DataFrame({
        "tissue": ["liver", "lung", "skin", "liver"],
        "other": ["x", "y", "z", "x"]}), "cat")
    resp = client.post(f"/api/datasets/{opened['dataset_id']}/query", json={
        "filters": [],
        "charts": [
            {"kind": "histogram", "x": "tissue"},
            {"kind": "scatter", "x": "tissue", "y": "other"}],
        "page": 0})
    assert resp.status_code == 200
    charts = resp.json()["charts"]
    assert charts[0]["data"] == []  # histogram coerced to empty
    assert charts[1]["data"] == []  # scatter coerced to empty
