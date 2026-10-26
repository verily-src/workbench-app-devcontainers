import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
from fastapi.testclient import TestClient

import data_jobs
import datasets
import execution
import main


def test_api_distinguishes_rows_people_and_traces_sql(client, fake_aurora, caplog):
    caplog.set_level(logging.INFO, logger='studio.execution')
    with fake_aurora.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE public.samples (person_id bigint)')
        conn.exec_driver_sql('INSERT INTO public.samples VALUES (1),(1),(2),(NULL)')
    opened = datasets.open_dataset(pd.DataFrame({'person_id': [1]}), 'test',
        live_source={'resource_id': 'test', 'sql': 'SELECT * FROM public.samples', 'columns': {'person_id': 'person_id'}})
    did = opened['dataset_id']
    try:
        response = client.post(f'/api/datasets/{did}/query', json={'entity_column': 'person_id'})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['total'] == 4
        assert result['entity']['total'] == 2
        assert result['count_contract']['entity_measure'] == 'distinct_non_null'
        assert result['count_contract']['grain'] == 'unspecified'
        trace = response.headers['X-Request-ID']
        events = [json.loads(r.message) for r in caplog.records if r.name == 'studio.execution']
        assert any(e['event'] == 'sql.finished' and e['trace_id'] == trace for e in events)
        assert any(e['event'] == 'http.finished' and e['trace_id'] == trace for e in events)
        assert all('statement' not in e and 'parameters' not in e for e in events)
    finally:
        datasets.close_dataset(did)


def test_bulk_capacity_does_not_block_dashboard_and_context_crosses_worker(caplog):
    caplog.set_level(logging.INFO, logger='studio.execution')
    entered = [threading.Event(), threading.Event(), threading.Event()]
    release = threading.Event()
    @execution.workload('bulk')
    def heavy(index):
        entered[index].set()
        assert release.wait(5)
        return execution.trace_id.get()
    did = datasets.open_dataset(pd.DataFrame({'person_id': [1, 1, None]}), 'test')['dataset_id']
    token = execution.trace_id.set('test-parent')
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [execution.submit(pool, heavy, i) for i in range(2)]
            try:
                assert all(e.wait(2) for e in entered[:2])
                third = execution.submit(pool, heavy, 2)
                assert not entered[2].wait(.1)
                response = TestClient(main.app).post(f'/api/datasets/{did}/query', json={'entity_column':'person_id'})
                assert response.status_code == 200
                assert response.json()['entity']['total'] == 1
            finally:
                release.set()
            assert [f.result() for f in futures] == ['test-parent', 'test-parent']
            assert third.result() == 'test-parent'
    finally:
        execution.trace_id.reset(token)
        datasets.close_dataset(did)


def test_dashboard_admission_returns_retry_and_recovers(monkeypatch):
    gate = execution.AdmissionGate(1)
    monkeypatch.setitem(execution._gates, 'interactive', gate)
    did = datasets.open_dataset(pd.DataFrame({'x': [1]}), 'test')['dataset_id']
    client = TestClient(main.app)
    gate.acquire()
    try:
        response = client.post(f'/api/datasets/{did}/query', json={})
        assert response.status_code == 429
        assert response.headers['Retry-After'] == '1'
    finally:
        gate.release()
    try:
        assert client.post(f'/api/datasets/{did}/query', json={}).status_code == 200
    finally:
        datasets.close_dataset(did)


def test_data_jobs_owner_limit_preserves_other_session(tmp_path):
    manager = data_jobs.DataJobs(tmp_path/'jobs.sqlite3', workers=2)
    release = threading.Event()
    def work():
        assert release.wait(5)
        return {}
    try:
        manager.submit('open', 'first', work, lambda _: None)
        manager.submit('open', 'first', work, lambda _: None)
        try:
            manager.submit('open', 'first', work, lambda _: None)
        except data_jobs.Busy:
            pass
        else:
            raise AssertionError('Owner quota was not enforced')
        assert manager.submit('open', 'second', work, lambda _: None)['job_id']
    finally:
        release.set()
        manager.shutdown()


def test_key_evidence_is_scoped_and_does_not_declare_grain():
    for values, sampled, expected in [([1, 2], False, 'unique_non_null'),
                                       ([1, 1], False, 'duplicates_or_nulls'),
                                       ([1, None], False, 'duplicates_or_nulls'),
                                       ([], False, 'empty'), ([1, 2], True, 'unique_non_null')]:
        did = datasets.open_dataset(pd.DataFrame({'id': values}), 'evidence', capped=sampled)['dataset_id']
        try:
            result = datasets.query(did, [], [], entity_column='id')
            assert result['count_contract']['key_status'] == expected
            assert result['count_contract']['evidence_scope'] == ('sample' if sampled else 'loaded')
            assert result['count_contract']['grain'] == 'unspecified'
        finally:
            datasets.close_dataset(did)


def test_fifo_admission_and_timed_out_waiter_cleanup():
    import time
    gate = execution.AdmissionGate(1)
    gate.acquire()
    order = []
    def wait(index):
        assert gate.acquire(timeout=3)
        try:
            order.append(index)
        finally:
            gate.release()
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = []
        try:
            for index in range(3):
                futures.append(pool.submit(wait, index))
                deadline = time.monotonic() + 2
                while True:
                    with gate.condition:
                        if len(gate.waiters) == index + 1:
                            break
                    assert time.monotonic() < deadline
                    time.sleep(.001)
            assert not gate.acquire(timeout=.01)
        finally:
            gate.release()
        for future in futures:
            future.result()
    assert order == [0, 1, 2]
    assert gate.active == 0 and gate.waiters == []
