import io
import json
import tempfile
from pathlib import Path

import duckdb
import pandas as pd
import pytest
from fastapi.testclient import TestClient

import datasets
import disk_data
import main


@pytest.fixture
def client_no_db(monkeypatch):
    monkeypatch.setattr(main, '_lineage_engine', lambda: None)
    monkeypatch.setattr(main.lineage, 'record', lambda *args, **kwargs: None)
    return TestClient(main.app)


@pytest.mark.parametrize('format', ['json', 'parquet'])
@pytest.mark.parametrize('disk', [False, True])
def test_filtered_format_export(client_no_db, monkeypatch, tmp_path, format, disk):
    df = pd.DataFrame({'id': [1, 2, 3], 'label': ['alpha', None, 'omega']})
    if disk:
        path = str(tmp_path / 'source.duckdb')
        con = duckdb.connect(path)
        con.register('input_df', df)
        con.execute('CREATE TABLE data AS SELECT * FROM input_df')
        con.close()
        disk_source = {'path': path, 'table': 'data', 'columns': ['id', 'label']}
    else:
        disk_source = None
    did = datasets.open_dataset(df, 'fixture', disk_source=disk_source)['dataset_id']
    try:
        response = client_no_db.post(f'/api/datasets/{did}/export', json={
            'format': format, 'filters': [{'column': 'id', 'kind': 'range', 'min': 2, 'max': 3}]})
        assert response.status_code == 200, response.text
        assert 'cohort.' + format in response.headers['content-disposition']
        if format == 'json':
            rows = json.loads(response.content)
        else:
            parquet = tmp_path / ('result-' + str(disk) + '.parquet')
            parquet.write_bytes(response.content)
            con = duckdb.connect()
            rows = [dict(zip(("id", "label"), row)) for row in con.execute(f"SELECT * FROM read_parquet('{parquet}')").fetchall()]
            con.close()
        assert rows == [{'id': 2, 'label': None}, {'id': 3, 'label': 'omega'}]
    finally:
        datasets.close_dataset(did)


def test_disk_export_rejects_truncation(client_no_db, monkeypatch, tmp_path):
    path = str(tmp_path / 'source.duckdb')
    con = duckdb.connect(path)
    con.execute('CREATE TABLE data AS SELECT * FROM range(3) r(id)')
    con.close()
    df = pd.DataFrame({'id': [0, 1, 2]})
    did = datasets.open_dataset(df, 'fixture', disk_source={'path': path, 'table': 'data', 'columns': ['id']})['dataset_id']
    monkeypatch.setattr(main.queries, 'ROW_CAP', 2)
    try:
        for format in ('tsv', 'tsv.gz', 'json', 'parquet'):
            response = client_no_db.post(f'/api/datasets/{did}/export', json={'format': format})
            assert response.status_code == 413, (format, response.text)
            assert 'more than 2 rows' in response.text
    finally:
        datasets.close_dataset(did)


def test_export_job_is_owned_by_session(client_no_db, monkeypatch):
    import execution
    import export_jobs

    monkeypatch.setattr(execution, 'submit', lambda *_: None)
    source = {'resource_id': 'fixture', 'sql': 'SELECT 1 AS id', 'columns': {'id': 'id'}}
    did = datasets.open_dataset(pd.DataFrame({'id': [1]}), 'live')['dataset_id']
    datasets.get(did)['live_source'] = source
    outsider = TestClient(main.app)
    try:
        started = client_no_db.post(f'/api/datasets/{did}/exports', json={})
        assert started.status_code == 202, started.text
        job_id = started.json()['id']
        assert client_no_db.get(f'/api/exports/{job_id}').status_code == 200
        assert outsider.get(f'/api/exports/{job_id}').status_code == 404
        assert outsider.get(f'/api/exports/{job_id}/download').status_code == 404
        assert outsider.delete(f'/api/exports/{job_id}').status_code == 404
        assert client_no_db.delete(f'/api/exports/{job_id}').status_code == 200
    finally:
        datasets.close_dataset(did)
        with export_jobs._LOCK:
            export_jobs._JOBS.pop(job_id, None)
