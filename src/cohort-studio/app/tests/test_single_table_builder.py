import io
import uuid
import duckdb
import pandas as pd

import datasets
import extracts
from sqlalchemy import text

from tests.test_join_filters import tables, _open  # noqa: F401


def test_single_database_table_filters_fields_and_reopens(client, engine, tables):
    base = _open(client, tables["people"])
    body = {"base_id": base, "steps": [],
            "base_filters": [{"column": "status", "op": "=", "value": "case"}],
            "output": {"exclude": ["status"], "rename": {"person_id": "patient"}}}
    checked = client.post("/api/datasets/join/validate", json=body)
    assert checked.status_code == 200 and checked.json()["ok"], checked.text
    preview = client.post("/api/datasets/join/preview", json=body)
    assert preview.status_code == 200, preview.text
    assert preview.json()["columns"] == ["patient"]
    joined = client.post("/api/datasets/join", json=body)
    assert joined.status_code == 200, joined.text
    result = joined.json()
    assert result["source_ref"]["steps"] == []
    assert [c["name"] for c in result["columns"]] == ["patient"]
    query = client.post(f"/api/datasets/{result['dataset_id']}/query", json={"filters": [], "charts": []})
    assert query.status_code == 200, query.text
    assert query.json()["total"] == 2
    assert {row[0] for row in query.json()["rows"]["data"]} == {1, 2}
    reopened = client.post("/api/datasets/open", json={"source_ref": result["source_ref"]})
    assert reopened.status_code == 200, reopened.text
    assert [c["name"] for c in reopened.json()["columns"]] == ["patient"]
    query = client.post(f"/api/datasets/{reopened.json()['dataset_id']}/query", json={"filters": [], "charts": []})
    assert query.status_code == 200 and query.json()["total"] == 2
    destination = f"single_extract_{uuid.uuid4().hex[:8]}"
    try:
        info = extracts.write(datasets.get(result["dataset_id"]), "omopdb", destination,
                              "Filtered people", result["source_ref"])
        assert info["rows"] == 2 and info["refreshable"] is True
        with engine.connect() as conn:
            assert conn.execute(text(f'SELECT count(*) FROM public."{destination}"')).scalar_one() == 2
        assert extracts.info("omopdb", destination)["recipe"]["steps"] == []
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP TABLE IF EXISTS public."{destination}"'))


def test_single_uploaded_table_filters_and_projects(client):
    upload = client.post("/api/datasets/upload", files={"file": ("test.csv", io.BytesIO(b"id,status\n1,case\n2,control\n"), "text/csv")})
    assert upload.status_code == 200, upload.text
    body = {"base_id": upload.json()["dataset_id"], "steps": [],
            "base_filters": [{"column": "status", "op": "=", "value": "case"}],
            "output": {"exclude": ["status"], "rename": {"id": "patient"}}}
    response = client.post("/api/datasets/join", json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["rows"] == 1
    query = client.post(f"/api/datasets/{result['dataset_id']}/query", json={"filters": [], "charts": []})
    assert query.status_code == 200, query.text
    assert query.json()["rows"]["columns"] == ["patient"]
    assert query.json()["rows"]["data"] == [[1]]


def test_single_disk_source_reads_all_rows_and_projects(client, tmp_path):
    path = str(tmp_path / "single.duckdb")
    conn = duckdb.connect(path)
    conn.execute("CREATE TABLE data AS SELECT range AS id, range % 2 AS grp FROM range(150000)")
    conn.close()
    opened = datasets.open_dataset(pd.DataFrame({"id": [0, 1], "grp": [0, 1]}), "disk",
        disk_source={"path": path, "table": "data", "columns": ["id", "grp"], "rows": 150000})
    body = {"base_id": opened["dataset_id"], "steps": [],
            "base_filters": [{"column": "grp", "op": "=", "value": 1}],
            "output": {"exclude": ["grp"], "rename": {"id": "patient"}}}
    response = client.post("/api/datasets/join", json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["join"]["total_rows"] == 75000
    assert result["join"]["truncated"] is False
    query = client.post(f"/api/datasets/{result['dataset_id']}/query", json={"filters": [], "charts": []})
    assert query.status_code == 200, query.text
    assert query.json()["total"] == 75000
    assert query.json()["rows"]["columns"] == ["patient"]


def test_single_live_source_over_preview_cap_is_not_marked_truncated(client, engine, tables):
    name = tables["people"]
    with engine.begin() as conn:
        conn.exec_driver_sql(f'TRUNCATE TABLE public."{name}"')
        conn.exec_driver_sql(f'INSERT INTO public."{name}" SELECT n, \'case\' FROM generate_series(1, 110000) AS n')
    base = _open(client, name)
    result = client.post("/api/datasets/join", json={"base_id": base, "steps": []})
    assert result.status_code == 200, result.text
    assert result.json()["join"]["total_rows"] == 110000
    assert result.json()["join"]["truncated"] is False
    query = client.post(f"/api/datasets/{result.json()['dataset_id']}/query", json={"filters": [], "charts": []})
    assert query.status_code == 200 and query.json()["total"] == 110000
