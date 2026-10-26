import threading
import time

import pandas as pd
from fastapi.testclient import TestClient

import data_jobs
import datasets
import main


def terminal(client, job_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = client.get('/api/data-jobs/' + job_id).json()
        if job['status'] not in {'queued','running','cancelling'}:
            return job
        time.sleep(.01)
    raise AssertionError('Job did not finish')


def test_api_returns_before_work_cancels_and_discards_result(tmp_path, monkeypatch):
    manager = data_jobs.DataJobs(tmp_path/'jobs.sqlite3', workers=1, capacity=1)
    monkeypatch.setattr(data_jobs, '_instance', manager)
    entered, release = threading.Event(), threading.Event()
    created = []
    def slow(req):
        entered.set()
        assert release.wait(5)
        result = datasets.open_dataset(pd.DataFrame({'id':[1]}), 'cancel-test')
        created.append(result['dataset_id'])
        return result
    monkeypatch.setattr(main, 'open_dataset', slow)
    client = TestClient(main.app)
    body = {'kind':'aurora','resource_id':'test','table':'person'}
    try:
        response = client.post('/api/data-jobs/open', json=body)
        assert response.status_code == 202
        job_id = response.json()['job_id']
        assert entered.wait(2)
        assert client.get('/api/health').status_code == 200
        assert client.post('/api/data-jobs/open', json=body).status_code == 429
        assert TestClient(main.app).get('/api/data-jobs/'+job_id).status_code == 404
        assert client.post('/api/data-jobs/'+job_id+'/cancel').json()['status'] == 'cancelling'
        release.set()
        assert terminal(client, job_id)['status'] == 'cancelled'
        assert created and created[0] not in datasets._store
    finally:
        release.set()
        manager.shutdown()


def test_real_open_and_join_jobs_return_queryable_result(client, fake_aurora, tmp_path, monkeypatch):
    manager = data_jobs.DataJobs(tmp_path/'jobs.sqlite3')
    monkeypatch.setattr(data_jobs, '_instance', manager)
    monkeypatch.setattr(main, '_lineage_engine', lambda: None)
    monkeypatch.setattr(main.lineage, 'record', lambda *args, **kwargs: None)
    opened = []
    try:
        for _ in range(2):
            response = client.post('/api/data-jobs/open', json={'source_ref': {'kind':'aurora','resource_id':'test','schema':'cdm','table':'person'}})
            assert response.status_code == 202, response.text
            job = terminal(client, response.json()['job_id'])
            assert job['status'] == 'complete', job
            opened.append(job['result']['dataset_id'])
        response = client.post('/api/data-jobs/join', json={'left_id':opened[0], 'right_id':opened[1], 'left_on':'person_id','right_on':'person_id','how':'inner'})
        job = terminal(client, response.json()['job_id'])
        assert job['status'] == 'complete', job
        opened.append(job['result']['dataset_id'])
        result = client.post('/api/datasets/'+opened[-1]+'/query', json={'page_size':2}).json()
        assert result['total'] == 100
        assert len(result['rows']['data']) == 2
        manager.shutdown()
        recovered = data_jobs.DataJobs(tmp_path/'jobs.sqlite3')
        try:
            with recovered.connect() as db:
                assert set(r[0] for r in db.execute('SELECT status FROM jobs')) == {'interrupted'}
        finally:
            recovered.shutdown()
    finally:
        for dataset_id in opened:
            datasets.close_dataset(dataset_id)
        manager.shutdown()


def test_cloud_cli_serializes_credential_process_calls(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import cloud_cli
    active = 0
    peak = 0
    lock = threading.Lock()
    def execute(*args, **kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(.02)
        with lock:
            active -= 1
        return 'ok'
    monkeypatch.setattr(cloud_cli.subprocess, 'run', execute)
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(lambda _: cloud_cli.run(['aws','s3','ls'], timeout=2), range(8))) == ['ok'] * 8
    assert peak == 1


def test_resource_polling_does_not_restart_warmup_or_erase_good_cache(monkeypatch):
    import db
    records = [{'id':'existing','resourceType':'AWS_AURORA_DATABASE'}]
    monkeypatch.setattr(db, '_resource_cache', records)
    monkeypatch.setattr(db, '_last_refresh', time.monotonic()-30)
    calls = []
    monkeypatch.setattr(db, '_fetch_resources', lambda: calls.append('fetch') or [])
    monkeypatch.setattr(db, 'configure_aws_profiles', lambda: calls.append('configure'))
    assert db._ensure_cache() == records
    assert calls == []
    db._refresh_resource_cache()
    assert db._resource_cache == records
    assert calls == ['fetch']
