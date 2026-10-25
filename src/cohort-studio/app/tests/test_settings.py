from pathlib import Path
import json
from concurrent.futures import ThreadPoolExecutor
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient
from botocore.exceptions import ClientError

import config
import llm
import main
import secret_store

FIXTURE = Path(__file__).parent / "fixtures" / "samples.csv"
client = TestClient(main.app)


class MemorySecrets:
    def __init__(self):
        self.value = None
        self.kms_key = None

    def _missing(self, operation):
        raise ClientError({"Error": {"Code": "ResourceNotFoundException"}}, operation)

    def get_secret_value(self, SecretId):
        if self.value is None:
            self._missing("GetSecretValue")
        return {"SecretString": self.value}

    def describe_secret(self, SecretId):
        if self.value is None:
            self._missing("DescribeSecret")
        return {"KmsKeyId": self.kms_key}

    def create_secret(self, Name, SecretString, KmsKeyId):
        if self.value is not None:
            raise ClientError({"Error": {"Code": "ResourceExistsException"}},
                              "CreateSecret")
        self.value, self.kms_key = SecretString, KmsKeyId
        return {"Name": Name}

    def put_secret_value(self, SecretId, SecretString):
        self.value = SecretString
        return {"ARN": SecretId}


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "cfg.json")
    monkeypatch.setenv("STUDIO_LOCAL_SECRET_DIR", str(tmp_path / "secure-keys"))
    memory = MemorySecrets()
    monkeypatch.setattr(secret_store, "_client", lambda _settings: memory)
    monkeypatch.setenv("STUDIO_LLM_SECRET_ID", "cohort-studio/test/llm")
    monkeypatch.setenv("STUDIO_LLM_KMS_KEY_ID",
                       "arn:aws:kms:us-east-1:123456789012:key/"
                       "12345678-1234-1234-1234-123456789012")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("VERTEXAI_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)
    monkeypatch.delenv("VERTEXAI_LOCATION", raising=False)
    monkeypatch.delenv("STUDIO_OPENWEIGHT_BASE_URL", raising=False)
    monkeypatch.delenv("STUDIO_OPENWEIGHT_MODEL", raising=False)
    monkeypatch.delenv("STUDIO_OPENWEIGHT_API_KEY", raising=False)
    monkeypatch.setenv("AWS_REGION", "us-east-1")


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
    assert "sk-ant" not in resp.text
    assert body["llm"]["api_key_source"] == "secret_manager"
    assert "api_key_hint" not in body["llm"]
    assert "sk-ant-secret-key-1234" not in config.CONFIG_PATH.read_text()


def test_jev_token_api_saves_only_to_secret_store_and_can_remove():
    token = "test-only-jev-token-not-for-live-use"
    saved = client.put("/api/config", json={
        "jev_api_key": token, "jev_model": "ranker-v1"})
    assert saved.status_code == 200
    assert token not in saved.text
    assert secret_store.read_keys()["jev"] == token
    assert token not in config.CONFIG_PATH.read_text()
    assert saved.json()["jev"]["api_key_set"] is True
    assert saved.json()["jev"]["model"] == "ranker-v1"

    removed = client.put("/api/config", json={"jev_api_key": ""})
    assert removed.status_code == 200
    assert token not in removed.text
    assert "jev" not in secret_store.read_keys()
    assert removed.json()["jev"]["api_key_set"] is False


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
        "vertexai", "openweight"}
    assert body["llm"]["providers"]["anthropic"]["model"] == "claude-opus-5"

    assert body["llm"]["providers"]["openai"]["model"] == ""
    assert body["llm"]["providers"]["openrouter"]["model"] == ""
    assert body["llm"]["providers"]["openweight"]["model"] == ""


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
    assert config.get_llm_config() == {
        "provider": "openrouter", "api_key": "sk-or-env-1234",
        "model": "provider/model", "base_url": "https://openrouter.ai/api/v1",
        "region": None}


