import json
from pathlib import Path

import duckdb
import pandas as pd
import pytest
from fastapi.testclient import TestClient

import datasets
import disk_data
import column_settings
import compare
import agent
import db
import main


@pytest.fixture
def client(engine, monkeypatch):
    monkeypatch.setattr(db, "list_aurora_resources", lambda: [{"id": "omopdb"}])
    monkeypatch.setattr(db, "get_engine_for_resource", lambda resource_id: engine)
    return TestClient(main.app)


def test_s3_sources_join_and_page_past_preview(tmp_path, monkeypatch, client):
    left_file = tmp_path / "left.parquet"
    right_file = tmp_path / "right.parquet"
    for path, value in ((left_file, "left_value"), (right_file, "right_value")):
        con = duckdb.connect()
        con.execute(
            f"COPY (SELECT i::BIGINT AS join_id, i::BIGINT AS {value}, "
            "CASE WHEN i % 2 = 0 THEN 'even' ELSE 'odd' END AS group_name "
            f"FROM range(100005) AS r(i)) TO '{path}' (FORMAT PARQUET)")
        con.close()

    files = {"left.parquet": left_file, "right.parquet": right_file}
    monkeypatch.setattr(disk_data, "_object_size",
                        lambda rid, name: (disk_data.LARGE_OPERATION_BYTES
                                           if name == "left.parquet"
                                           else files[name].stat().st_size,
                                           str(files[name]), "us-east-1", False))
    monkeypatch.setattr(disk_data.duck, "_connect",
                        lambda profile, region=None, app_credentials=False: duckdb.connect())

    opened, disk_paths = [], []
    try:
        source_ids = []
        for name in files:
            response = client.post("/api/datasets/open", json={
                "kind": "s3", "resource_id": "fixture", "table": name})
            assert response.status_code == 200, response.text
            body = response.json()
            opened.append(body["dataset_id"])
            disk_paths.append(datasets.get(body["dataset_id"])["disk_source"]["path"])
            source_ids.append(body["dataset_id"])
            assert body["sampled"] is False
            assert body["rows"] == 100_000
            assert body["large_warning"] is (name == "left.parquet")

        joined = client.post("/api/datasets/join", json={
            "base_id": source_ids[0], "steps": [{
                "right_id": source_ids[1], "how": "inner", "alias": "right",
                "columns": ["right_value"],
                "conditions": [{"left": "join_id", "right": "join_id"}],
            }]})
        assert joined.status_code == 200, joined.text
        body = joined.json()
        opened.append(body["dataset_id"])
        disk_paths.append(datasets.get(body["dataset_id"])["disk_source"]["path"])
        assert body["join"]["rows"] == 100_005
        assert body["join"]["large_warning"] is True
        assert body["sampled"] is False

        page = client.post(f"/api/datasets/{body['dataset_id']}/query", json={
            "page": 10_000, "page_size": 10, "filters": [],
            "charts": [{"kind": "bar", "x": "group_name"}],
            "entity_column": "join_id"})
        assert page.status_code == 200, page.text
        result = page.json()
        assert result["total"] == 100_005
        assert result["entity"] == {"column": "join_id", "total": 100_005,
                                    "filtered": 100_005}
        assert result["rows"]["data"][0][0] == 100_000
        chart_counts = {row["category"]: row["all"]
                        for row in result["charts"][0]["data"]}
        assert chart_counts == {"even": 50_003, "odd": 50_002}

        export = client.post(f"/api/datasets/{body['dataset_id']}/export", json={
            "page": 0, "page_size": 50, "filters": [], "charts": []})
        assert export.status_code == 200, export.text
        assert len(export.text.splitlines()) == 100_001

        derived = client.post(f"/api/datasets/{body['dataset_id']}/derive", json={
            "op": "formula", "name": "double_id", "left": "join_id",
            "operator": "*", "right": "2"})
        assert derived.status_code == 200, derived.text
        assert derived.json()["sampled"] is False
        derived_page = client.post(f"/api/datasets/{body['dataset_id']}/query", json={
            "page": 10_000, "page_size": 10, "filters": [], "charts": []})
        assert derived_page.status_code == 200, derived_page.text
        columns = derived_page.json()["rows"]["columns"]
        assert derived_page.json()["rows"]["data"][0][columns.index("double_id")] == 200_000.0

        current = datasets.get(body["dataset_id"])
        profiles = column_settings.profiles(current)
        group_profile = next(item for item in profiles
                             if item["name"] == "group_name")
        assert set(group_profile["values"]) == {"even", "odd"}
        id_profile = next(item for item in profiles if item["name"] == "join_id")
        assert id_profile["min"] == 0 and id_profile["max"] == 100_004
        compared = compare.compare(body["dataset_id"], [
            {"column": "join_id", "kind": "range", "min": 0, "max": 49_999}], [
            {"column": "join_id", "kind": "range", "min": 50_000, "max": 100_004}])
        assert compared["a_n"] == 50_000 and compared["b_n"] == 50_005
        assert any(row["column"] == "group_name" for row in compared["results"])

        ui, actions = {"filters": [], "charts": []}, []
        tools = {tool.__name__: tool for tool in agent.build_tools(
            current["df"], profiles, ui, actions,
            disk_source=current["disk_source"])}
        filters = json.dumps([{"column": "join_id", "kind": "range",
                               "min": 0, "max": 49_999}])
        assistant_query = json.loads(tools["run_query"](filters))
        assert assistant_query["matching_rows"] == 50_000
        assistant_aggregate = json.loads(tools["aggregate"](
            "count", "", "group_name", filters))
        assert assistant_aggregate["result"] == {"even": 25_000, "odd": 25_000}
        assistant_filter = json.loads(tools["set_filters"](filters, "first half"))
        assert assistant_filter["matching_rows"] == 50_000

    finally:
        for dataset_id in opened:
            datasets.close_dataset(dataset_id)
    assert all(not Path(path).exists() and not Path(path + ".tmp").exists()
               for path in disk_paths)


