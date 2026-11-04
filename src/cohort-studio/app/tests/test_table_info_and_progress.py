import threading
import time

import pandas as pd
from fastapi.testclient import TestClient

import data_jobs
import datasets
import duck
import main
import queries


def _wait(client, job_id, until):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = client.get('/api/data-jobs/' + job_id).json()
        if until(job):
            return job
        time.sleep(.01)
    raise AssertionError(f'Job never reached the expected state: {job}')


def test_open_job_reports_label_phase_and_elapsed(tmp_path, monkeypatch):
    manager = data_jobs.DataJobs(tmp_path / 'jobs.sqlite3', workers=1, capacity=2)
    monkeypatch.setattr(data_jobs, '_instance', manager)
    reading, release = threading.Event(), threading.Event()

    def slow(req):
        data_jobs.report('Reading cdm.person from omop', resource='omop',
                         table='cdm.person', cap=100000, ignored=object())
        reading.set()
        assert release.wait(5)
        return datasets.open_dataset(pd.DataFrame({'id': [1, 2]}), 'progress-test')

    monkeypatch.setattr(main, 'open_dataset', slow)
    client = TestClient(main.app)
    try:
        body = {'source_ref': {'kind': 'aurora', 'resource_id': 'omop',
                               'schema': 'cdm', 'table': 'person'}}
        started = client.post('/api/data-jobs/open', json=body).json()
        assert started['label'] == 'cdm.person from omop'
        assert reading.wait(2)
        running = _wait(client, started['job_id'],
                        lambda j: j.get('phase', '').startswith('Reading'))
        assert running['status'] == 'running'
        assert running['detail'] == {'resource': 'omop', 'table': 'cdm.person', 'cap': 100000}
        assert running['elapsed'] >= 0 and running['started'] > 0
        release.set()
        done = _wait(client, started['job_id'], lambda j: j['status'] == 'complete')
        assert done['label'] == 'cdm.person from omop'
        frozen = done['elapsed']
        time.sleep(.05)
        assert client.get('/api/data-jobs/' + started['job_id']).json()['elapsed'] == frozen
        datasets.close_dataset(done['result']['dataset_id'])
    finally:
        release.set()
        manager.shutdown()


def test_report_outside_a_job_is_a_no_op():
    data_jobs.report('nothing to see', rows=1)


def test_join_label_names_sources_type_and_keys(monkeypatch):
    left = datasets.open_dataset(pd.DataFrame({'person_id': [1]}), 'omop / cdm.person')
    right = datasets.open_dataset(pd.DataFrame({'person_id': [1]}), 'omop / genetics_demo.samples')
    try:
        req = main.JoinRequest(left_id=left['dataset_id'], right_id=right['dataset_id'],
                               left_on='person_id', right_on='person_id', how='inner')
        label = main._data_job_label('join', req)
        assert label == ('omop / cdm.person + omop / genetics_demo.samples '
                         '(inner on person_id)')
        assert main._data_job_label('join_preview', req) == label
        expired = main.JoinRequest(left_id='missing', right_id='gone', left_on='a', right_on='a')
        assert main._data_job_label('join', expired) == 'selected tables'
    finally:
        datasets.close_dataset(left['dataset_id'])
        datasets.close_dataset(right['dataset_id'])


def test_s3_listing_keeps_size_and_modified_time():
    output = '\n'.join([
        '                           PRE folder/',
        '2026-10-21 21:52:40    2605984 base/care_site.csv',
        '2026-10-21 21:52:41       1024 base/_SUCCESS.marker',
        '2026-10-22 01:37:06  395123456 base/cost.parquet',
    ])
    entries = duck.parse_s3_ls_entries(output, prefix='base')
    assert entries == [
        {'name': 'care_site.csv', 'modified': '2026-10-21 21:52:40', 'bytes': 2605984},
        {'name': 'cost.parquet', 'modified': '2026-10-22 01:37:06', 'bytes': 395123456},
    ]
    assert duck.parse_s3_ls(output, prefix='base') == ['care_site.csv', 'cost.parquet']


def test_tables_endpoint_returns_s3_file_metadata(monkeypatch):
    monkeypatch.setattr(duck, 'describe_s3_files', lambda rid: [
        {'name': 'cost.parquet', 'bytes': 395123456, 'modified': '2026-10-22 01:37:06'}])
    listed = TestClient(main.app).get('/api/tables', params={'kind': 's3', 'resource_id': 'bucket'}).json()
    assert listed == [{'name': 'cost.parquet', 'detail': 'file', 'bytes': 395123456,
                       'modified': '2026-10-22 01:37:06'}]


def test_row_estimate_handles_unanalyzed_and_views():
    assert queries._row_estimate('table', 32355293, 32355293) == 32355293
    assert queries._row_estimate('table', -1, 1200) == 1200      # never analyzed
    assert queries._row_estimate('table', 0, 5000) == 5000       # stale zero estimate
    assert queries._row_estimate('table', 0, 0) == 0
    assert queries._row_estimate('table', -1, None) is None
    assert queries._row_estimate('view', 10, 10) is None


def test_list_tables_falls_back_to_names_when_stats_query_fails():
    class Result:
        def __init__(self, rows):
            self.rows = rows

        def fetchall(self):
            return self.rows

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, statement):
            if 'pg_total_relation_size' in str(statement):
                raise RuntimeError('permission denied for pg_class')
            return Result([('cdm', 'person', 'BASE TABLE'), ('public', 'v', 'VIEW')])

    class Engine:
        def connect(self):
            return Conn()

    assert queries.list_tables(Engine()) == [
        {'name': 'cdm.person', 'table': 'person', 'schema': 'cdm', 'kind': 'table'},
        {'name': 'v', 'table': 'v', 'schema': 'public', 'kind': 'view'},
    ]
