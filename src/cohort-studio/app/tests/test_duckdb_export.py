import duckdb
import pandas as pd
import pytest
from fastapi.testclient import TestClient
import datasets, main

@pytest.mark.parametrize('disk', [False, True])
def test_filtered_duckdb_download_roundtrip(tmp_path, monkeypatch, disk):
    monkeypatch.setattr(main, '_lineage_engine', lambda: None)
    monkeypatch.setattr(main.lineage, 'record', lambda *a, **kw: None)
    frame = pd.DataFrame({'id': [1,2,3], 'label': ['a', None, 'c']})
    source = None
    if disk:
        source_path = str(tmp_path / 'input.duckdb')
        con = duckdb.connect(source_path)
        con.register('df', frame)
        con.execute('CREATE TABLE data AS SELECT * FROM df')
        con.close()
        source = {'path': source_path, 'table': 'data', 'columns': ['id', 'label']}
    did = datasets.open_dataset(frame, 'fixture', disk_source=source)['dataset_id']
    try:
        result = TestClient(main.app).post(f'/api/datasets/{did}/export', json={'format': 'duckdb', 'filters': [{'column':'id','kind':'range','min':2,'max':3}]})
        assert result.status_code == 200, result.text
        assert 'cohort.duckdb' in result.headers['content-disposition']
        output = tmp_path / 'download.duckdb'
        output.write_bytes(result.content)
        con = duckdb.connect(str(output), read_only=True)
        assert con.execute('select * from data order by id').fetchall() == [(2, None), (3, 'c')]
        con.close()
    finally:
        datasets.close_dataset(did)


def test_duckdb_export_rejects_partial_disk_source(tmp_path, monkeypatch):
    monkeypatch.setattr(main, '_lineage_engine', lambda: None)
    monkeypatch.setattr(main.lineage, 'record', lambda *a, **kw: None)
    monkeypatch.setattr(main.queries, 'ROW_CAP', 2)
    source_path = str(tmp_path / 'input.duckdb')
    con = duckdb.connect(source_path)
    con.execute('CREATE TABLE data AS SELECT * FROM range(3) r(id)')
    con.close()
    did = datasets.open_dataset(pd.DataFrame({'id':[0,1,2]}), 'fixture', disk_source={'path':source_path,'table':'data','columns':['id']})['dataset_id']
    try:
        response = TestClient(main.app).post(f'/api/datasets/{did}/export', json={'format':'duckdb'})
        assert response.status_code == 413
    finally:
        datasets.close_dataset(did)


def test_duckdb_export_cleans_up_when_connection_setup_fails(tmp_path, monkeypatch):
    import disk_data
    monkeypatch.setattr(disk_data, '_ROOT', tmp_path)
    def fail(*args, **kwargs):
        raise RuntimeError('connection setup failed')
    monkeypatch.setattr(disk_data, '_configure', fail)
    with pytest.raises(RuntimeError, match='setup failed'):
        disk_data.export_dataframe(pd.DataFrame({'id':[1]}), 'duckdb')
    assert not list(tmp_path.glob('export-*'))


def test_duckdb_export_rejects_ambiguous_case_insensitive_columns(tmp_path):
    import disk_data
    frame = pd.DataFrame([[1,2]], columns=['id','ID'])
    with pytest.raises(ValueError, match='unique ignoring case'):
        disk_data.export_dataframe(frame, 'duckdb')
