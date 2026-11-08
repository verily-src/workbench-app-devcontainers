import hashlib
import json
import socketserver
import threading
from email import policy
from email.parser import BytesParser

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
        assert "recipient" not in report
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


def test_report_sends_session_diagnostics_to_smtp(tmp_path, monkeypatch):
    received = []

    class SMTP(socketserver.StreamRequestHandler):
        def handle(self):
            self.wfile.write(b"220 test\r\n")
            while line := self.rfile.readline():
                command = line.split(None, 1)[0].upper()
                if command in (b"EHLO", b"HELO"):
                    self.wfile.write(b"250 test\r\n")
                elif command in (b"MAIL", b"RCPT", b"RSET"):
                    self.wfile.write(b"250 OK\r\n")
                elif command == b"DATA":
                    self.wfile.write(b"354 Send data\r\n")
                    parts = []
                    while (part := self.rfile.readline()) != b".\r\n":
                        parts.append(part)
                    received.append(b"".join(parts))
                    self.wfile.write(b"250 Accepted\r\n")
                elif command == b"QUIT":
                    self.wfile.write(b"221 Bye\r\n")
                    return

    store = operational_store.Store(tmp_path / "metrics.sqlite")
    monkeypatch.setattr(operational_store, "_instance", store)
    owner = hashlib.sha256(("a" * 64).encode()).hexdigest()
    store.record(owner, {"event": "http.finished", "trace_id": "a" * 32, "status": 500})
    store.queue.join()
    server = socketserver.TCPServer(("127.0.0.1", 0), SMTP)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("STUDIO_SUPPORT_SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("STUDIO_SUPPORT_SMTP_PORT", str(server.server_address[1]))
    monkeypatch.setenv("STUDIO_SUPPORT_SMTP_SECURITY", "plain")
    monkeypatch.setenv("STUDIO_SUPPORT_FROM", "cohort@example.com")
    monkeypatch.setenv("STUDIO_SUPPORT_EMAIL", "help@example.com")
    try:
        client = TestClient(main.app)
        client.cookies.set("studio_chat_owner", "a" * 64)
        response = client.post("/api/support/report", json={"details": "Chart failed"})
        assert response.status_code == 200 and response.json() == {"sent": True}
        assert "help@example.com" not in response.text
        msg = BytesParser(policy=policy.default).parsebytes(received[0])
        assert msg["To"] == "help@example.com"
        assert "Chart failed" in msg.get_body(preferencelist=("plain",)).get_content()
        attachment = list(msg.iter_attachments())[0]
        assert attachment.get_filename() == "cohort-browser-diagnostics.json"
        report = json.loads(attachment.get_content())
        assert any(event.get("trace_id") == "a" * 32 for event in report["events"])
        assert "recipient" not in report
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        store.shutdown()


def test_report_failure_when_mail_is_unconfigured(monkeypatch):
    monkeypatch.delenv("STUDIO_SUPPORT_SMTP_HOST", raising=False)
    response = TestClient(main.app).post("/api/support/report", json={"details": "A problem"})
    assert response.status_code == 503
    assert response.json()["detail"] == "Issue reporting is not configured."
