"""Dashboard queries stop in PostgreSQL when the browser disconnects."""
import asyncio
import json
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

    def sleeping():
        with engine.connect() as conn:
            return conn.exec_driver_sql(
                "SELECT count(*) FROM pg_stat_activity WHERE state = 'active' "
                f"AND query LIKE '%%CROSS JOIN public.\"{name}\"%%' AND pid <> pg_backend_pid()").scalar()

    body = json.dumps({"filters": [], "charts": [], "page": 0, "page_size": 10,
                       "refresh": True}).encode()
    try:
        started = time.monotonic()
        sent = []

        async def call_app():
            # Full ASGI path through every installed middleware.
            messages = [{"type": "http.request", "body": body, "more_body": False}]

            async def receive():
                if messages:
                    return messages.pop(0)
                while not gone.is_set():
                    await asyncio.sleep(0.02)
                return {"type": "http.disconnect"}

            async def send(message):
                sent.append(message)
            scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                     "method": "POST", "scheme": "http", "path": f"/api/datasets/{ds['dataset_id']}/query",
                     "raw_path": b"", "query_string": b"", "root_path": "",
                     "headers": [(b"content-type", b"application/json"),
                                 (b"content-length", str(len(body)).encode())],
                     "client": ("127.0.0.1", 1), "server": ("127.0.0.1", 80)}
            await main.app(scope, receive, send)

        thread = threading.Thread(target=lambda: asyncio.run(call_app()))
        thread.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not sleeping():
            time.sleep(0.05)
        assert sleeping(), f"query never started: {sent!r}"
        gone.set()
        thread.join(8)
        assert not thread.is_alive()
        assert time.monotonic() - started < 8          # far less than the full count
        status = next(m["status"] for m in sent if m["type"] == "http.response.start")
        assert status == 499, sent
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and sleeping():
            time.sleep(0.05)
        assert not sleeping(), "PostgreSQL statement kept running"
    finally:
        datasets.close_dataset(ds["dataset_id"])
        with engine.begin() as conn:
            conn.exec_driver_sql(f'DROP TABLE public."{name}"')
