import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import agent_stream
import config
import main
import providers
import agent_store as store_module
from tests.test_agent_store import agent_store


@pytest.fixture
def workspace(agent_store, monkeypatch):
    monkeypatch.setattr(store_module, "AgentStore", lambda: agent_store)
    monkeypatch.setattr(config, "get_llm_config", lambda: {
        "provider": "openai", "model": "test", "api_key": "test", "base_url": None})
    client = TestClient(main.app)
    assert client.get("/api/agent/chat/history").status_code == 200
    return client


def events(response):
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/x-ndjson")
    return [json.loads(line) for line in response.text.splitlines()]


def test_stream_progress_result_and_history_survive_slow_consumer(workspace, agent_store, monkeypatch):
    def provider(*_args, on_step, **_kwargs):
        for turn in range(400):
            on_step({"type": "model_start", "turn": turn})
        return {"reply": "Complete result.", "usage": {}, "tool_calls": []}
    monkeypatch.setattr(providers, "run", provider)
    output = events(workspace.post("/api/agent/chat/stream", json={"message": "Inspect sources"}))
    assert output[0]["type"] == "started"
    assert any(e["type"] == "progress" and e["stage"] == "model_start" for e in output)
    result = next(e["result"] for e in output if e["type"] == "result")
    assert result["reply"] == "Complete result." and result["run_status"] == "completed"
    assert output[-1] == {"type": "end"}
    history = workspace.get("/api/agent/chat/history").json()
    assert history["session_id"] == result["session_id"]
    assert history["messages"][-1]["content"] == result["reply"]
    assert output[0]["run_id"] not in agent_stream._active


def test_owner_cancel_stops_later_steps_and_persists_reason(workspace, agent_store, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []
    def provider(*_args, on_step, **_kwargs):
        on_step({"type": "tool_start", "turn": 1, "tool_name": "list_sources"})
        entered.set()
        assert release.wait(10)
        on_step({"type": "tool_end", "turn": 1, "tool_name": "list_sources"})
        calls.append("later_tool")
        return {"reply": "Should not complete", "usage": {}}
    monkeypatch.setattr(providers, "run", provider)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(workspace.post, "/api/agent/chat/stream", json={"message": "Inspect"})
        try:
            assert entered.wait(10)
            with agent_stream._lock:
                run_id = next(iter(agent_stream._active))
            outsider = TestClient(main.app)
            assert outsider.post(f"/api/agent/chat/runs/{run_id}/cancel").status_code == 404
            assert not agent_stream._active[run_id]["cancel"].is_set()
            assert workspace.post(f"/api/agent/chat/runs/{run_id}/cancel").json() == {"status": "cancelling"}
        finally:
            release.set()
        output = events(future.result(timeout=10))
    assert calls == []
    assert not any(e["type"] == "result" for e in output)
    cancelled = next(e for e in output if e["type"] == "cancelled")
    assert cancelled["session_id"] and output[-1]["type"] == "end"
    history = workspace.get("/api/agent/chat/history").json()
    assert "Stopped by request" in history["messages"][-1]["content"]
    with agent_store.engine.connect() as conn:
        assert conn.execute(text("SELECT status, error_class FROM _studio_agent.runs")).one() == ("failed", "AgentCancelled")
    assert workspace.post(f"/api/agent/chat/runs/{run_id}/cancel").status_code == 404
    assert run_id not in agent_stream._active


@pytest.mark.parametrize("message, expected", [
    ("credit balance is too low: secret-key", "billing and quota"),
    ("unknown error secret-key", "Check provider settings"),
])
def test_stream_provider_error_is_actionable_and_redacted(workspace, monkeypatch, message, expected):
    def provider(*_args, **_kwargs):
        raise RuntimeError(message)
    monkeypatch.setattr(providers, "run", provider)
    output = events(workspace.post("/api/agent/chat/stream", json={"message": "Inspect"}))
    error = next(e for e in output if e["type"] == "error")
    assert expected in error["message"]
    assert "secret-key" not in json.dumps(output)
    assert output[-1] == {"type": "end"}


def test_real_http_disconnect_stops_next_step_and_records_cancellation(workspace, agent_store, monkeypatch):
    import socket
    import time
    import httpx
    import uvicorn

    entered, release = threading.Event(), threading.Event()
    later = []
    def provider(*_args, on_step, **_kwargs):
        on_step({"type": "model_start", "turn": 1})
        entered.set()
        assert release.wait(10)
        on_step({"type": "model_end", "turn": 1})
        later.append("tool")
        return {"reply": "Unexpected", "usage": {}}
    monkeypatch.setattr(providers, "run", provider)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(main.app, log_level="error", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(.01)
        assert server.started
        with httpx.Client(base_url=f"http://127.0.0.1:{port}") as client:
            with client.stream("POST", "/api/agent/chat/stream", json={"message": "Inspect"}) as response:
                assert response.status_code == 200
                lines = response.iter_lines()
                started = json.loads(next(lines))
                assert started["type"] == "started"
                assert entered.wait(10)
            deadline = time.monotonic() + 5
            while not agent_stream._active[started["run_id"]]["cancel"].is_set() and time.monotonic() < deadline:
                time.sleep(.01)
            assert agent_stream._active[started["run_id"]]["cancel"].is_set()
            release.set()
            deadline = time.monotonic() + 5
            while started["run_id"] in agent_stream._active and time.monotonic() < deadline:
                time.sleep(.01)
            assert started["run_id"] not in agent_stream._active
        assert later == []
        with agent_store.engine.connect() as conn:
            assert conn.execute(text("SELECT status, error_class FROM _studio_agent.runs")).one() == ("failed", "AgentCancelled")
    finally:
        release.set()
        server.should_exit = True
        thread.join(10)
        listener.close()
