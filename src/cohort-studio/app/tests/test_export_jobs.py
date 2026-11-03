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


def test_gzip_export_filtered_rows_and_download(client, export_source):
    import gzip

    dataset_id, _ = export_source
    filters = [{"column": "person_id", "kind": "range", "min": 120004, "max": 120005}]
    started = client.post(f"/api/datasets/{dataset_id}/exports", json={"filters": filters, "format": "tsv.gz"})
    assert started.status_code == 202, started.text
    job_id = started.json()["id"]
    outcome = wait_terminal(client, job_id)
    assert outcome["status"] == "complete", outcome
    assert outcome["rows"] == 2
    download = client.get(f"/api/exports/{job_id}/download")
    assert download.status_code == 200
    assert 'cohort.tsv.gz' in download.headers['content-disposition']
    rows = list(csv.reader(io.StringIO(gzip.decompress(download.content).decode()), delimiter="\t"))
    assert rows == [["person_id", "label"], ["120004", "old"], ["120005", "old"]]
    assert client.delete(f"/api/exports/{job_id}").status_code == 200


def test_gzip_limit_uses_compressed_file_size(client, export_source, monkeypatch):
    import gzip

    dataset_id, _ = export_source
    datasets.get(dataset_id)['live_source']['sql'] = (
        "SELECT 1 AS person_id, repeat('a', 300) AS label FROM generate_series(1, 2000)")
    monkeypatch.setattr(export_jobs, 'MAX_JOB_BYTES', 10000)
    job_id = client.post(f'/api/datasets/{dataset_id}/exports', json={'format': 'tsv.gz'}).json()['id']
    outcome = wait_terminal(client, job_id)
    assert outcome['status'] == 'complete', outcome.get('error')
    assert outcome['rows'] == 2000
    content = client.get(f'/api/exports/{job_id}/download').content
    assert len(content) < 10000
    assert len(gzip.decompress(content)) > 10000


def test_export_encodes_complex_types_and_direct_live_endpoint_rejects(client, export_source):
    import json

    dataset_id, _ = export_source
    source = datasets.get(dataset_id)['live_source']
    source['sql'] = "SELECT true AS flag, '{\"a\":1}'::jsonb AS details, ARRAY['x','y'] AS tags, decode('abcd','hex') AS binary_data"
    source['columns'] = {name: name for name in ('flag', 'details', 'tags', 'binary_data')}
    direct = client.post(f'/api/datasets/{dataset_id}/export', json={'format': 'tsv'})
    assert direct.status_code == 400
    job = client.post(f'/api/datasets/{dataset_id}/exports', json={}).json()
    assert wait_terminal(client, job['id'])['status'] == 'complete'
    data = client.get(f'/api/exports/{job["id"]}/download')
    rows = list(csv.reader(io.StringIO(data.text), delimiter='\t'))
    assert rows[1][0] == 'true'
    assert json.loads(rows[1][1]) == {'a': 1}
    assert json.loads(rows[1][2]) == ['x', 'y']
    assert rows[1][3] == r'\xabcd'


