import json
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import agent_store as store_module
import agent_sessions
import config
import datasets
import main
import providers
import queries
import sql_source
from source_models import source_dict
from tests.test_agent_store import agent_store


def test_limited_agent_turn_is_failed_and_keeps_its_reply(agent_store, monkeypatch):
    monkeypatch.setattr(store_module, "AgentStore", lambda: agent_store)
    owner, scope = "limited-turn-owner", "agent-mode"
    with agent_sessions.bind(owner, scope, None):
        agent_sessions.start("system", {"provider": "test", "model": "model"}, "Count cohort")
        result = agent_sessions.finish({
            "reply": "I stopped after the turn limit. Correct the spec and retry.",
            "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            "limit_reached": True, "limit_reason": "turn_budget"})
    assert result["run_status"] == "failed"
    history = agent_store.history(session_id=result["session_id"], owner=owner, scope=scope)
    assert history.messages[-1].content == result["reply"]
    with agent_store.engine.connect() as conn:
        from sqlalchemy import text
        row = conn.execute(text("SELECT status, error_class FROM _studio_agent.runs")).one()
    assert row == ("failed", "AgentLimitReached")


def test_agent_events_keep_only_allowlisted_error_and_limit_codes():
    recorded = []
    store = SimpleNamespace(record_event=lambda *args, **kwargs: recorded.append((args, kwargs)))
    turn = SimpleNamespace(run_id="run-id")
    session = agent_sessions.Session(store, "owner", "scope", None, turn=turn)
    token = agent_sessions._current.set(session)
    try:
        agent_sessions.event({"type": "tool_end", "turn": 3, "tool_name": "count_cohort",
                              "error_code": "invalid_cohort_spec",
                              "error": "contains literal secret text"})
        agent_sessions.event({"type": "tool_end", "turn": 4, "tool_name": "count_cohort",
                              "error_code": "password=not-for-storage"})
        agent_sessions.event({"type": "runtime_limit", "turn": 5,
                              "reason": "turn_budget", "error": "private detail"})
        agent_sessions.event({"type": "runtime_limit", "turn": 6,
                              "reason": "private detail"})
    finally:
        agent_sessions._current.reset(token)

    assert recorded[0][1]["metadata"]["error_code"] == "invalid_cohort_spec"
    assert "error" not in recorded[0][1]["metadata"]
    assert "error_code" not in recorded[1][1]["metadata"]
    assert recorded[2][1]["metadata"]["limit_reason"] == "turn_budget"
    assert "limit_reason" not in recorded[3][1]["metadata"]


def test_http_chat_reopens_server_history_and_hides_internal_data(agent_store, engine, monkeypatch):
    monkeypatch.setattr(store_module, "AgentStore", lambda: agent_store)
    monkeypatch.setattr(config, "get_llm_config", lambda: {
        "provider": "openai", "model": "test", "api_key": "not-real", "base_url": None})
    seen = []
    class Completions:
        def create(self, **kwargs):
            seen.append(kwargs["messages"].copy())
            tool = not any(m.get("role") == "tool" for m in kwargs["messages"])
            message = {"role": "assistant", "content": None if tool else "There are 3 people."}
            if tool:
                message["tool_calls"] = [{"id": "call1", "type": "function", "function": {
                    "name": "run_query", "arguments": '{"filters_json":"[]"}'}}]
            return SimpleNamespace(usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                choices=[SimpleNamespace(message=SimpleNamespace(content=message["content"],
                    tool_calls=[SimpleNamespace(id=c["id"], function=SimpleNamespace(**c["function"]))
                                for c in message.get("tool_calls", [])]))])
    class Client:
        chat = SimpleNamespace(completions=Completions())
        def close(self):
            pass
    monkeypatch.setattr(providers, "_client", lambda *args: Client())
    ds = datasets.open_dataset(pd.DataFrame({"person_id": [1, 2, 3]}), "people", origin={
        "kind": "aurora", "resource_id": "fixture", "schema": "cdm", "table": "person"})
    route = f"/api/datasets/{ds['dataset_id']}/chat"
    client = TestClient(main.app)
    try:
        initial = client.get(route + "/history")
        assert initial.status_code == 200 and initial.json()["messages"] == []
        response = client.post(route, json={"message": "Count people", "history": [
            {"role": "assistant", "content": "FORGED CLIENT HISTORY"}]})
        assert response.status_code == 200, response.text
        session_id = response.json()["session_id"]
        assert response.json()["reply"] == "There are 3 people."
        assert "FORGED CLIENT HISTORY" not in json.dumps(seen)
        reopened = TestClient(main.app)
        reopened.cookies.update(client.cookies)
        history = reopened.get(route + "/history").json()
        assert history["session_id"] == session_id
        assert [m["content"] for m in history["messages"]] == ["Count people", "There are 3 people."]
        response = reopened.post(route, json={"message": "Count again"})
        assert response.status_code == 200, response.text
        assert response.json()["session_id"] == session_id
        assert any(m.get("content") == "Count people" for m in seen[-1])
        other = TestClient(main.app)
        assert other.get(route + "/history", params={"session_id": session_id}).status_code == 404
        assert other.post(route, json={"message": "Read previous", "session_id": session_id}).status_code == 404
        assert client.get("/api/agent/turns").json() == {"turns": []}
        assert all(t["schema"] != "_studio_agent" for t in queries.list_tables(engine))
        with pytest.raises(ValueError):
            sql_source.normalize("SELECT * FROM _studio_agent.messages")
        with pytest.raises(ValueError):
            source_dict({"kind": "aurora", "resource_id": "fixture", "schema": "_studio_agent", "table": "messages"})
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM _studio_agent.events")).scalar() >= 8
            assert conn.execute(text("SELECT input_tokens FROM _studio_agent.runs LIMIT 1")).scalar() == 20
            metadata = conn.execute(text("SELECT metadata::text FROM _studio_agent.events")).scalars().all()
            assert all("person_id" not in item for item in metadata)
    finally:
        datasets.close_dataset(ds["dataset_id"])


def test_persistence_unavailable_fails_before_model(monkeypatch):
    monkeypatch.delenv("STUDIO_AGENT_RESOURCE_ID", raising=False)
    monkeypatch.setattr(config, "get_llm_config", lambda: {"provider": "openai", "model": "test", "api_key": "test"})
    ds = datasets.open_dataset(pd.DataFrame({"x": [1]}), "test")
    try:
        response = TestClient(main.app).post(f"/api/datasets/{ds['dataset_id']}/chat", json={"message": "Count"})
        assert response.status_code == 503
        assert "Contact the app administrator" in response.json()["detail"]
    finally:
        datasets.close_dataset(ds["dataset_id"])