def test_operation_guard_rejects_over_one_tb():
    assert disk_data._budget(disk_data.MAX_OPERATION_BYTES) == disk_data.MAX_OPERATION_BYTES
    try:
        disk_data._budget(disk_data.MAX_OPERATION_BYTES // 2 + 1,
                          disk_data.MAX_OPERATION_BYTES // 2 + 1)
    except disk_data.OperationTooLarge as exc:
        assert "1 TB" in str(exc)
    else:
        raise AssertionError("over-limit operation was accepted")


def test_join_materialization_checks_current_high_fanout_batch(monkeypatch):
    cap = 1_000_000
    monkeypatch.setattr(disk_data, "MAX_OPERATION_BYTES", cap)
    left = {"df": pd.DataFrame({
        "key": [1] * 100, "payload": ["x" * 1000 for _ in range(100)]})}
    right = {"df": pd.DataFrame({"key": [1] * 100})}
    plan = {"base": left, "steps": [{
        "no": 1, "ds": right, "how": "inner", "left": ["key", "payload"],
        "conds": [{"left": "key", "right": "key", "op": "=", "cast": False}],
        "cols": [], "notes": [],
    }]}
    created = []
    new_path = disk_data._new_path

    def record_path():
        path = new_path()
        created.append(path)
        return path

    monkeypatch.setattr(disk_data, "_new_path", record_path)
    monkeypatch.setattr(disk_data, "_duckdb_estimate", lambda *_args: 1)
    with pytest.raises(disk_data.OperationTooLarge):
        disk_data.run_join(plan)
    assert created and all(not Path(path).exists() for path in created)


def test_s3_open_rejects_over_budget_from_head_before_read(monkeypatch, client):
    calls = []

    class S3:
        def head_object(self, **kwargs):
            calls.append("head")
            return {"ContentLength": disk_data.MAX_OPERATION_BYTES // 2 + 1}

        def get_object(self, **kwargs):
            calls.append("get")
            raise AssertionError("source read started before the budget check")

    monkeypatch.setattr(
        disk_data, "_s3_client",
        lambda resource_id, filename:
            (S3(), "fixture", filename, f"s3://fixture/{filename}", "us-east-1", False))
    response = client.post("/api/datasets/open", json={
        "kind": "s3", "resource_id": "fixture", "table": "huge.parquet"})
    assert response.status_code == 413, response.text
    assert calls == ["head"]


def test_failed_disk_source_registration_removes_database_and_spill(monkeypatch):
    path = disk_data._new_path()
    con = duckdb.connect(path)
    con.execute("CREATE TABLE data AS SELECT 1 AS value")
    con.close()
    source = {"path": path, "table": "data", "columns": ["value"],
              "rows": 1, "scan_bytes": Path(path).stat().st_size}

    def fail_profile(*_args):
        raise disk_data.OperationTooLarge("profile scan exceeded the operation budget")

    monkeypatch.setattr(disk_data, "profile_columns", fail_profile)
    with pytest.raises(disk_data.OperationTooLarge):
        datasets.open_dataset(pd.DataFrame({"value": [1]}), "fixture",
                              disk_source=source)
    assert not Path(path).exists()
    assert not Path(path + ".tmp").exists()


def test_materialization_limits_reject_busy_and_low_disk_then_recover(tmp_path, monkeypatch):
    import threading
    from types import SimpleNamespace

    path = tmp_path / "source.parquet"
    con = duckdb.connect()
    con.execute(f"COPY (SELECT 7 AS id) TO '{path}' (FORMAT PARQUET)")
    con.close()
    monkeypatch.setattr(disk_data, "_object_size",
                        lambda *_: (path.stat().st_size, str(path), "us-east-1", False))
    monkeypatch.setattr(disk_data.duck, "_connect", lambda *_args, **_kwargs: duckdb.connect())
    slots = threading.BoundedSemaphore(2)
    monkeypatch.setattr(disk_data, "_MATERIALIZATIONS", slots)
    slots.acquire()
    slots.acquire()
    with pytest.raises(disk_data.OperationTooLarge, match="already writing"):
        disk_data.open_s3({"resource_id": "test", "table": "source.parquet"})
    slots.release()
    slots.release()
    real_usage = disk_data.shutil.disk_usage
    monkeypatch.setattr(disk_data.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    with pytest.raises(disk_data.OperationTooLarge, match="less than 1 GB"):
        disk_data.open_s3({"resource_id": "test", "table": "source.parquet"})
    monkeypatch.setattr(disk_data.shutil, "disk_usage", real_usage)
    frame, source = disk_data.open_s3({"resource_id": "test", "table": "source.parquet"})
    try:
        assert source["rows"] == 1
        assert frame["id"].tolist() == [7]
    finally:
        disk_data.remove(source)