@pytest.mark.parametrize('format', ['json', 'parquet'])
def test_full_source_format_export_preserves_rows_and_nulls(client, export_source, tmp_path, format):
    import json
    import duckdb

    dataset_id, _ = export_source
    source = datasets.get(dataset_id)['live_source']
    source['sql'] = """SELECT n AS person_id, CAST(CASE WHEN n=1 THEN NULL ELSE n END AS numeric(10,2)) AS measure,
        n % 2 = 0 AS selected, DATE '2020-01-01' AS observed,
        ARRAY['a','b']::text[] AS tags, '{\"note\":\"hi\"}'::jsonb AS metadata
        FROM generate_series(1,120005) n"""
    source['columns'] = {name:name for name in ('person_id','measure','selected','observed','tags','metadata')}
    started = client.post(f'/api/datasets/{dataset_id}/exports', json={'format':format})
    assert started.status_code == 202, started.text
    job_id = started.json()['id']
    outcome = wait_terminal(client, job_id)
    assert outcome['status'] == 'complete', outcome.get('error')
    assert outcome['rows'] == 120005
    response = client.get(f'/api/exports/{job_id}/download')
    assert response.status_code == 200
    assert 'cohort.' + format in response.headers['content-disposition']
    if format == 'json':
        from decimal import Decimal
        rows = json.loads(response.content, parse_float=Decimal)
        assert len(rows) == 120005
        assert rows[0] == {'person_id':1, 'measure':None, 'selected':False,
                           'observed':'2020-01-01', 'tags':['a','b'], 'metadata':{'note':'hi'}}
        assert rows[-1]['measure'] == Decimal('120005.00')
    else:
        file = tmp_path / 'out.parquet'
        file.write_bytes(response.content)
        with duckdb.connect() as con:
            assert con.execute(f"SELECT COUNT(*) FROM read_parquet('{file}')").fetchone()[0] == 120005
            row = con.execute(f"SELECT * FROM read_parquet('{file}') WHERE person_id=1").fetchone()
            assert row[0] == 1 and row[1] is None and row[2] is False
            assert row[4] == ['a','b'] and json.loads(row[5]) == {'note':'hi'}
            types = {r[0]:r[1] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{file}')").fetchall()}
            assert types['measure'] == 'DECIMAL(10,2)'
            assert types['selected'] == 'BOOLEAN' and types['observed'] == 'DATE'


@pytest.mark.parametrize('format', ['json', 'parquet'])
def test_cancel_running_format_export(client, engine, export_source, format):
    dataset_id, _ = export_source
    datasets.get(dataset_id)['live_source'] = {
        'resource_id': 'export-test', 'sql':'SELECT 1 AS person_id, pg_sleep(60)::text AS label',
        'columns': {'person_id':'person_id','label':'label'}}
    job_id = client.post(f'/api/datasets/{dataset_id}/exports', json={'format':format}).json()['id']
    deadline = time.monotonic()+5
    while time.monotonic()<deadline:
        with engine.connect() as con:
            running = con.execute(text("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE wait_event='PgSleep')")).scalar()
        if running: break
        time.sleep(.03)
    assert running
    assert client.delete(f'/api/exports/{job_id}').status_code == 200
    assert wait_terminal(client, job_id)['status'] == 'cancelled'
    assert client.get(f'/api/exports/{job_id}/download').status_code == 409


def test_parquet_unsupported_type_fails_without_a_file(client, export_source):
    dataset_id, _ = export_source
    source = datasets.get(dataset_id)['live_source']
    source['sql'] = "SELECT 1::numeric AS measure"
    source['columns'] = {'measure':'measure'}
    job_id = client.post(f'/api/datasets/{dataset_id}/exports', json={'format':'parquet'}).json()['id']
    result = wait_terminal(client, job_id)
    assert result['status'] == 'failed', result
    assert 'precision' in result['error']
    assert client.get(f'/api/exports/{job_id}/download').status_code == 409


@pytest.mark.parametrize('format', ['json', 'parquet'])
def test_empty_result_and_filtered_result(client, export_source, tmp_path, format):
    import json
    import duckdb
    dataset_id, _ = export_source
    filters = [{'column': 'person_id', 'kind': 'range', 'min': 200000, 'max': 200001}]
    job_id = client.post(f'/api/datasets/{dataset_id}/exports', json={'format':format,'filters':filters}).json()['id']
    outcome = wait_terminal(client, job_id)
    assert outcome['status'] == 'complete', outcome.get('error')
    assert outcome['rows'] == 0
    data = client.get(f'/api/exports/{job_id}/download').content
    if format == 'json':
        assert json.loads(data) == []
    else:
        file = tmp_path / 'empty.parquet'
        file.write_bytes(data)
        with duckdb.connect() as con:
            assert con.execute(f"SELECT COUNT(*) FROM read_parquet('{file}')").fetchone()[0] == 0
            assert [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{file}')").fetchall()] == ['person_id','label']


@pytest.mark.parametrize('format', ['json', 'parquet'])
def test_columnar_export_size_limit_deletes_incomplete_file(client, export_source, monkeypatch, format):
    dataset_id, _ = export_source
    monkeypatch.setattr(export_jobs, 'MAX_JOB_BYTES', 32)
    job_id = client.post(f'/api/datasets/{dataset_id}/exports', json={'format':format}).json()['id']
    outcome = wait_terminal(client, job_id)
    assert outcome['status'] == 'failed'
    assert 'storage limit' in outcome['error']
    assert not (export_jobs._ROOT / (job_id + '.part')).exists()
    assert client.get(f'/api/exports/{job_id}/download').status_code == 409


@pytest.mark.parametrize('format', ['json', 'parquet'])
def test_jsonb_decimal_precision_and_restore_connection_adapters(client, engine, export_source, tmp_path, format):
    import decimal
    import json
    import duckdb
    from psycopg.pq import Format

    dataset_id, _ = export_source
    source = datasets.get(dataset_id)['live_source']
    source['sql'] = "SELECT '{\"value\":0.12345678901234567890123456789}'::jsonb AS metadata"
    source['columns'] = {'metadata': 'metadata'}
    with engine.connect() as conn:
        adapters = conn.connection.driver_connection.adapters
        original = [adapters.get_loader(oid, rep) for oid in (114, 3802) for rep in (Format.TEXT, Format.BINARY)]
    job_id = client.post(f'/api/datasets/{dataset_id}/exports', json={'format':format}).json()['id']
    outcome = wait_terminal(client, job_id)
    assert outcome['status'] == 'complete', outcome.get('error')
    data = client.get(f'/api/exports/{job_id}/download').content
    if format == 'json':
        metadata = json.loads(data, parse_float=decimal.Decimal)[0]['metadata']
    else:
        file = tmp_path / 'jsonb.parquet'
        file.write_bytes(data)
        with duckdb.connect() as con:
            value = con.execute(f"SELECT metadata FROM read_parquet('{file}')").fetchone()[0]
        metadata = json.loads(value, parse_float=decimal.Decimal)
    assert metadata['value'] == decimal.Decimal('0.12345678901234567890123456789')
    with engine.connect() as conn:
        adapters = conn.connection.driver_connection.adapters
        assert [adapters.get_loader(oid, rep) for oid in (114, 3802) for rep in (Format.TEXT, Format.BINARY)] == original


@pytest.mark.parametrize('format', ['tsv', 'tsv.gz'])
def test_tsv_jsonb_decimal_precision_and_adapter_restoration(client, engine, export_source, format):
    import decimal
    import gzip
    import json
    from psycopg.pq import Format

    dataset_id, _ = export_source
    source = datasets.get(dataset_id)['live_source']
    source['sql'] = "SELECT '{\"value\":0.12345678901234567890123456789}'::jsonb AS metadata"
    source['columns'] = {'metadata': 'metadata'}
    with engine.connect() as conn:
        adapters = conn.connection.driver_connection.adapters
        original = [adapters.get_loader(oid, rep) for oid in (114, 3802) for rep in (Format.TEXT, Format.BINARY)]
    started = client.post(f'/api/datasets/{dataset_id}/exports', json={'format':format})
    assert started.status_code == 202, started.text
    job_id = started.json()['id']
    outcome = wait_terminal(client, job_id)
    assert outcome['status'] == 'complete', outcome.get('error')
    content = client.get(f'/api/exports/{job_id}/download').content
    if format == 'tsv.gz': content = gzip.decompress(content)
    rows = list(csv.reader(io.StringIO(content.decode()), delimiter='\t'))
    metadata = json.loads(rows[1][0], parse_float=decimal.Decimal)
    assert metadata['value'] == decimal.Decimal('0.12345678901234567890123456789')
    with engine.connect() as conn:
        adapters = conn.connection.driver_connection.adapters
        assert [adapters.get_loader(oid, rep) for oid in (114, 3802) for rep in (Format.TEXT, Format.BINARY)] == original


def test_failed_submission_does_not_leak_job(client, export_source, monkeypatch):
    import execution
    dataset_id, _ = export_source
    before = set(export_jobs._JOBS)
    def fail(*args, **kwargs):
        raise RuntimeError('executor not available')
    monkeypatch.setattr(execution, 'submit', fail)
    with pytest.raises(RuntimeError, match='executor not available'):
        client.post(f'/api/datasets/{dataset_id}/exports', json={})
    assert set(export_jobs._JOBS) == before


def test_cancel_does_not_hold_global_lock_or_release_connection_early(export_source, monkeypatch):
    import threading
    import execution

    dataset_id, _ = export_source
    monkeypatch.setattr(execution, 'submit', lambda *_: None)
    job_id = export_jobs.start(datasets.get(dataset_id)['live_source'], [], owner='owner')['id']
    entered, release, cleared, status_checked = (threading.Event() for _ in range(4))
    class BlockingConnection:
        def cancel(self):
            entered.set()
            assert release.wait(5)
    job = export_jobs._JOBS[job_id]
    with export_jobs._LOCK:
        job['connection'] = BlockingConnection()
    def clear_connection():
        with job['connection_lock']:
            with export_jobs._LOCK:
                job['connection'] = None
            cleared.set()
    def check_status():
        assert export_jobs.status(job_id, owner='owner')['status'] == 'cancelled'
        status_checked.set()
    cancelling = threading.Thread(target=lambda: export_jobs.cancel(job_id, owner='owner'))
    clearing = threading.Thread(target=clear_connection)
    checking = threading.Thread(target=check_status)
    try:
        cancelling.start()
        assert entered.wait(2)
        clearing.start()
        checking.start()
        assert status_checked.wait(2), 'cancel held the global job lock'
        assert not cleared.wait(.1), 'connection was released while cancellation was in flight'
    finally:
        release.set()
        cancelling.join(5)
        clearing.join(5)
        checking.join(5)
        with export_jobs._LOCK:
            job['active'] = False
    assert cleared.is_set()
