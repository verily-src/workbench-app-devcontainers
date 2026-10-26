import json

import cohort_agent
import main
from tests.test_agent_store import agent_store
from fastapi.testclient import TestClient

INFO = {"version": "5.4", "cdm_schema": "cdm", "vocab_schema": "vocab"}
client = TestClient(main.app)


def test_endpoint_rejects_invalid_spec_with_400(monkeypatch):
    import config

    monkeypatch.setattr(main, "_omop_cdm", lambda _rid: (object(), INFO))
    monkeypatch.setattr(config, "get_llm_config", lambda: {
        "provider": "openrouter", "api_key": "key", "model": "model"})
    response = client.post("/api/omop/test-resource/cohort/agent", json={
        "message": "Build a cohort", "spec": {"unexpected": True}})
    assert response.status_code == 400
    assert "Unknown cohort spec key" in json.dumps(response.json()["detail"])


def test_endpoint_reports_missing_config_with_400(monkeypatch):
    import config

    monkeypatch.setattr(main, "_omop_cdm", lambda _rid: (object(), INFO))
    monkeypatch.setattr(config, "get_llm_config", lambda: {
        "provider": "openrouter", "api_key": None, "model": "model"})
    response = client.post("/api/omop/test-resource/cohort/agent", json={
        "message": "Build a cohort"})
    assert response.status_code == 400
    assert "No OpenRouter API key" in response.json()["detail"]


def test_endpoint_returns_result_and_preserves_conversation(monkeypatch, agent_store):
    import agent_store as storage
    import config
    import providers
    monkeypatch.setattr(storage, "AgentStore", lambda: agent_store)
    monkeypatch.setattr(main, "_omop_cdm", lambda _rid: (object(), INFO))
    monkeypatch.setattr(config, "get_llm_config", lambda: {
        "provider": "openrouter", "api_key": "test-key", "model": "test", "base_url": None})
    monkeypatch.setattr(providers, "run", lambda *args, **kwargs: {
        "reply": "Which clinical events should define the cohort?",
        "usage": {"prompt_tokens": 5, "completion_tokens": 4}, "tool_calls": []})
    local = TestClient(main.app)
    response = local.post("/api/omop/test-resource/cohort/agent", json={
        "message": "Build a cohort", "spec": {"criteria": []}})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["session_id"]
    assert body["spec"] is None
    history = local.get("/api/omop/test-resource/cohort/agent/history").json()
    assert history["session_id"] == body["session_id"]
    assert history["messages"][-1]["content"] == body["reply"]


def test_omop_request_validation_is_strict_and_returns_400():
    cases = [
        ("/api/omop/test-resource/cohort/count", {"require_observation": "false"}),
        ("/api/omop/test-resource/cohort/open",
         {"spec": {}, "name": "", "unexpected": True}),
        ("/api/omop/test-resource/domain/open",
         {"table": "person", "concept_names": "false"}),
        ("/api/omop/test-resource/cohort/agent", {"message": "   "}),
        ("/api/omop/test-resource/cohort/agent",
         {"message": "Build", "unexpected": True}),
    ]
    for path, body in cases:
        response = client.post(path, json=body)
        assert response.status_code == 400, (path, response.text)


def test_non_omop_request_validation_remains_422():
    response = client.post("/api/datasets/unknown/chat", json={})
    assert response.status_code == 422


def test_omop_nonfinite_validation_returns_json_400():
    response = TestClient(main.app).post(
        "/api/omop/example/cohort/count",
        content='{"demographics":{"age_min":NaN}}',
        headers={"content-type": "application/json"})
    assert response.status_code == 400
    assert "finite" in response.json()["detail"][0]["msg"]
