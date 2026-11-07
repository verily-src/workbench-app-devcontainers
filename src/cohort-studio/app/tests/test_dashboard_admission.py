import threading
import time
import asyncio
import json

import pandas as pd
import httpx
from fastapi.testclient import TestClient

import datasets
import execution
import live_query
import main
import query_cancellation


def test_dashboard_waits_for_busy_slot_and_returns_filtered_rows(engine, monkeypatch):
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE public.admission_extract AS SELECT n AS id, n %% 10 AS grp FROM generate_series(1, 1390000) AS n")
    gate = execution.AdmissionGate(1)
    monkeypatch.setitem(execution._gates, "interactive", gate)
    monkeypatch.setattr(live_query.db, "get_engine_for_resource", lambda _rid: engine)
    ds = datasets.open_dataset(pd.DataFrame({"id": [1], "grp": [1]}), "extract", live_source={
        "resource_id": "omopdb", "sql": "SELECT id, grp FROM public.admission_extract",
        "columns": {"id": "id", "grp": "grp"}})
    gate.acquire()
    result = []
    try:
        def request():
            with TestClient(main.app) as client:
                result.append(client.post(f"/api/datasets/{ds['dataset_id']}/query", json={
                    "filters": [{"column": "grp", "kind": "range", "min": 3, "max": 3}],
                    "charts": [], "page": 0, "page_size": 10}))
        thread = threading.Thread(target=request)
        thread.start()
        time.sleep(1.2)
        assert thread.is_alive(), "query was rejected instead of waiting"
        gate.release()
        thread.join(15)
        assert not thread.is_alive()
        assert result[0].status_code == 200, result[0].text
        assert result[0].json()["filtered"] == 139000
    finally:
        if gate.owners.get(None):
            gate.release()
        datasets.close_dataset(ds["dataset_id"])
        with engine.begin() as conn:
            conn.exec_driver_sql("DROP TABLE public.admission_extract")


def test_cancelled_waiter_does_not_consume_slot():
    gate = execution.AdmissionGate(1)
    scope = query_cancellation.Scope()
    gate.acquire()
    stopped = threading.Event()
    def wait():
        try:
            gate.acquire(timeout=30, check_cancel=scope.check)
        except query_cancellation.Cancelled:
            stopped.set()
    thread = threading.Thread(target=wait)
    thread.start()
    try:
        scope.cancel()
        assert stopped.wait(1)
        thread.join(1)
        assert not gate.waiters
        assert gate.active == 1
    finally:
        gate.release()


def test_disconnect_cancels_queued_dashboard_request(monkeypatch):
    gate = execution.AdmissionGate(1)
    monkeypatch.setitem(execution._gates, "interactive", gate)
    monkeypatch.setattr(main, "DISCONNECT_POLL_S", 0.05)
    ds = datasets.open_dataset(pd.DataFrame({"id": [1]}), "waiter")
    gate.acquire()
    disconnected = threading.Event()
    responses = []
    body = json.dumps({"filters": [], "charts": []}).encode()

    async def call_app():
        messages = [{"type": "http.request", "body": body, "more_body": False}]
        async def receive():
            if messages:
                return messages.pop(0)
            while not disconnected.is_set():
                await asyncio.sleep(0.01)
            return {"type": "http.disconnect"}
        async def send(message):
            responses.append(message)
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                 "method": "POST", "scheme": "http", "path": f"/api/datasets/{ds['dataset_id']}/query",
                 "raw_path": b"", "query_string": b"", "root_path": "",
                 "headers": [(b"content-type", b"application/json"),
                             (b"content-length", str(len(body)).encode())],
                 "client": ("127.0.0.1", 1), "server": ("127.0.0.1", 80)}
        await main.app(scope, receive, send)

    thread = threading.Thread(target=lambda: asyncio.run(call_app()))
    thread.start()
    try:
        deadline = time.monotonic() + 3
        while not gate.waiters and time.monotonic() < deadline:
            time.sleep(0.01)
        assert gate.waiters
        disconnected.set()
        thread.join(3)
        assert not thread.is_alive()
        assert not gate.waiters
        assert gate.active == 1
        assert next(m["status"] for m in responses if m["type"] == "http.response.start") == 499
    finally:
        disconnected.set()
        gate.release()
        thread.join(3)
        datasets.close_dataset(ds["dataset_id"])


def test_saturated_dashboard_queue_keeps_sync_endpoints_responsive(monkeypatch):
    gate = execution.AdmissionGate(1)
    monkeypatch.setitem(execution._gates, "interactive", gate)
    monkeypatch.setattr(execution, "INTERACTIVE_QUERY_MAX_WAITERS", 8)
    ds = datasets.open_dataset(pd.DataFrame({"id": [1]}), "queue")
    gate.acquire()
    async def exercise():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            tasks = [asyncio.create_task(client.post(f"/api/datasets/{ds['dataset_id']}/query", json={}))
                     for _ in range(8)]
            deadline = time.monotonic() + 5
            while len(gate.waiters) < 8 and time.monotonic() < deadline:
                await asyncio.sleep(0.01)
            assert len(gate.waiters) == 8
            started = time.monotonic()
            assert (await client.get("/api/health")).status_code == 200
            assert time.monotonic() - started < 2
            assert (await client.post(f"/api/datasets/{ds['dataset_id']}/query", json={})).status_code == 429
            gate.release()
            return [response.status_code for response in await asyncio.gather(*tasks)]
    try:
        assert asyncio.run(exercise()) == [200] * 8
    finally:
        if gate.owners.get(None):
            gate.release()
        datasets.close_dataset(ds["dataset_id"])