def test_openweight_settings_use_server_endpoint_and_optional_secret(monkeypatch):
    monkeypatch.setenv("STUDIO_OPENWEIGHT_BASE_URL", "http://modelbox.local:8080/v1/")
    monkeypatch.setenv("STUDIO_OPENWEIGHT_MODEL", "qwen-local")
    response = client.put("/api/config", json={
        "provider": "openweight", "model": "browser-model",
        "api_key": "optional-private-key"})
    assert response.status_code == 200
    assert "optional-private-key" not in response.text
    assert "http://modelbox.local:8080" not in response.text
    body = response.json()
    state = body["llm"]["providers"]["openweight"]
    assert body["llm"]["provider"] == "openweight"
    assert state["model"] == "qwen-local"
    assert state["endpoint_host"] == "modelbox.local"
    assert state["configured"] is True
    assert state["auth_method"] == "optional_api_key"
    assert state["api_key_source"] == "secret_manager"
    assert config.get_llm_config() == {
        "provider": "openweight", "api_key": "optional-private-key",
        "model": "qwen-local", "base_url": "http://modelbox.local:8080/v1",
        "region": None}
    saved = json.loads(config.CONFIG_PATH.read_text())
    assert "openweight" not in saved.get("llm", {}).get("keys", {})
    assert saved["llm"]["models"].get("openweight") is None


def test_qwen_profile_wires_model_settings_without_loading_weights(monkeypatch):
    monkeypatch.setenv("STUDIO_OPENWEIGHT_BASE_URL", "http://inference.internal:8000/v1")
    monkeypatch.setenv("STUDIO_OPENWEIGHT_MODEL", "Qwen/Qwen3.8-27B")
    response = client.put("/api/config", json={"provider": "openweight"})
    assert response.status_code == 200
    state = response.json()["llm"]["providers"]["openweight"]
    assert state["model"] == "Qwen/Qwen3.8-27B"
    assert state["endpoint_host"] == "inference.internal"
    assert state["configured"] is True
    cfg = config.get_llm_config()
    assert cfg["provider"] == "openweight"
    assert cfg["model"] == "Qwen/Qwen3.8-27B"
    assert cfg["base_url"] == "http://inference.internal:8000/v1"
    assert cfg["api_key"] == "not-required"


def test_openweight_endpoint_rejects_credentials_and_url_parameters(monkeypatch):
    for endpoint in ("http://user:pass@modelbox.local/v1",
                     "http://modelbox.local/v1?token=hidden",
                     "http://modelbox.local/v1#secret"):
        monkeypatch.setenv("STUDIO_OPENWEIGHT_BASE_URL", endpoint)
        monkeypatch.setenv("STUDIO_OPENWEIGHT_MODEL", "qwen-local")
        client.put("/api/config", json={"provider": "openweight"})
        response = client.post("/api/config/llm/test")
        assert response.status_code == 400
        assert "STUDIO_OPENWEIGHT_BASE_URL" in response.json()["detail"]


