"""Dashboard queries stop in PostgreSQL when the browser disconnects."""
import asyncio
import threading
import time
import uuid

import pytest

import datasets
import live_query
import main


def test_disconnect_cancels_running_dashboard_query(engine, monkeypatch):
    name = f"slow_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE TABLE public."{name}" (id int)')
        conn.exec_driver_sql(f'INSERT INTO public."{name}" SELECT g FROM generate_series(1, 20000) g')
    monkeypatch.setattr(live_query.db, "get_engine_for_resource", lambda _rid: engine)
    monkeypatch.setattr(main, "DISCONNECT_POLL_S", 0.05)
    import pandas as pd
    ds = datasets.open_dataset(pd.DataFrame({"id": [1, 2], "slow": [1, 1]}), "slow", live_source={
        "resource_id": "slow", "params": {},
        # Counting a 400M-row cross join keeps the summary query busy for a long time.
        "sql": f'SELECT a.id AS id, b.id AS slow FROM public."{name}" AS a '
               f'CROSS JOIN public."{name}" AS b',
        "columns": {"id": "id", "slow": "slow"}})
    gone = threading.Event()

    class Request:
        async def is_disconnected(self):
            return gone.is_set()

    def sleeping():
        with engine.connect() as conn:
            return conn.exec_driver_sql(
                "SELECT count(*) FROM pg_stat_activity WHERE state = 'active' "
                f"AND query LIKE '%%CROSS JOIN public.\"{name}\"%%' AND pid <> pg_backend_pid()").scalar()
    try:
        req = main.QueryRequest(filters=[], charts=[], page=0, page_size=10, refresh=True)
        started = time.monotonic()
        result = {}

        def run():
            try:
                asyncio.run(main.query_dataset(ds["dataset_id"], req, Request()))
            except Exception as exc:
                result["error"] = exc
        thread = threading.Thread(target=run)
        thread.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not sleeping():
            time.sleep(0.05)
        assert sleeping(), f"query never started: {result!r}"
        gone.set()
        thread.join(8)
        assert not thread.is_alive()
        assert time.monotonic() - started < 8          # far less than the full count
        assert getattr(result.get("error"), "status_code", None) == 499
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and sleeping():
            time.sleep(0.05)
        assert not sleeping(), "PostgreSQL statement kept running"
    finally:
        datasets.close_dataset(ds["dataset_id"])
        with engine.begin() as conn:
            conn.exec_driver_sql(f'DROP TABLE public."{name}"')
