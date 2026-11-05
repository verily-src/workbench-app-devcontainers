"""Group summary "Open as table": the full summary as a reproducible dataset tab."""
import duckdb
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import datasets
import disk_data
import group_summary
import main
from source_models import source_dict

TABLE = "group_summary_open_test"
EXPECTED = [["A", 2, 2, 4.0, 2.0, 1.0, 3.0], ["B", 2, 0, None, None, None, None], [None, 1, 1, 4.0, 4.0, 4.0, 4.0]]
COLUMNS = ["group", "Rows", "Numeric values", "Sum", "Mean", "Minimum", "Maximum"]
SPEC = {"group_by": ["group"], "measure": "value"}


@pytest.fixture
def frame():
    return pd.DataFrame({"group": ["A", "A", "B", None, "B"], "part": [1, 1, 2, 1, 2],
                         "value": ["1", "3", "bad", "4", None]})


@pytest.fixture
def api():
    return TestClient(main.app)


def _rows(client, dataset_id, **body):
    response = client.post(f"/api/datasets/{dataset_id}/query", json={
        "filters": [], "charts": [], "page": 0, "page_size": 100, **body})
    assert response.status_code == 200, response.text
    result = response.json()
    columns = result["rows"]["columns"]
    data = [dict(zip(columns, row)) for row in result["rows"]["data"]]
    return result, [[row[name] for name in COLUMNS if name in row] for row in data]


def _normalized(rows):
    def clean(value):
        if value is None or (isinstance(value, float) and value != value):
            return None
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else value
    return sorted(([clean(v) for v in row] for row in rows), key=lambda row: (row[0] is None, str(row[0])))


def _expected():
    return _normalized(EXPECTED)


def _duckdb_dataset(frame, tmp_path):
    path = str(tmp_path / "data.duckdb")
    con = duckdb.connect(path)
    con.register("frame", frame)
    con.execute("CREATE TABLE data AS SELECT * FROM frame")
    con.close()
    return datasets.open_dataset(frame, "file", disk_source={
        "path": path, "table": "data", "columns": list(frame.columns), "rows": len(frame)})


def _materialize(client, dataset_id, **body):
    return client.post(f"/api/datasets/{dataset_id}/summary/materialize", json={**SPEC, **body})


def test_loaded_dataset_opens_every_group_respecting_filters(api, frame):
    opened = datasets.open_dataset(frame, "loaded")
    ids = [opened["dataset_id"]]
    try:
        response = _materialize(api, opened["dataset_id"])
        assert response.status_code == 200, response.text
        body = response.json()
        ids.append(body["dataset_id"])
        assert body["source"] == "loaded · Group summary (group)"
        assert body["rows"] == 3 and [c["name"] for c in body["columns"]] == COLUMNS
        assert body["summary"] == {"total_groups": 3, "input_rows": 5, "scope": "loaded",
                                   "sampled": False, "staged": False}
        # An uploaded base has no reproducible recipe, like the upload itself.
        assert body.get("source_ref") is None
        _, rows = _rows(api, body["dataset_id"])
        assert _normalized(rows) == _expected()

        filtered = _materialize(api, opened["dataset_id"], filters=[
            {"column": "group", "kind": "categorical", "values": ["A"]}]).json()
        ids.append(filtered["dataset_id"])
        assert filtered["rows"] == 1 and filtered["summary"]["input_rows"] == 2
    finally:
        for dataset_id in ids:
            datasets.close_dataset(dataset_id)


@pytest.mark.parametrize("row_cap", [100_000, 1])
def test_duckdb_dataset_in_memory_and_staged(api, frame, tmp_path, monkeypatch, row_cap):
    monkeypatch.setattr(group_summary.queries, "ROW_CAP", row_cap)
    opened = _duckdb_dataset(frame, tmp_path)
    ids = [opened["dataset_id"]]
    try:
        response = _materialize(api, opened["dataset_id"])
        assert response.status_code == 200, response.text
        body = response.json()
        ids.append(body["dataset_id"])
        staged = row_cap == 1
        assert body["summary"]["staged"] is staged and body["summary"]["total_groups"] == 3
        assert [c["name"] for c in body["columns"]] == COLUMNS
        ds = datasets.get(body["dataset_id"])
        assert bool(ds.get("disk_source")) is staged
        # The table, filters and the panel itself work on the new tab.
        result, rows = _rows(api, body["dataset_id"])
        assert result["total"] == 3 and _normalized(rows) == _expected()
        filtered, _ = _rows(api, body["dataset_id"], filters=[
            {"column": "Rows", "kind": "range", "min": 2, "max": 2}])
        assert filtered["filtered"] == 2
        again = group_summary.summarize(body["dataset_id"], {"group_by": ["Rows"]})
        assert again["total_groups"] == 2
    finally:
        for dataset_id in ids:
            datasets.close_dataset(dataset_id)


def test_guards_and_validation(api, frame, tmp_path, monkeypatch):
    opened = _duckdb_dataset(frame, tmp_path)
    try:
        path = f"/api/datasets/{opened['dataset_id']}/summary/materialize"
        assert api.post(path, json={"group_by": ["unknown"]}).status_code == 400
        assert api.post(path, json={"group_by": ["group", "group"]}).status_code == 422
        assert api.post(path, json={"group_by": ["group"], "page": 1}).status_code == 422
        assert api.post(path, json={"group_by": ["group"], "filters": [
            {"column": "nope", "kind": "categorical", "values": ["x"]}]}).status_code == 400
        assert api.post("/api/datasets/unknown/summary/materialize",
                        json={"group_by": ["group"]}).status_code == 404
        monkeypatch.setattr(disk_data, "MAX_OPERATION_BYTES", 1)
        too_large = api.post(path, json={"group_by": ["group"]})
        assert too_large.status_code == 413
        assert "1 TB" in too_large.json()["detail"]
    finally:
        datasets.close_dataset(opened["dataset_id"])


