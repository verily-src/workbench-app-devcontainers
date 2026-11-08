from pathlib import Path
from uuid import uuid4

import duckdb
from fastapi.testclient import TestClient
from sqlalchemy import text

import database as db
import datasets
import disk_data
import extracts
import main


def test_reopened_derived_disk_source_keeps_all_rows_for_extract(engine, tmp_path, monkeypatch):
    parquet = tmp_path / "source.parquet"
    with duckdb.connect() as conn:
        conn.execute(f"COPY (SELECT i::BIGINT AS id FROM range(100005) AS r(i)) "
                     f"TO '{parquet}' (FORMAT PARQUET)")
    monkeypatch.setattr(disk_data, "_object_size", lambda *_: (
        parquet.stat().st_size, str(parquet), "us-east-1", False))
    monkeypatch.setattr(disk_data.duck, "_connect", lambda *a, **k: duckdb.connect())
    monkeypatch.setattr(db, "get_engine_for_resource", lambda _: engine)
    client = TestClient(main.app)
    opened = client.post("/api/datasets/open", json={
        "kind": "s3", "resource_id": "fixture", "table": "source.parquet"})
    assert opened.status_code == 200, opened.text
    original = opened.json()["dataset_id"]
    reopened = None
    table = "derived_" + uuid4().hex[:12]
    path = None
    try:
        derived = client.post(f"/api/datasets/{original}/derive", json={
            "op": "formula", "name": "double_id", "left": "id", "operator": "*", "right": "2"})
        assert derived.status_code == 200, derived.text
        assert derived.json()["sampled"] is False
        restored = main._open_source(derived.json()["source_ref"])
        reopened = restored["dataset_id"]
        source = datasets.get(reopened)
        path = source["disk_source"]["path"]
        assert Path(path).exists()
        response = client.post(f"/api/datasets/{reopened}/query", json={
            "page": 10000, "page_size": 10, "filters": [], "charts": []})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["total"] == 100005
        assert result["rows"]["data"][0][result["rows"]["columns"].index("double_id")] == 200000
        info = extracts.write(source, "fixture", table, "derived", derived.json()["source_ref"])
        assert info["rows"] == 100005
        with engine.connect() as conn:
            assert conn.execute(text(f'SELECT count(*) FROM public."{table}"')).scalar_one() == 100005
    finally:
        datasets.close_dataset(original)
        if reopened:
            datasets.close_dataset(reopened)
        extracts.forget("fixture", table)
        with engine.begin() as conn:
            conn.execute(text(f'DROP TABLE IF EXISTS public."{table}"'))
    assert path is not None and not Path(path).exists()
