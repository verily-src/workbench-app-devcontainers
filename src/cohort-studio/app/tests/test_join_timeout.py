import time

import pandas as pd
import pytest

import data_jobs
import datasets
import joins
import db


@pytest.fixture
def fixture(engine, tmp_path, monkeypatch):
    with engine.begin() as con:
        con.exec_driver_sql('CREATE OR REPLACE VIEW public.studio_fast_join_test AS SELECT i AS id FROM generate_series(1,10000) i')
        con.exec_driver_sql('CREATE OR REPLACE VIEW public.studio_slow_join_test AS SELECT i AS id FROM generate_series(1,10000) i CROSS JOIN LATERAL (SELECT pg_sleep(0.002 + i*0)) delay')
    monkeypatch.setattr(db, 'get_engine_for_resource', lambda _: engine)
    ids = []
    for sql in ('SELECT id FROM public.studio_slow_join_test', 'SELECT id FROM public.studio_fast_join_test'):
        source = {'resource_id': 'fixture', 'sql': sql, 'params': {}, 'columns': {'id': 'id'}, 'estimated_bytes': 1024}
        did = datasets.open_dataset(pd.DataFrame({'id': [1]}), 'fixture')['dataset_id']
        datasets.get(did)['live_source'] = source
        ids.append(did)
    steps = [{'right_id': ids[1], 'how': 'inner', 'conditions': [{'left': 'id', 'op': '=', 'right': 'id'}]}]
    yield engine, ids, steps
    for id in ids:
        datasets.close_dataset(id)
    with engine.begin() as con:
        con.exec_driver_sql('DROP VIEW public.studio_slow_join_test')
        con.exec_driver_sql('DROP VIEW public.studio_fast_join_test')


def test_preview_fetches_sample_without_expensive_full_counts(fixture):
    engine, ids, steps = fixture
    started = time.monotonic()
    result = joins.preview(ids[0], steps)
    assert time.monotonic() - started < 5
    assert len(result['sample']) == 20
    assert result['sample_truncated'] is True
    assert result['sample_only'] is True
    assert result['total_rows'] is None and result['base_rows'] is None


def test_join_cancel_interrupts_actual_postgres_statement(fixture, tmp_path):
    engine, ids, steps = fixture
    manager = data_jobs.DataJobs(tmp_path/'jobs.sqlite3', workers=1)
    try:
        job = manager.submit('join', 'owner', lambda: joins.run(ids[0], steps), lambda _: None)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with engine.connect() as conn:
                sleeping = conn.exec_driver_sql("SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE wait_event = 'PgSleep' AND pid <> pg_backend_pid())").scalar()
            if sleeping:
                break
            time.sleep(.02)
        assert sleeping
        assert manager.cancel(job['job_id'], 'wrong-owner') is None
        started = time.monotonic()
        manager.cancel(job['job_id'], 'owner')
        while time.monotonic() - started < 5:
            state = manager.get(job['job_id'], 'owner')['status']
            if state == 'cancelled':
                break
            time.sleep(.02)
        assert state == 'cancelled'
        assert time.monotonic() - started < 5
    finally:
        manager.shutdown()


def test_preview_job_can_cancel_postgres_and_is_owner_scoped(fixture, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import main

    engine, ids, steps = fixture
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE OR REPLACE VIEW public.studio_slow_join_test AS SELECT i AS id FROM generate_series(1,10000) i CROSS JOIN LATERAL (SELECT pg_sleep(20 + i*0)) delay')
    manager = data_jobs.DataJobs(tmp_path/'preview.sqlite3', workers=1)
    monkeypatch.setattr(data_jobs, '_instance', manager)
    client = TestClient(main.app)
    try:
        response = client.post('/api/data-jobs/join_preview', json={'base_id': ids[0], 'steps': steps})
        assert response.status_code == 202, response.text
        job_id = response.json()['job_id']
        assert TestClient(main.app).post(f'/api/data-jobs/{job_id}/cancel').status_code == 404
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with engine.connect() as conn:
                sleeping = conn.exec_driver_sql("SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE wait_event = 'PgSleep' AND pid <> pg_backend_pid())").scalar()
            if sleeping:
                break
            time.sleep(.02)
        assert sleeping
        assert client.post(f'/api/data-jobs/{job_id}/cancel').status_code == 200
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = client.get(f'/api/data-jobs/{job_id}').json()['status']
            if state == 'cancelled':
                break
            time.sleep(.02)
        assert state == 'cancelled'
    finally:
        manager.shutdown()


def test_cancel_before_sql_starts_is_not_lost(fixture, tmp_path):
    import threading
    import query_cancellation

    engine, _, _ = fixture
    manager = data_jobs.DataJobs(tmp_path/'race.sqlite3', workers=1)
    entered, release = threading.Event(), threading.Event()
    def work():
        with engine.connect() as conn, query_cancellation.postgres_connection(conn):
            entered.set()
            assert release.wait(3)
            conn.exec_driver_sql('SELECT pg_sleep(20)')
    try:
        job = manager.submit('join', 'owner', work, lambda _: None)
        assert entered.wait(3)
        manager.cancel(job['job_id'], 'owner')
        release.set()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = manager.get(job['job_id'], 'owner')['status']
            if state == 'cancelled':
                break
            time.sleep(.02)
        assert state == 'cancelled'
    finally:
        release.set()
        manager.shutdown()


def test_join_timeout_config_validates(monkeypatch):
    import query_cancellation
    monkeypatch.delenv('STUDIO_JOIN_TIMEOUT_MS', raising=False)
    assert query_cancellation.join_timeout_ms() == 0
    monkeypatch.setenv('STUDIO_JOIN_TIMEOUT_MS', '180000')
    assert query_cancellation.join_timeout_ms() == 180000
    monkeypatch.setenv('STUDIO_JOIN_TIMEOUT_MS', '-1')
    with pytest.raises(ValueError):
        query_cancellation.join_timeout_ms()


def test_preview_can_run_longer_than_ten_seconds(fixture):
    engine, ids, steps = fixture
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE OR REPLACE VIEW public.studio_slow_join_test AS SELECT i AS id FROM generate_series(1,10000) i CROSS JOIN LATERAL (SELECT pg_sleep(0.5 + i*0)) delay')
    started = time.monotonic()
    result = joins.preview(ids[0], steps)
    assert time.monotonic() - started >= 10
    assert len(result['sample']) == 20
    assert result['sample_truncated']
