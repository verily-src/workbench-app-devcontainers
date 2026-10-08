"""Settings, ask-AI, and MCP mount tests — no network, LLM mocked."""

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

    # the suggested filters actually work against the query endpoint
    out = client.post(f"/api/datasets/{dataset_id}/query",
                      json={"filters": body["filters"], "charts": []}).json()
    assert 0 < out["filtered"] < out["total"]


def test_suggest_filters_validation_drops_bad_columns(monkeypatch):
    class FakeParsed:
        filters = [
            llm.SuggestedFilter(column="tissue", kind="categorical",
                                values=["liver", "NOT_A_VALUE"]),
            llm.SuggestedFilter(column="nope", kind="categorical",
                                values=["x"]),
            llm.SuggestedFilter(column="rin_score", kind="range",
                                min=-999, max=7),
        ]
        explanation = "ok"

    class FakeResponse:
        stop_reason = "end_turn"
        parsed_output = FakeParsed()

    class FakeMessages:
        def parse(self, **kwargs):
            return FakeResponse()

    class FakeClient:
        messages = FakeMessages()

    monkeypatch.setattr(llm, "_client", lambda: (FakeClient(), "claude-opus-5"))
    columns = [
        {"name": "tissue", "filter_kind": "categorical",
         "values": ["liver", "lung"]},
        {"name": "rin_score", "filter_kind": "range", "min": 5.0, "max": 10.0},
    ]
    out = llm.suggest_filters("q", columns, [])
    assert out["filters"] == [
        {"column": "tissue", "kind": "categorical", "values": ["liver"]},
        {"column": "rin_score", "kind": "range", "min": 5.0, "max": 7.0},
    ]
