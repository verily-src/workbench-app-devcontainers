import csv
import io
import time
import uuid

import pandas as pd
import pytest
from sqlalchemy import text

import datasets
import db
import export_jobs


@pytest.fixture
def export_source(engine, monkeypatch):
    monkeypatch.setattr(db, "get_engine_for_resource", lambda _rid: engine)
    name = "export_" + uuid.uuid4().hex[:10]
    with engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE TABLE public."{name}" AS '
                             "SELECT n AS person_id, 'old'::text AS label "
                             "FROM generate_series(1, 120005) n")
    source = {"resource_id": "export-test", "sql": f'SELECT * FROM public."{name}"',
              "columns": {"person_id": "person_id", "label": "label"}}
    opened = datasets.open_dataset(pd.DataFrame({"person_id": [1], "label": ["old"]}),
                                   name, live_source=source, capped=True)
    yield opened["dataset_id"], name
    export_jobs.shutdown()
    with engine.begin() as conn:
        conn.exec_driver_sql(f'DROP TABLE public."{name}"')


def wait_terminal(client, job_id):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        response = client.get(f"/api/exports/{job_id}")
        assert response.status_code == 200, response.text
        body = response.json()
        if body["status"] in ("complete", "failed", "cancelled"):
            return body
        time.sleep(0.03)
    pytest.fail("Export did not finish within 15 seconds")


def test_stream_export_all_rows_beyond_preview_with_fresh_data(client, engine, export_source):
    dataset_id, table = export_source
    queried = client.post(f"/api/datasets/{dataset_id}/query", json={})
    assert queried.status_code == 200, queried.text
    label = 'fresh\tvalue\n"quoted" Ω'
    with engine.begin() as conn:
        conn.execute(text(f'UPDATE public."{table}" SET label = :label'), {"label": label})
    started = client.post(f"/api/datasets/{dataset_id}/exports", json={"filters": []})
    assert started.status_code == 202, started.text
    job_id = started.json()["id"]
    result = wait_terminal(client, job_id)
    assert result["status"] == "complete", result
    assert result["rows"] == 120005 and result["bytes"] > 0
    download = client.get(f"/api/exports/{job_id}/download")
    assert download.status_code == 200
    rows = list(csv.reader(io.StringIO(download.text), delimiter="\t"))
    assert rows[0] == ["person_id", "label"]
    assert len(rows) == 120006
    assert {int(r[0]) for r in rows[1:]} == set(range(1, 120006))
    assert all(row[1] == label for row in rows[1:])
    assert client.delete(f"/api/exports/{job_id}").status_code == 200
    assert client.get(f"/api/exports/{job_id}/download").status_code == 404


def test_export_bound_params_filters_and_failed_files_are_not_downloadable(
        client, export_source, monkeypatch):
    dataset_id, _ = export_source
    source = datasets.get(dataset_id)["live_source"]
    source["sql"] = "SELECT n AS person_id, :value AS label FROM generate_series(1, 120005) n"
    source["params"] = {"value": "literal :not_a_bind ' %"}
    filters = [{"column": "person_id", "kind": "range", "min": 120004, "max": 120005}]
    started = client.post(f"/api/datasets/{dataset_id}/exports", json={"filters": filters})
    job_id = started.json()["id"]
    assert wait_terminal(client, job_id)["rows"] == 2
    data = client.get(f"/api/exports/{job_id}/download").text
    assert "literal :not_a_bind ' %" in data
    monkeypatch.setattr(export_jobs, "MAX_JOB_BYTES", 32)
    failed = client.post(f"/api/datasets/{dataset_id}/exports", json={"filters": []}).json()
    outcome = wait_terminal(client, failed["id"])
    assert outcome["status"] == "failed"
    assert outcome["bytes"] == 0
    assert client.get(f"/api/exports/{failed['id']}/download").status_code == 409
    assert not (export_jobs._ROOT / (failed["id"] + ".part")).exists()


def test_export_cancellation_interrupts_aurora_query(client, engine, export_source):
    dataset_id, _ = export_source
    datasets.get(dataset_id)["live_source"] = {
        "resource_id": "export-test", "sql": "SELECT 1 AS person_id, pg_sleep(60)::text AS label",
        "columns": {"person_id": "person_id", "label": "label"}}
    job_id = client.post(f"/api/datasets/{dataset_id}/exports", json={}).json()["id"]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with engine.connect() as conn:
            running = conn.execute(text("SELECT EXISTS(SELECT 1 FROM pg_stat_activity "
                                        "WHERE wait_event='PgSleep')")).scalar()
        if running:
            break
        time.sleep(0.03)
    assert running, client.get(f"/api/exports/{job_id}").json()
    assert client.get(f"/api/exports/{job_id}/download").status_code == 409
    assert client.delete(f"/api/exports/{job_id}").status_code == 200
    assert wait_terminal(client, job_id)["status"] == "cancelled"
    deadline = time.monotonic() + 5
    while export_jobs._JOBS[job_id]["active"] and time.monotonic() < deadline:
        time.sleep(0.03)
    assert not export_jobs._JOBS[job_id]["active"]
    assert not (export_jobs._ROOT / (job_id + ".part")).exists()
    assert client.get(f"/api/exports/{job_id}/download").status_code == 409
