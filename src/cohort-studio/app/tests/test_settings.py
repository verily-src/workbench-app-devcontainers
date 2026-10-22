from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import config
import llm
import main

FIXTURE = Path(__file__).parent / "fixtures" / "samples.csv"
client = TestClient(main.app)


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "cfg.json")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("VERTEXAI_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)
    monkeypatch.delenv("VERTEXAI_LOCATION", raising=False)


def test_config_defaults():
    body = client.get("/api/config").json()
    assert body["llm"]["model"] == "claude-opus-5"
    assert body["llm"]["api_key_set"] is False
    assert body["mcp"]["available"] is True
    assert body["mcp"]["path"] == "/mcp"


def test_config_update_never_echoes_key():
    resp = client.put("/api/config", json={
        "model": "claude-sonnet-5", "api_key": "sk-ant-secret-key-1234"})
    body = resp.json()
    assert body["llm"]["model"] == "claude-sonnet-5"
    assert body["llm"]["api_key_set"] is True
    assert body["llm"]["api_key_hint"] == "…1234"
    assert "sk-ant" not in resp.text


def test_chart_palette_roundtrips():
    body = client.get("/api/config").json()
    assert body["chart_palette"] == "verily"
    updated = client.put("/api/config", json={"chart_palette": "indigo"}).json()
    assert updated["chart_palette"] == "indigo"

    reset = client.put("/api/config", json={"chart_palette": "bogus"}).json()
    assert reset["chart_palette"] == "verily"


def test_mcp_mounted():
    assert any(str(getattr(r, "path", "")) == "/mcp"
               for r in main.app.routes)


def _open_fixture() -> str:
    with open(FIXTURE, "rb") as f:
        resp = client.post("/api/datasets/upload",
                           files={"file": ("samples.csv", f, "text/csv")})
    return resp.json()["dataset_id"]


def test_ask_unconfigured_is_400():
    dataset_id = _open_fixture()
    resp = client.post(f"/api/datasets/{dataset_id}/ask",
                       json={"question": "liver only"})
    assert resp.status_code == 400
    assert "Settings" in resp.json()["detail"]


def test_ask_applies_suggested_filters(monkeypatch):
    def fake_suggest(question, columns, current):
        assert question == "liver samples with high RIN"
        names = {c["name"] for c in columns}
        assert {"tissue", "rin_score"} <= names
        return {"filters": [
            {"column": "tissue", "kind": "categorical", "values": ["liver"]},
            {"column": "rin_score", "kind": "range", "min": 7.0, "max": 10.0},
        ], "explanation": "Filtered to liver with RIN ≥ 7."}

    monkeypatch.setattr(llm, "suggest_filters", fake_suggest)
    dataset_id = _open_fixture()
    resp = client.post(f"/api/datasets/{dataset_id}/ask",
                       json={"question": "liver samples with high RIN"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["filters"]) == 2
    assert body["explanation"].startswith("Filtered")


    out = client.post(f"/api/datasets/{dataset_id}/query",
                      json={"filters": body["filters"], "charts": []}).json()
    assert 0 < out["filtered"] < out["total"]


def test_config_defaults_expose_providers():
    body = client.get("/api/config").json()
    assert body["llm"]["provider"] == "anthropic"
    assert set(body["llm"]["providers"]) == {
        "anthropic", "openai", "gemini", "openrouter", "bedrock",
        "vertexai"}
    assert body["llm"]["providers"]["anthropic"]["model"] == "claude-opus-5"

    assert body["llm"]["providers"]["openai"]["model"] == ""
    assert body["llm"]["providers"]["openrouter"]["model"] == ""


def test_openrouter_settings_and_environment_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-env-1234")
    resp = client.put("/api/config", json={
        "provider": "openrouter", "model": "provider/model",
        "api_key": "sk-or-saved-5678"})
    assert resp.status_code == 200
    assert "sk-or-" not in resp.text
    body = resp.json()
    assert body["llm"]["provider"] == "openrouter"
    assert body["llm"]["providers"]["openrouter"]["model"] == "provider/model"
    assert body["llm"]["providers"]["openrouter"]["api_key_source"] == "environment"
    assert body["llm"]["providers"]["openrouter"]["api_key_hint"] == "…1234"
    assert config.get_llm_config() == {
        "provider": "openrouter", "api_key": "sk-or-env-1234",
        "model": "provider/model", "base_url": "https://openrouter.ai/api/v1",
        "region": None}


def test_bedrock_settings_use_iam_region_and_never_store_api_key(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    resp = client.put("/api/config", json={
        "provider": "bedrock", "model": "configured-model",
        "api_key": "must-not-be-saved"})
    assert resp.status_code == 200
    assert "must-not-be-saved" not in resp.text
    body = resp.json()
    state = body["llm"]["providers"]["bedrock"]
    assert body["llm"]["provider"] == "bedrock"
    assert state["model"] == "configured-model"
    assert state["auth_method"] == "iam"
    assert state["region"] == "us-east-1"
    assert state["api_key_set"] is False
    assert config.get_llm_config() == {
        "provider": "bedrock", "api_key": None,
        "model": "configured-model", "base_url": None,
        "region": "us-east-1"}


def test_bedrock_test_connection_reports_missing_region_and_model(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "")
    client.put("/api/config", json={"provider": "bedrock", "model": "model-id"})
    no_region = client.post("/api/config/llm/test")
    assert no_region.status_code == 400
    assert "AWS region is required" in no_region.json()["detail"]

    monkeypatch.setenv("AWS_REGION", "us-east-1")
    client.put("/api/config", json={"provider": "bedrock", "model": ""})
    no_model = client.post("/api/config/llm/test")
    assert no_model.status_code == 400
    assert "No Amazon Bedrock model set" in no_model.json()["detail"]


def test_vertexai_config_uses_adc_env_and_never_stores_api_key(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "studio-project")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    monkeypatch.setenv("VERTEXAI_PROJECT", "lower-priority-project")
    monkeypatch.setenv("VERTEXAI_LOCATION", "global")
    resp = client.put("/api/config", json={
        "provider": "vertexai", "model": "google/gemini-model",
        "api_key": "must-not-be-saved"})
    assert resp.status_code == 200
    assert "must-not-be-saved" not in resp.text
    body = resp.json()
    state = body["llm"]["providers"]["vertexai"]
    assert body["llm"]["provider"] == "vertexai"
    assert state["model"] == "google/gemini-model"
    assert state["auth_method"] == "adc"
    assert state["api_key_set"] is False
    assert state["project"] == "studio-project"
    assert state["location"] == "us-central1"
    assert state["configured"] is True
    assert config.get_llm_config() == {
        "provider": "vertexai", "api_key": None,
        "model": "google/gemini-model", "base_url": None,
        "region": None, "project": "studio-project",
        "location": "us-central1"}


def test_vertexai_test_connection_reports_missing_project_location_model(
        monkeypatch):
    client.put("/api/config", json={"provider": "vertexai", "model": "model-id"})
    no_project = client.post("/api/config/llm/test")
    assert no_project.status_code == 400
    assert "GOOGLE_CLOUD_PROJECT" in no_project.json()["detail"]

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "studio-project")
    no_location = client.post("/api/config/llm/test")
    assert no_location.status_code == 400
    assert "GOOGLE_CLOUD_LOCATION" in no_location.json()["detail"]

    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    client.put("/api/config", json={"provider": "vertexai", "model": ""})
    no_model = client.post("/api/config/llm/test")
    assert no_model.status_code == 400
    assert "No Google Vertex AI model set" in no_model.json()["detail"]


def test_switch_provider_keeps_per_provider_keys_and_never_echoes():

    client.put("/api/config", json={
        "provider": "anthropic", "api_key": "sk-ant-aaaa1111"})
    resp = client.put("/api/config", json={
        "provider": "openai", "model": "some-openai-model",
        "api_key": "sk-openai-bbbb2222"})
    body = resp.json()
    assert "sk-ant" not in resp.text and "sk-openai" not in resp.text
    assert body["llm"]["provider"] == "openai"
    assert body["llm"]["model"] == "some-openai-model"
    provs = body["llm"]["providers"]

    assert provs["anthropic"]["api_key_set"] is True
    assert provs["anthropic"]["api_key_hint"] == "…1111"
    assert provs["openai"]["api_key_set"] is True
    assert provs["openai"]["api_key_hint"] == "…2222"


def test_agent_turn_recorded(monkeypatch, tmp_path):

    import agent
    monkeypatch.setattr(main, "_lineage_engine",
                        lambda: _file_engine(tmp_path))

    def fake_chat(dataset_id, message, history, filters, charts):
        return {"reply": "ok", "filters": filters, "charts": charts,
                "actions": [], "provider": "openai", "model": "m-1",
                "usage": {"prompt_tokens": 10, "completion_tokens": 5,
                          "total_tokens": 15},
                "tool_calls": ["run_query", "add_chart"]}

    monkeypatch.setattr(agent, "chat", fake_chat)
    dataset_id = _open_fixture()
    resp = client.post(f"/api/datasets/{dataset_id}/chat",
                       json={"message": "plot it"})
    assert resp.status_code == 200
    assert resp.json()["trace_id"]
    turns = client.get("/api/agent/turns").json()["turns"]
    assert turns and turns[0]["provider"] == "openai"
    assert turns[0]["total_tokens"] == 15
    assert turns[0]["status"] == "ok"


def _file_engine(tmp_path):
    from sqlalchemy import create_engine
    return create_engine(f"sqlite:///{tmp_path / 'turns.db'}",
                         connect_args={"check_same_thread": False})