def test_source_ref_validation():
    base = {"kind": "aurora", "resource_id": "db", "table": "t"}
    ref = source_dict({"kind": "group_summary", "base": base, "spec": {"group_by": ["a"], "measure": None},
                       "filters": [{"column": "a", "kind": "categorical", "values": ["x"]}]})
    assert ref == {"kind": "group_summary", "base": base, "spec": {"group_by": ["a"]},
                   "filters": [{"column": "a", "kind": "categorical", "values": ["x"]}]}
    for bad in ({"group_by": []}, {"group_by": ["a", "a"]}, {"group_by": ["a"], "page": 1}):
        with pytest.raises(ValueError):
            source_dict({"kind": "group_summary", "base": base, "spec": bad})


@pytest.fixture
def pg_table(engine, client):
    with engine.begin() as con:
        con.execute(text(f'CREATE TABLE public.{TABLE} ("group" text, part bigint, value text)'))
        con.execute(text(f"INSERT INTO public.{TABLE} VALUES ('A',1,'1'),('A',1,'3'),('B',2,'bad'),(NULL,1,'4'),('B',2,NULL)"))
    yield {"kind": "aurora", "resource_id": "omopdb", "schema": "public", "table": TABLE}
    with engine.begin() as con:
        con.execute(text(f"DROP TABLE IF EXISTS public.{TABLE}"))


@pytest.mark.parametrize("row_cap", [100_000, 1])
def test_database_summary_reopens_from_source_ref(client, pg_table, monkeypatch, row_cap):
    monkeypatch.setattr(group_summary.queries, "ROW_CAP", row_cap)
    base = main._open_source(pg_table)
    ids = [base["dataset_id"]]
    try:
        filters = [{"column": "part", "kind": "range", "min": 1, "max": 1}]
        response = _materialize(client, base["dataset_id"], filters=filters)
        assert response.status_code == 200, response.text
        body = response.json()
        ids.append(body["dataset_id"])
        assert body["summary"] == {"total_groups": 2, "input_rows": 3, "scope": "database",
                                   "sampled": False, "staged": row_cap == 1}
        assert [c["name"] for c in body["columns"]] == COLUMNS
        ref = body["source_ref"]
        assert ref["kind"] == "group_summary" and ref["spec"] == SPEC
        assert ref["base"]["table"] == TABLE and ref["filters"] == filters
        _, rows = _rows(client, body["dataset_id"])
        expected = _normalized([EXPECTED[0], EXPECTED[2]])
        assert _normalized(rows) == expected

        reopened = client.post("/api/datasets/open", json={"source_ref": ref})
        assert reopened.status_code == 200, reopened.text
        ids.append(reopened.json()["dataset_id"])
        assert reopened.json()["source"] == body["source"]
        assert reopened.json()["source_ref"] == ref
        _, again = _rows(client, reopened.json()["dataset_id"])
        assert _normalized(again) == expected
    finally:
        for dataset_id in ids:
            datasets.close_dataset(dataset_id)


def test_saved_view_roundtrip_keeps_group_summary_and_summary_tab(client, pg_table):
    base = main._open_source(pg_table)
    ids = [base["dataset_id"]]
    try:
        body = _materialize(client, base["dataset_id"]).json()
        ids.append(body["dataset_id"])
        recipe = {"group_by": ["group", "part"], "measure": "value"}
        saved = client.post("/api/views", json={
            "kind": "aurora", "resource_id": "omopdb", "name": "summary view", "active": 1,
            "datasets": [
                {"source": base["source_ref"], "title": "base", "group_summary": recipe,
                 "filters": [{"column": "group", "kind": "categorical", "values": ["A"]}]},
                {"source": body["source_ref"], "title": body["source"],
                 "group_summary": {"group_by": ["Rows"], "measure": None}},
            ]})
        assert saved.status_code == 200, saved.text
        view = client.get("/api/views/one", params={
            "kind": "aurora", "resource_id": "omopdb", "name": "summary view"})
        assert view.status_code == 200, view.text
        tabs = view.json()["datasets"]
        assert tabs[0]["group_summary"] == recipe
        assert tabs[1]["group_summary"] == {"group_by": ["Rows"], "measure": None}
        assert tabs[1]["source"] == body["source_ref"]
        reopened = client.post("/api/datasets/open", json={"source_ref": tabs[1]["source"]})
        assert reopened.status_code == 200, reopened.text
        ids.append(reopened.json()["dataset_id"])
        assert reopened.json()["rows"] == 3
        # The saved panel recipe reruns against the reopened base.
        base_again = client.post("/api/datasets/open", json={"source_ref": tabs[0]["source"]}).json()
        ids.append(base_again["dataset_id"])
        rerun = client.post(f"/api/datasets/{base_again['dataset_id']}/summary",
                            json={**tabs[0]["group_summary"], "filters": tabs[0]["filters"]})
        assert rerun.status_code == 200, rerun.text
        assert rerun.json()["total_groups"] == 1 and rerun.json()["input_rows"] == 2
        # Invalid panel recipes are rejected at save time.
        bad = client.post("/api/views", json={
            "kind": "aurora", "resource_id": "omopdb", "name": "bad view",
            "datasets": [{"source": base["source_ref"], "group_summary": {"group_by": ["a", "a"]}}]})
        assert bad.status_code == 422
        client.delete("/api/views", params={"kind": "aurora", "resource_id": "omopdb", "name": "summary view"})
    finally:
        for dataset_id in ids:
            datasets.close_dataset(dataset_id)
