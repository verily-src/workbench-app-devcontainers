from pathlib import Path
import uuid

import duckdb
import pandas as pd
import pytest
from fastapi.testclient import TestClient

import main
import datasets
import disk_data


def test_chained_join_retains_incomplete_source_warning(client):
    opened = []
    try:
        for name, capped in [("sample", True), ("first", False), ("second", False)]:
            dataset = datasets.open_dataset(pd.DataFrame({"person_id": [1, 2]}), name, capped=capped)
            opened.append(dataset["dataset_id"])

        def join(left, right, alias):
            response = client.post("/api/datasets/join", json={
                "base_id": left, "allow_loaded": True, "steps": [{
                    "right_id": right, "how": "inner", "alias": alias,
                    "conditions": [{"left": "person_id", "op": "=", "right": "person_id"}],
                }],
            })
            assert response.status_code == 200, response.text
            result = response.json()
            opened.append(result["dataset_id"])
            return result

        first = join(opened[0], opened[1], "first")
        assert first["sampled"] is True
        assert first["join"]["complete_source"] is False
        assert datasets.get(first["dataset_id"])["disk_source"]

        derived = client.post(f"/api/datasets/{first['dataset_id']}/derive", json={
            "op": "formula", "name": "next_id", "left": "person_id", "operator": "+", "right": "1",
        })
        assert derived.status_code == 200, derived.text
        assert derived.json()["sampled"] is True

        second = join(first["dataset_id"], opened[2], "second")
        assert second["sampled"] is True
        assert second["join"]["complete_source"] is False
        assert first["source"] in second["join"]["capped_inputs"]
        query = client.post(f"/api/datasets/{second['dataset_id']}/query", json={})
        assert query.status_code == 200, query.text
        assert query.json()["sampled"] is True
    finally:
        for dataset_id in reversed(opened):
            datasets.close_dataset(dataset_id)


@pytest.fixture
def client(engine, monkeypatch):
    monkeypatch.setattr(main.db, "list_aurora_resources", lambda: [{"id": "omopdb"}])
    monkeypatch.setattr(main.db, "get_engine_for_resource", lambda _rid: engine)
    return TestClient(main.app)


def test_aurora_and_s3_join_uses_duckdb_and_requires_consent(client, engine,
                                                             monkeypatch, tmp_path):
    table = f"studio_join_s3_{uuid.uuid4().hex[:8]}"
    parquet = tmp_path / "samples.parquet"
    con = duckdb.connect()
    con.execute("COPY (SELECT * FROM (VALUES (1::BIGINT, 'first'), "
                "(2::BIGINT, 'second')) AS t(person_id, variant)) "
                f"TO '{parquet}' (FORMAT PARQUET)")
    con.close()
    with engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE TABLE public."{table}" (person_id BIGINT, status TEXT)')
        conn.exec_driver_sql(f'INSERT INTO public."{table}" VALUES (1, \'case\'), (2, \'control\')')

    def open_s3(_ref):
        path = disk_data._new_path()
        con = duckdb.connect(path)
        con.execute(f"CREATE TABLE data AS SELECT * FROM read_parquet('{parquet}')")
        frame = con.execute("SELECT * FROM data LIMIT 100000").df()
        con.close()
        size = Path(path).stat().st_size
        return frame, {"path": path, "table": "data", "columns": list(frame.columns),
                       "rows": len(frame), "estimated_bytes": size, "scan_bytes": size,
                       "large_warning": False}

    monkeypatch.setattr(disk_data, "open_s3", open_s3)
    opened, staged = [], []
    try:
        aurora = client.post("/api/datasets/open", json={"source_ref": {
            "kind": "aurora", "resource_id": "omopdb", "schema": "public", "table": table,
        }})
        s3 = client.post("/api/datasets/open", json={"source_ref": {
            "kind": "s3", "resource_id": "fixture", "uuid": "fixture-uuid",
            "table": "samples.parquet",
        }})
        assert aurora.status_code == s3.status_code == 200
        opened.extend([aurora.json()["dataset_id"], s3.json()["dataset_id"]])
        staged.append(datasets.get(opened[1])["disk_source"]["path"])
        request = {"base_id": opened[0], "steps": [{
            "right_id": opened[1], "how": "inner", "alias": "samples",
            "columns": None,
            "conditions": [{"left": "person_id", "op": "=", "right": "person_id"}],
        }]}
        denied = client.post("/api/datasets/join", json=request)
        assert denied.status_code == 400
        assert "explicit approval" in denied.text
        response = client.post("/api/datasets/join", json={**request, "allow_loaded": True})
        assert response.status_code == 200, response.text
        result = response.json()
        opened.append(result["dataset_id"])
        staged.append(datasets.get(result["dataset_id"])["disk_source"]["path"])
        assert result["join"]["engine"] == "duckdb"
        assert result["join"]["complete_source"] is True
        assert result["join"]["rows"] == 2
        query = client.post(f"/api/datasets/{result['dataset_id']}/query", json={
            "page": 0, "page_size": 20, "filters": [], "charts": [],
        })
        assert query.status_code == 200, query.text
        assert query.json()["sampled"] is False
        assert query.json()["rows"]["data"] == [
            [1, "case", 1, "first"], [2, "control", 2, "second"],
        ]
    finally:
        for dataset_id in opened:
            datasets.close_dataset(dataset_id)
        for path in staged:
            disk_data.remove({"path": path})
        with engine.begin() as conn:
            conn.exec_driver_sql(f'DROP TABLE IF EXISTS public."{table}"')
