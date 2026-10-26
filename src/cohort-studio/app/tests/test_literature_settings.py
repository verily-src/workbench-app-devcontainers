import pytest

import config
import secret_store
from app.tests.test_settings import client, isolated_config


def test_ncbi_key_is_encrypted_redacted_and_removable(isolated_config):
    key = "ncbi-test-key-do-not-echo"
    saved = client.put("/api/config", json={"ncbi_api_key": key})
    assert saved.status_code == 200
    assert key not in saved.text
    assert secret_store.read_keys()["ncbi"] == key
    assert key not in (config.CONFIG_PATH.read_text()
                       if config.CONFIG_PATH.exists() else "")
    assert saved.json()["literature"] == {
        "ncbi_api_key_set": True,
        "ncbi_api_key_source": "secret_manager",
        "secure_key_store_available": True,
    }
    assert config.get_ncbi_api_key() == key

    removed = client.put("/api/config", json={"ncbi_api_key": ""})
    assert removed.status_code == 200
    assert "ncbi" not in secret_store.read_keys()
    assert removed.json()["literature"]["ncbi_api_key_set"] is False
    assert config.get_ncbi_api_key() is None


def test_ncbi_environment_key_has_precedence_and_is_not_removed(isolated_config, monkeypatch):
    monkeypatch.setenv("NCBI_API_KEY", "environment-ncbi-key")
    client.put("/api/config", json={"ncbi_api_key": "saved-key"})
    assert config.get_ncbi_api_key() == "environment-ncbi-key"
    assert client.get("/api/config").json()["literature"] == {
        "ncbi_api_key_set": True,
        "ncbi_api_key_source": "environment",
        "secure_key_store_available": True,
    }
    client.put("/api/config", json={"ncbi_api_key": ""})
    assert config.get_ncbi_api_key() == "environment-ncbi-key"


def test_ncbi_key_request_is_bounded(isolated_config):
    response = client.put("/api/config", json={"ncbi_api_key": "x" * 8193})
    assert response.status_code == 422


def test_invalid_ncbi_key_format_is_rejected_without_echo(isolated_config):
    secret = "key-with-invalid-character-<must-not-echo>"
    response = client.put("/api/config", json={"ncbi_api_key": secret})
    assert response.status_code == 422
    assert secret not in response.text
