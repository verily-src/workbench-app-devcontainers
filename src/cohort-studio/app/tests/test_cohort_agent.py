import json

import cohort_agent
import main
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


def test_endpoint_returns_result_and_records_turn(monkeypatch):
    monkeypatch.setattr(main, "_omop_cdm", lambda _rid: (object(), INFO))
    monkeypatch.setattr(cohort_agent, "chat", lambda *args, **kwargs: {
        "reply": "Proposed asthma cohort.", "spec": {"criteria": []},
        "count": None, "reason": "asthma", "provider": "openrouter",
        "model": "model", "usage": {"total_tokens": 9},
        "tool_calls": ["propose_cohort"]})
    recorded = []
    monkeypatch.setattr(main, "_record_turn", lambda *a, **k: recorded.append((a, k)))
    response = client.post("/api/omop/test-resource/cohort/agent", json={
        "message": "Build an asthma cohort",
        "history": [{"role": "user", "content": "Earlier"}],
        "spec": {"criteria": []}})
    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "Proposed asthma cohort."
    assert body["reason"] == "asthma"
    assert body["trace_id"]
    assert recorded[-1][1]["result"]["usage"]["total_tokens"] == 9


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
