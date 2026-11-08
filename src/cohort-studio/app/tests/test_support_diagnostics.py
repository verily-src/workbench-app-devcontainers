import hashlib

from fastapi.testclient import TestClient

import main
import operational_store


def test_diagnostics_are_bounded_allowlisted_and_session_scoped(tmp_path, monkeypatch):
    store = operational_store.Store(tmp_path / "metrics.sqlite")
    monkeypatch.setattr(operational_store, "_instance", store)
    monkeypatch.setenv("STUDIO_SUPPORT_EMAIL", "help@example.com")
    own_cookie, other_cookie = "a" * 64, "b" * 64
    own = hashlib.sha256(own_cookie.encode()).hexdigest()
    other = hashlib.sha256(other_cookie.encode()).hexdigest()
    try:
        for _ in range(205):
            store.record(own, {"event": "http.finished", "trace_id": "a" * 32,
                               "method": "GET", "route": "/api/performance", "status": 200,
                               "elapsed_ms": 12, "sql": "secret sql", "filters": "patient"})
        store.record(other, {"event": "http.finished", "trace_id": "b" * 32,
                             "method": "POST", "route": "/api/performance", "status": 500})
        store.queue.join()
        client = TestClient(main.app)
        client.cookies.set("studio_chat_owner", own_cookie)
        response = client.get("/api/support/diagnostics")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        report = response.json()
        assert report["recipient"] == "help@example.com"
        assert len(report["events"]) == 200
        assert all(event["trace_id"] == "a" * 32 for event in report["events"])
        assert all(event["route"] == "/api/performance" for event in report["events"])
        assert "secret" not in response.text and "patient" not in response.text
        client.cookies.set("studio_chat_owner", other_cookie)
        other_report = client.get("/api/support/diagnostics").json()
        assert any(event.get("trace_id") == "b" * 32 for event in other_report["events"])
        assert all(event.get("trace_id") != "a" * 32 for event in other_report["events"])
    finally:
        store.shutdown()