def test_openweight_connection_uses_fake_openai_compatible_endpoint(monkeypatch):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            requests.append((self.path, payload, self.headers.get("Authorization")))
            body = json.dumps({
                "id": "chatcmpl-local", "object": "chat.completion", "created": 1,
                "model": payload["model"],
                "choices": [{"index": 0, "message": {"role": "assistant",
                    "content": "pong"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                          "total_tokens": 2},
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        monkeypatch.setenv("STUDIO_OPENWEIGHT_BASE_URL",
                           f"http://127.0.0.1:{server.server_port}/v1")
        monkeypatch.setenv("STUDIO_OPENWEIGHT_MODEL", "fixture-model")
        client.put("/api/config", json={"provider": "openweight"})
        response = client.post("/api/config/llm/test")
        assert response.status_code == 200, response.text
        assert response.json()["provider"] == "openweight"
        assert response.json()["model"] == "fixture-model"
        assert requests[0][0] == "/v1/chat/completions"
        assert requests[0][1]["model"] == "fixture-model"
        assert requests[0][2] == "Bearer not-required"
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


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
    assert provs["openai"]["api_key_set"] is True


def test_key_write_uses_encrypted_local_store_without_kms(monkeypatch):
    monkeypatch.delenv("STUDIO_LLM_SECRET_ID")
    monkeypatch.delenv("STUDIO_LLM_KMS_KEY_ID")
    response = client.put("/api/config", json={
        "provider": "anthropic", "model": "new-model", "api_key": "new-secret"})
    body = response.json()

    data_path, key_path = secret_store._local_paths()
    assert response.status_code == 200
    assert "new-secret" not in response.text
    assert secret_store.read_keys()["anthropic"] == "new-secret"
    assert data_path.exists() and key_path.exists()
    assert "new-secret" not in data_path.read_text()
    assert "new-secret" not in config.CONFIG_PATH.read_text()
    assert data_path.stat().st_mode & 0o777 == 0o600
    assert key_path.stat().st_mode & 0o777 == 0o600
    assert data_path.parent.stat().st_mode & 0o777 == 0o700
    assert body["llm"]["providers"]["anthropic"]["api_key_source"] == "local_encrypted"


def test_secret_store_denial_keeps_existing_environment_service_key(
        monkeypatch):
    config.CONFIG_PATH.write_text(json.dumps({
        "llm": {"provider": "anthropic", "models": {"anthropic": "old-model"}},
    }))
    before = config.CONFIG_PATH.read_text()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "deployment-key")
    memory = secret_store._client(secret_store.SecretStoreSettings.from_env())

    def denied_create(**_kwargs):
        raise ClientError({"Error": {"Code": "AccessDeniedException"}},
                          "CreateSecret")

    monkeypatch.setattr(memory, "create_secret", denied_create)
    config.update_llm_config(provider="anthropic", model="new-model",
                             api_key="new-secret")

    assert config.CONFIG_PATH.read_text() != before
    assert secret_store.read_keys()["anthropic"] == "new-secret"
    assert config.get_llm_config()["api_key"] == "deployment-key"


def test_local_key_tampering_fails_closed(monkeypatch):
    monkeypatch.delenv("STUDIO_LLM_SECRET_ID")
    monkeypatch.delenv("STUDIO_LLM_KMS_KEY_ID")
    secret_store.write_keys({"anthropic": "tamper-check-secret"})
    data_path, _ = secret_store._local_paths()
    data_path.write_text(data_path.read_text()[:-4] + "AAAA")

    with pytest.raises(secret_store.SecretStoreError, match="could not be read or verified"):
        secret_store.read_keys()


def test_local_keys_migrate_to_kms_without_loss(monkeypatch):
    monkeypatch.delenv("STUDIO_LLM_SECRET_ID")
    monkeypatch.delenv("STUDIO_LLM_KMS_KEY_ID")
    secret_store.write_keys({"anthropic": "local-before-recovery"})
    data_path, _ = secret_store._local_paths()
    assert data_path.exists()

    monkeypatch.setenv("STUDIO_LLM_SECRET_ID", "cohort-studio/test/llm")
    monkeypatch.setenv("STUDIO_LLM_KMS_KEY_ID",
                       "arn:aws:kms:us-east-1:123456789012:key/"
                       "12345678-1234-1234-1234-123456789012")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    memory = secret_store._client(secret_store.SecretStoreSettings.from_env())
    memory.value = json.dumps({"version": 1, "keys": {
        "anthropic": "stale-remote-key", "openai": "remote-key"}})
    memory.kms_key = secret_store.SecretStoreSettings.from_env().kms_key_arn
    assert secret_store.key_source("anthropic") == "local_encrypted"

    assert secret_store.read_keys() == {
        "anthropic": "local-before-recovery", "openai": "remote-key"}
    assert not data_path.exists()
    assert json.loads(memory.value)["keys"] == {
        "anthropic": "local-before-recovery", "openai": "remote-key"}


def test_local_key_deletion_survives_kms_recovery(monkeypatch):
    secret_store.write_keys({"anthropic": "stale-key"})
    monkeypatch.setenv("STUDIO_LLM_SECRET_ID", "cohort-studio/test/llm")
    monkeypatch.setenv("STUDIO_LLM_KMS_KEY_ID",
                       "arn:aws:kms:us-east-1:123456789012:key/"
                       "12345678-1234-1234-1234-123456789012")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    settings = secret_store.SecretStoreSettings.from_env()
    memory = secret_store._client(settings)
    memory.value = json.dumps({"version": 1, "keys": {
        "anthropic": "stale-key", "openai": "keep-key"}})
    memory.kms_key = settings.kms_key_arn
    original_read = memory.get_secret_value

    def denied_read(**_kwargs):
        raise ClientError({"Error": {"Code": "AccessDeniedException"}},
                          "GetSecretValue")

    monkeypatch.setattr(memory, "get_secret_value", denied_read)
    secret_store.remove_key("anthropic")
    assert "anthropic" not in secret_store.read_keys()

    monkeypatch.setattr(memory, "get_secret_value", original_read)
    assert secret_store.read_keys() == {"openai": "keep-key"}
    assert json.loads(memory.value)["keys"] == {"openai": "keep-key"}


def test_recovery_during_save_preserves_remote_and_local_keys(monkeypatch):
    settings = secret_store.SecretStoreSettings.from_env()
    memory = secret_store._client(settings)
    memory.value = json.dumps({"version": 1, "keys": {"openai": "remote-key"}})
    memory.kms_key = settings.kms_key_arn
    original_read = memory.get_secret_value

    def denied_read(**_kwargs):
        raise ClientError({"Error": {"Code": "AccessDeniedException"}},
                          "GetSecretValue")

    monkeypatch.setattr(memory, "get_secret_value", denied_read)
    secret_store.write_keys({"anthropic": "saved-during-outage"})
    assert secret_store.read_keys() == {"anthropic": "saved-during-outage"}

    monkeypatch.setattr(memory, "get_secret_value", original_read)
    secret_store.write_keys({"gemini": "new-key"})
    assert secret_store.read_keys() == {
        "openai": "remote-key", "anthropic": "saved-during-outage",
        "gemini": "new-key"}


def test_delete_local_key_preserves_other_local_and_remote_keys(monkeypatch):
    monkeypatch.delenv("STUDIO_LLM_SECRET_ID")
    monkeypatch.delenv("STUDIO_LLM_KMS_KEY_ID")
    secret_store.write_keys({"anthropic": "remove-me", "jev": "keep-local"})
    monkeypatch.setenv("STUDIO_LLM_SECRET_ID", "cohort-studio/test/llm")
    monkeypatch.setenv("STUDIO_LLM_KMS_KEY_ID",
                       "arn:aws:kms:us-east-1:123456789012:key/"
                       "12345678-1234-1234-1234-123456789012")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    settings = secret_store.SecretStoreSettings.from_env()
    memory = secret_store._client(settings)
    memory.value = json.dumps({"version": 1, "keys": {"openai": "keep-remote"}})
    memory.kms_key = settings.kms_key_arn

    secret_store.remove_key("anthropic")

    assert secret_store.read_keys() == {"jev": "keep-local", "openai": "keep-remote"}
    assert json.loads(memory.value)["keys"] == {
        "jev": "keep-local", "openai": "keep-remote"}


def test_concurrent_local_saves_and_reads_do_not_lose_keys(monkeypatch):
    monkeypatch.delenv("STUDIO_LLM_SECRET_ID")
    monkeypatch.delenv("STUDIO_LLM_KMS_KEY_ID")
    values = {"openai": "openai-key", "anthropic": "anthropic-key",
              "gemini": "gemini-key", "jev": "jev-key"}

    def save(item):
        key, value = item
        secret_store.write_keys({key: value})
        return secret_store.read_keys()

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(save, values.items()))

    assert secret_store.read_keys() == values


def test_clear_key_with_unavailable_configured_store_clears_legacy_key(
        monkeypatch):
    config.CONFIG_PATH.write_text(json.dumps({
        "llm": {"provider": "anthropic", "keys": {"anthropic": "legacy-ant"}},
    }))
    memory = secret_store._client(secret_store.SecretStoreSettings.from_env())

    def denied_read(**_kwargs):
        raise ClientError({"Error": {"Code": "AccessDeniedException"}},
                          "GetSecretValue")

    monkeypatch.setattr(memory, "get_secret_value", denied_read)
    config.update_llm_config(provider="anthropic", api_key="")

    assert "legacy-ant" not in config.CONFIG_PATH.read_text()
    assert config.get_llm_config()["api_key"] is None


def test_jev_read_falls_back_to_existing_legacy_key_if_store_is_unavailable(
        monkeypatch):
    config.CONFIG_PATH.write_text(json.dumps({"jev": {"api_key": "legacy-jev"}}))
    memory = secret_store._client(secret_store.SecretStoreSettings.from_env())

    def denied_read(**_kwargs):
        raise ClientError({"Error": {"Code": "AccessDeniedException"}},
                          "GetSecretValue")

    monkeypatch.setattr(memory, "get_secret_value", denied_read)

    assert config.get_integration_key("jev") == "legacy-jev"
    public = config.public_config()
    assert public["jev"]["api_key_set"] is True
    assert public["jev"]["api_key_source"] == "legacy_settings"
    assert public["jev"]["secure_key_store_available"] is False


def test_legacy_key_migration_confirms_secret_before_removing_disk_keys():
    config.CONFIG_PATH.write_text(json.dumps({
        "llm": {"provider": "anthropic", "keys": {"anthropic": "legacy-ant"}},
        "jev": {"api_key": "legacy-jev", "model": "jev-model"},
    }))

    result = config.migrate_legacy_keys()

    saved = json.loads(config.CONFIG_PATH.read_text())
    secure = secret_store.read_keys()
    assert result == {"migrated": 2}
    assert secure == {"anthropic": "legacy-ant", "jev": "legacy-jev"}
    assert "legacy-ant" not in config.CONFIG_PATH.read_text()
    assert "legacy-jev" not in config.CONFIG_PATH.read_text()
    assert saved["jev"]["model"] == "jev-model"
    assert "keys" not in saved["llm"]
    assert config.public_config()["llm"]["legacy_keys_present"] is False
    assert config.public_config()["jev"]["legacy_key_present"] is False


def test_failed_legacy_migration_keeps_plaintext_for_retry(monkeypatch):
    config.CONFIG_PATH.write_text(json.dumps({
        "llm": {"provider": "anthropic", "keys": {"anthropic": "legacy-ant"}},
    }))
    monkeypatch.setattr(secret_store, "write_keys", lambda _keys: None)

    with pytest.raises(secret_store.SecretStoreError, match="could not be confirmed"):
        config.migrate_legacy_keys()

    assert "legacy-ant" in config.CONFIG_PATH.read_text()


def test_clear_legacy_key_without_store_does_not_call_aws(monkeypatch):
    config.CONFIG_PATH.write_text(json.dumps({
        "llm": {"provider": "anthropic", "keys": {"anthropic": "legacy-ant"}},
    }))
    monkeypatch.delenv("STUDIO_LLM_SECRET_ID")
    monkeypatch.delenv("STUDIO_LLM_KMS_KEY_ID")
    monkeypatch.setattr(secret_store, "_client",
                        lambda _settings: pytest.fail("AWS must not be called"))

    config.update_llm_config(provider="anthropic", api_key="")

    assert "legacy-ant" not in config.CONFIG_PATH.read_text()


def test_jev_key_is_secure_and_environment_takes_precedence(monkeypatch):
    body = config.update_jev_config(api_key="jev-secret", model="ranker-v1")
    assert secret_store.read_keys()["jev"] == "jev-secret"
    assert "jev-secret" not in config.CONFIG_PATH.read_text()
    assert "jev-secret" not in json.dumps(body)
    assert body["jev"]["api_key_set"] is True
    assert body["jev"]["model"] == "ranker-v1"
    assert body["jev"]["api_key_source"] == "secret_manager"
    assert config.get_integration_key("jev") == "jev-secret"

    monkeypatch.setenv("TYPESAFE_API_KEY", "jev-from-env")
    assert config.get_integration_key("jev") == "jev-from-env"
    assert config.public_config()["jev"]["api_key_source"] == "environment"


def test_existing_legacy_keys_remain_readable_without_backend(monkeypatch):
    config.CONFIG_PATH.write_text(json.dumps({
        "llm": {"provider": "openai", "keys": {"openai": "legacy-openai"}},
        "jev": {"api_key": "legacy-jev"},
    }))
    monkeypatch.delenv("STUDIO_LLM_SECRET_ID")
    monkeypatch.delenv("STUDIO_LLM_KMS_KEY_ID")

    assert config.get_llm_config()["api_key"] == "legacy-openai"
    assert config.get_integration_key("jev") == "legacy-jev"
    public = config.public_config()
    assert public["llm"]["api_key_set"] is True
    assert public["llm"]["api_key_source"] == "legacy_settings"
    assert public["jev"]["api_key_set"] is True
    assert public["jev"]["api_key_source"] == "legacy_settings"


def test_existing_secret_with_wrong_kms_key_is_not_updated():
    store = secret_store._client(secret_store.SecretStoreSettings.from_env())
    store.value = json.dumps({"version": 1, "keys": {"openai": "old-key"}})
    store.kms_key = "arn:aws:kms:us-east-1:123456789012:key/wrong"

    secret_store.write_keys({"openai": "new-key"})

    assert json.loads(store.value)["keys"]["openai"] == "old-key"
    assert secret_store.read_keys()["openai"] == "new-key"
    assert secret_store.key_source("openai") == "local_encrypted"


def test_mcp_token_is_stored_in_secret_manager_and_never_returned():
    token = "mcp-private-token-123"
    body = config.update_mcp_connections([{
        "name": "biorxiv", "label": "bioRxiv", "url": "https://example.org/mcp",
        "enabled": True, "authorization_token": token,
    }])
    assert secret_store.read_keys()["mcp:biorxiv"] == token
    assert token not in config.CONFIG_PATH.read_text()
    assert token not in json.dumps(body)
    assert body["mcp_connections"][0]["token_set"] is True
    assert config.get_mcp_connections()[0]["authorization_token"] == token


def test_mcp_token_write_denial_keeps_connection_metadata_unchanged(monkeypatch):
    config.CONFIG_PATH.write_text(json.dumps({
        "mcp_connections": [{
            "name": "biorxiv", "label": "bioRxiv",
            "url": "https://old.example.org/mcp", "enabled": False,
        }],
    }))
    before = config.CONFIG_PATH.read_text()
    monkeypatch.setattr(secret_store, "write_keys", lambda _keys: (
        _ for _ in ()).throw(secret_store.SecretStoreError("store unavailable")))

    with pytest.raises(secret_store.SecretStoreError):
        config.update_mcp_connections([{
            "name": "biorxiv", "label": "bioRxiv",
            "url": "https://new.example.org/mcp", "enabled": True,
            "authorization_token": "must-not-be-saved",
        }])

    assert config.CONFIG_PATH.read_text() == before
    assert "must-not-be-saved" not in before


def test_mcp_token_omission_and_empty_string_preserve_existing_secure_token():
    token = "preserved-mcp-token"
    config.update_mcp_connections([{
        "name": "pubmed", "label": "PubMed", "url": "https://example.org/mcp",
        "enabled": True, "authorization_token": token,
    }])
    config.update_mcp_connections([{
        "name": "pubmed", "label": "PubMed", "url": "https://changed.example.org/mcp",
        "enabled": True,
    }])
    config.update_mcp_connections([{
        "name": "pubmed", "label": "PubMed", "url": "https://changed.example.org/mcp",
        "enabled": True, "authorization_token": "",
    }])
    assert secret_store.read_keys()["mcp:pubmed"] == token
    assert config.get_mcp_connections()[0]["authorization_token"] == token
    assert token not in config.CONFIG_PATH.read_text()


def test_legacy_mcp_token_reads_and_migrates_only_after_confirmation(monkeypatch):
    token = "legacy-mcp-token"
    config.CONFIG_PATH.write_text(json.dumps({
        "mcp_connections": [{
            "name": "biorxiv", "label": "bioRxiv", "url": "https://example.org/mcp",
            "enabled": True, "authorization_token": token,
        }],
    }))
    public = config.public_config()
    assert public["llm"]["legacy_mcp_tokens_present"] is True
    assert public["mcp_connections"][0]["token_set"] is True
    assert token not in json.dumps(public)
    assert config.get_mcp_connections()[0]["authorization_token"] == token

    result = config.migrate_legacy_keys()
    assert result == {"migrated": 1}
    assert secret_store.read_keys()["mcp:biorxiv"] == token
    assert token not in config.CONFIG_PATH.read_text()
    assert config.public_config()["llm"]["legacy_mcp_tokens_present"] is False


def test_failed_mcp_legacy_migration_keeps_plaintext_for_retry(monkeypatch):
    token = "legacy-mcp-token"
    config.CONFIG_PATH.write_text(json.dumps({
        "mcp_connections": [{
            "name": "biorxiv", "label": "bioRxiv", "url": "https://example.org/mcp",
            "enabled": True, "authorization_token": token,
        }],
    }))
    monkeypatch.setattr(secret_store, "write_keys", lambda _keys: None)

    with pytest.raises(secret_store.SecretStoreError, match="could not be confirmed"):
        config.migrate_legacy_keys()

    assert token in config.CONFIG_PATH.read_text()
    assert secret_store.read_keys() == {}


def test_secret_store_accepts_only_bounded_mcp_token_names():
    stored = secret_store.StoredSecret.model_validate({
        "version": 1, "keys": {"anthropic": "api-key", "mcp:bioRxiv_1": "mcp-token"},
    })
    assert stored.keys == {"anthropic": "api-key", "mcp:bioRxiv_1": "mcp-token"}
    for key in ("mcp:", "mcp:bad.name", "mcp:" + "a" * 65, "unknown"):
        with pytest.raises(Exception):
            secret_store.StoredSecret.model_validate({
                "version": 1, "keys": {key: "token"},
            })


def test_jev_write_failure_does_not_save_token_or_model(monkeypatch):
    monkeypatch.setattr(secret_store, "write_keys", lambda _keys: (
        _ for _ in ()).throw(secret_store.SecretStoreError("store unavailable")))
    before = config.CONFIG_PATH.read_text() if config.CONFIG_PATH.exists() else None

    with pytest.raises(secret_store.SecretStoreError):
        config.update_jev_config(api_key="new-jev-secret", model="new-model")

    after = config.CONFIG_PATH.read_text() if config.CONFIG_PATH.exists() else None
    assert after == before
    assert "new-jev-secret" not in (after or "")


def test_agent_telemetry_is_not_exposed(monkeypatch, tmp_path):
    import lineage
    engine = _file_engine(tmp_path)
    monkeypatch.setattr(main, "_lineage_engine", lambda: engine)
    lineage.record_turn(engine, "private", "openai", "test", "table",
                        "private prompt", 5)
    assert client.get("/api/agent/turns").json() == {"turns": []}


def _file_engine(tmp_path):
    from sqlalchemy import create_engine
    return create_engine(f"sqlite:///{tmp_path / 'turns.db'}",
                         connect_args={"check_same_thread": False})
