import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import duckdb
import pandas as pd
import pytest
from fastapi.testclient import TestClient

import datasets
import execution
import grain
import main
import operational_store
from source_models import source_dict


@pytest.fixture(autouse=True)
def operations(tmp_path, monkeypatch):
    store = operational_store.Store(tmp_path/'operations.sqlite3')
    monkeypatch.setattr(operational_store, '_instance', store)
    yield store
    if not store.closed:
        store.shutdown()


def test_composite_grain_real_postgres_persists_reopens_and_detects_drift(client, fake_aurora, operations):
    with fake_aurora.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE public.samples (person_id bigint, visit_id bigint)')
        conn.exec_driver_sql('INSERT INTO public.samples VALUES (1,1),(1,2),(2,1)')
    ref = {'kind':'aurora', 'resource_id':'test', 'schema':'public', 'table':'samples'}
    opened = client.post('/api/datasets/open', json={'source_ref':ref})
    assert opened.status_code == 200, opened.text
    did = opened.json()['dataset_id']
    url = f'/api/datasets/{did}/grain'
    try:
        assert client.put(url, json={'entity':'event','keys':['missing']}).status_code == 400
        assert client.put(url, json={'entity':'event','keys':['person_id'],'unexpected':1}).status_code == 422
        assert client.put(url, json={'entity':'event','keys':['person_id','person_id']}).status_code == 422
        saved = client.put(url, json={'entity':'event','keys':['person_id','visit_id']})
        assert saved.status_code == 200, saved.text
        recipe = source_dict(saved.json()['source_ref'])
        assert recipe['grain']['keys'] == ['person_id','visit_id']
        checked = client.post(url+'/check').json()
        assert (checked['rows'], checked['distinct_keys'], checked['status'], checked['scope']) == (3,3,'unique_non_null','database')
        operations.shutdown()
        operational_store._instance = operational_store.Store(operations.path)
        reopened = client.post('/api/datasets/open', json={'source_ref':ref}).json()['dataset_id']
        try:
            assert client.get(f'/api/datasets/{reopened}/grain').json()['definition'] == recipe['grain']
            with fake_aurora.begin() as conn:
                conn.exec_driver_sql('INSERT INTO public.samples VALUES (1,1),(NULL,4)')
            checked = client.post(f'/api/datasets/{reopened}/grain/check').json()
            assert (checked['rows'], checked['duplicate_key_rows'], checked['null_key_rows'], checked['status']) == (5,1,1,'violated')
        finally:
            datasets.close_dataset(reopened)
    finally:
        datasets.close_dataset(did)
        operational_store._instance.shutdown()


def test_disk_and_sample_grain_scopes(tmp_path):
    path = str(tmp_path/'data.duckdb')
    with duckdb.connect(path) as con:
        con.execute('CREATE TABLE data (sample_id VARCHAR, variant_id VARCHAR)')
        con.execute("INSERT INTO data VALUES ('a','v1'),('a','v2'),('a','v2'),(NULL,'v3')")
    did = datasets.open_dataset(pd.DataFrame({'sample_id':pd.Series(dtype='str'), 'variant_id':pd.Series(dtype='str')}), 'disk',
        disk_source={'path':path, 'columns':['sample_id','variant_id']})['dataset_id']
    try:
        grain.save(did, {'entity':'variant', 'keys':['sample_id','variant_id']})
        result = grain.check(did)
        assert (result['rows'],result['distinct_keys'],result['null_key_rows'],result['duplicate_key_rows']) == (4,2,1,1)
        assert result['scope'] == 'loaded'
    finally:
        datasets.close_dataset(did)
    did = datasets.open_dataset(pd.DataFrame({'id':[1,2]}),'sample',capped=True)['dataset_id']
    try:
        grain.save(did, {'entity':'person','keys':['id']})
        assert grain.check(did)['scope'] == 'sample'
        assert not grain.get(did)['persistent']
    finally:
        datasets.close_dataset(did)


def test_metrics_are_durable_private_and_bounded(operations, monkeypatch):
    monkeypatch.setattr(operational_store, 'MAX_EVENTS', 30)
    for index in range(20):
        operations.record('owner-a', {'event':'operation.finished','operation':'test','elapsed_ms':index,'status':'complete','sql':'secret','prompt':'secret'})
    operations.record('owner-b', {'event':'operation.finished','operation':'private-b','elapsed_ms':2,'status':'failed'})
    operations.queue.join()
    assert operations.summary('owner-a')['groups'][0]['p95_ms'] == 18
    assert all(g['name'] != 'private-b' for g in operations.summary('owner-a')['groups'])
    operations.shutdown()
    restored = operational_store.Store(operations.path)
    try:
        assert restored.summary('owner-a')['groups'][0]['count'] == 20
        with restored.connect() as db:
            assert 'secret' not in str(db.execute('SELECT payload FROM metrics').fetchall())
        for _ in range(35):
            restored.record('owner-a', {'event':'http.finished','route':'/test','status':200})
        restored.queue.join()
        with restored.connect() as db:
            assert db.execute('SELECT count(*) FROM metrics').fetchone()[0] == 30
    finally:
        restored.shutdown()


def test_http_session_metrics_isolated(operations):
    a, b = TestClient(main.app), TestClient(main.app)
    assert a.get('/api/health').status_code == 200
    operations.queue.join()
    first = a.get('/api/performance')
    assert first.status_code == 200
    assert any(g['name']=='/api/health' for g in first.json()['groups'])
    assert b.get('/api/performance').json()['groups'] == []


def test_busy_owner_cannot_take_other_owners_slot():
    gate = execution.AdmissionGate(2, per_owner=1)
    assert gate.acquire(owner='a')
    started, release = threading.Event(), threading.Event()
    def second_a():
        started.set()
        assert gate.acquire(timeout=3, owner='a')
        gate.release(owner='a')
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(second_a)
        assert started.wait(1)
        try:
            assert gate.acquire(timeout=.1, owner='b')
            gate.release(owner='b')
            assert not future.done()
        finally:
            gate.release(owner='a')
        future.result()
    assert gate.active == 0


def test_worker_queue_skips_busy_owner_without_blocking_other_session():
    pool = execution.FairExecutor(max_workers=2)
    entered_a, entered_b, release = threading.Event(), threading.Event(), threading.Event()
    def first():
        entered_a.set()
        assert release.wait(3)
    token = execution.owner_id.set('owner-a')
    try:
        first_future = execution.submit(pool, first)
        assert entered_a.wait(1)
        second_future = execution.submit(pool, lambda: 'second-a')
        execution.owner_id.set('owner-b')
        other_future = execution.submit(pool, lambda: (entered_b.set(), execution.owner_id.get()))
        assert entered_b.wait(1)
        assert not second_future.done()
        assert other_future.result()[1] == 'owner-b'
    finally:
        release.set()
        execution.owner_id.reset(token)
        pool.shutdown()
    first_future.result()
    assert second_future.result() == 'second-a'
