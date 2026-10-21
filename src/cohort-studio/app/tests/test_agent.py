from pathlib import Path

from fastapi.testclient import TestClient

import agent
import main

FIXTURE = Path(__file__).parent / "fixtures" / "samples.csv"
client = TestClient(main.app)


def _open_fixture():
    with FIXTURE.open("rb") as stream:
        response = client.post("/api/datasets/upload",
                               files={"file": ("samples.csv", stream, "text/csv")})
    return response.json()["dataset_id"]


def test_chat_endpoint_applies_agent_result(monkeypatch):
    def fake_chat(dataset_id, message, history, filters, charts):
        assert message == "show rin by tissue"
        assert history[-1]["content"] == "earlier question"
        return {"reply": "Added a chart.", "filters": filters,
                "charts": charts + [{"kind": "bar", "x": "tissue"}],
                "actions": ["Added bar of tissue"]}

    monkeypatch.setattr(agent, "chat", fake_chat)
    dataset_id = _open_fixture()
    response = client.post(f"/api/datasets/{dataset_id}/chat", json={
        "message": "show rin by tissue",
        "history": [{"role": "user", "content": "earlier question"}],
        "filters": [], "charts": []})
    assert response.status_code == 200
    body = response.json()
    assert body["charts"] == [{"kind": "bar", "x": "tissue"}]
    assert body["actions"] == ["Added bar of tissue"]


def test_chat_unconfigured_returns_400(monkeypatch):
    import config

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(config, "CONFIG_PATH", Path("/nonexistent/cfg.json"))
    dataset_id = _open_fixture()
    response = client.post(f"/api/datasets/{dataset_id}/chat", json={"message": "hi"})
    assert response.status_code == 400
    assert "Settings" in response.json()["detail"]
