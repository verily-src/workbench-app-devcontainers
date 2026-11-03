import threading
import time

import pandas as pd
import pytest

import data_jobs
import disk_data
import query_cancellation


def _wait(manager, job_id, desired, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = manager.get(job_id, 'owner')
        if job['status'] in desired:
            return job
        time.sleep(.02)
    pytest.fail(f'Job did not finish: {job}')


def test_cancel_duckdb_join_interrupts_and_removes_staged_file(tmp_path, monkeypatch):
    monkeypatch.setattr(disk_data, '_ROOT', tmp_path)
    monkeypatch.setattr(disk_data, '_MIN_FREE_BYTES', 0)
    monkeypatch.setattr(disk_data, '_duckdb_estimate', lambda *args: None)
    monkeypatch.setattr(disk_data, '_join_step_sql', lambda *args: 'SELECT sum(hash(i)) AS i FROM range(1000000000000) r(i)')
    started = threading.Event()
    real_stream = disk_data._stream_duck_query
    def stream(*args):
        started.set()
        return real_stream(*args)
    monkeypatch.setattr(disk_data, '_stream_duck_query', stream)
    base = {'df': pd.DataFrame({'i': [1]})}
    right = {'df': pd.DataFrame({'i': [1]})}
    plan = {'base': base, 'steps': [{'ds': right, 'no': 1, 'notes': []}]}
    manager = data_jobs.DataJobs(tmp_path / 'jobs.sqlite3', workers=1)
    try:
        job_id = manager.submit('join', 'owner', lambda: disk_data.run_join(plan), lambda _: None)['job_id']
        assert started.wait(5)
        time.sleep(.25)
        assert manager.get(job_id, 'owner')['status'] == 'running'
        assert manager.cancel(job_id, 'outsider') is None
        manager.cancel(job_id, 'owner')
        assert _wait(manager, job_id, {'cancelled', 'failed'})['status'] == 'cancelled'
        assert not list(tmp_path.glob('dataset-*.duckdb'))
    finally:
        manager.shutdown()


def test_scope_cancels_multiple_connections_and_rejects_late_bind():
    scope = query_cancellation.Scope()
    a, b = threading.Event(), threading.Event()
    with scope.bind(a.set), scope.bind(b.set):
        scope.cancel()
        assert a.wait(1) and b.wait(1)
        with pytest.raises(query_cancellation.Cancelled):
            with scope.bind(lambda: None):
                pass
    scope.finish()


def test_cancel_interrupts_postgres_during_cross_source_staging(engine, tmp_path, monkeypatch):
    import database
    monkeypatch.setattr(disk_data, '_ROOT', tmp_path)
    monkeypatch.setattr(disk_data, '_MIN_FREE_BYTES', 0)
    monkeypatch.setattr(disk_data, '_estimate_live_bytes', lambda source: 1024)
    monkeypatch.setattr(database, 'get_engine_for_resource', lambda _: engine)
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE OR REPLACE VIEW public.studio_cross_cancel_slow AS SELECT i AS id FROM generate_series(1,10000) i CROSS JOIN LATERAL (SELECT pg_sleep(20 + i*0)) delay')
    live = {'resource_id': 'fixture', 'sql': 'SELECT id FROM public.studio_cross_cancel_slow',
            'columns': {'id': 'id'}, 'params': {}}
    base = {'df': pd.DataFrame({'id': [1]}), 'live_source': live}
    right = {'df': pd.DataFrame({'id': [1]})}
    plan = {'base': base, 'steps': [{'ds': right, 'no': 1, 'notes': []}]}
    manager = data_jobs.DataJobs(tmp_path / 'jobs.sqlite3', workers=1)
    try:
        job_id = manager.submit('join', 'owner', lambda: disk_data.run_join(plan), lambda _: None)['job_id']
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with engine.connect() as conn:
                sleeping = conn.exec_driver_sql("SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE wait_event='PgSleep' AND pid <> pg_backend_pid())").scalar()
            if sleeping:
                break
            time.sleep(.02)
        assert sleeping
        manager.cancel(job_id, 'owner')
        assert _wait(manager, job_id, {'cancelled', 'failed'})['status'] == 'cancelled'
        assert not list(tmp_path.glob('dataset-*.duckdb'))
    finally:
        manager.shutdown()
        with engine.begin() as conn:
            conn.exec_driver_sql('DROP VIEW public.studio_cross_cancel_slow')


def test_cancelled_postgres_connection_is_not_reused(engine):
    from sqlalchemy import create_engine

    pooled = create_engine(engine.url, pool_size=1, max_overflow=0)
    scope = query_cancellation.Scope()
    running = threading.Event()
    finished = threading.Event()
    worker_pids = []
    def work():
        token = query_cancellation.current.set(scope)
        try:
            with pooled.connect() as conn:
                worker_pids.append(conn.exec_driver_sql('SELECT pg_backend_pid()').scalar())
                with query_cancellation.postgres_connection(conn):
                    running.set()
                    conn.exec_driver_sql('SELECT pg_sleep(20)')
        except Exception:
            pass
        finally:
            query_cancellation.current.reset(token)
            finished.set()
    thread = threading.Thread(target=work)
    thread.start()
    try:
        assert running.wait(5)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with engine.connect() as conn:
                sleeping = conn.exec_driver_sql("SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE pid=%s AND wait_event='PgSleep')", (worker_pids[0],)).scalar()
            if sleeping:
                break
            time.sleep(.02)
        assert sleeping
        scope.cancel()
        assert finished.wait(5)
        with pooled.connect() as conn:
            replacement = conn.exec_driver_sql('SELECT pg_backend_pid()').scalar()
            assert replacement != worker_pids[0]
            assert conn.exec_driver_sql('SELECT 42').scalar() == 42
    finally:
        scope.finish()
        thread.join(timeout=5)
        pooled.dispose()
