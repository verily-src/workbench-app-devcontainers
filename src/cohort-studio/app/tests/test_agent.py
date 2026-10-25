import json
from contextlib import nullcontext
from pathlib import Path

import duckdb
import pandas as pd
from fastapi.testclient import TestClient

import agent
import datasets
import main

FIXTURE = Path(__file__).parent / "fixtures" / "samples.csv"
client = TestClient(main.app)


def _open_fixture():
    with FIXTURE.open("rb") as stream:
        response = client.post("/api/datasets/upload",
                               files={"file": ("samples.csv", stream, "text/csv")})
    return response.json()["dataset_id"]


def _open_disk_fixture(tmp_path):
    complete = pd.DataFrame({
        "person_id": range(1, 1001),
        "group": ["keep"] * 600 + ["drop"] * 400,
        "score": range(1000),
    })
    path = tmp_path / "source.duckdb"
    connection = duckdb.connect(str(path))
    try:
        connection.register("fixture", complete)
        connection.execute("CREATE TABLE data AS SELECT * FROM fixture")
    finally:
        connection.close()
    disk_source = {
        "path": str(path), "table": "data", "columns": list(complete.columns),
        "rows": len(complete), "estimated_bytes": path.stat().st_size,
        "scan_bytes": path.stat().st_size,
    }
    opened = datasets.open_dataset(
        complete.head(60), "fixture-s3 / genotypes.parquet",
        disk_source=disk_source)
    return opened["dataset_id"], complete


def test_chat_endpoint_applies_agent_result(monkeypatch):
    monkeypatch.setattr(main.llm, "validate_config", lambda _cfg: None)
    monkeypatch.setattr(main.agent_sessions, "bind", lambda *_args: nullcontext())

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


def test_disk_backed_chat_uses_bounded_duckdb_tools_through_api(
        monkeypatch, tmp_path):
    import agent_sessions
    import config
    import llm
    import providers

    dataset_id, _complete = _open_disk_fixture(tmp_path)
    observed = {}

    monkeypatch.setattr(config, "get_llm_config", lambda: {
        "provider": "openai", "model": "test-model", "api_key": "fake",
        "base_url": None,
    })
    monkeypatch.setattr(llm, "validate_config", lambda _cfg: None)
    monkeypatch.setattr(agent_sessions, "bind", lambda *_args: nullcontext())
    monkeypatch.setattr(agent_sessions, "start", lambda *_args: None)
    monkeypatch.setattr(agent_sessions, "finish", lambda result: result)
    monkeypatch.setattr(main, "_record_turn", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main.lineage, "record", lambda *_args, **_kwargs: None)

    def fake_provider(_provider, _model, _key, _base_url, system, _messages,
                      tools, **_kwargs):
        observed["system"] = system
        observed["preview"] = json.loads(tools["run_query"]("[]"))
        observed["aggregate"] = json.loads(tools["aggregate"](
            agg="mean", column="score", group_by="group", filters_json="[]"))
        observed["filters"] = json.loads(tools["set_filters"](
            '[{"column":"group","kind":"categorical",'
            '"values":["keep"]}]', "keep group"))
        return {"reply": "The current selection contains 600 rows.",
                "usage": {"total_tokens": 12},
                "tool_calls": ["run_query", "aggregate", "set_filters"]}

    monkeypatch.setattr(providers, "run", fake_provider)
    try:
        response = client.post(f"/api/datasets/{dataset_id}/chat", json={
            "message": "Count the full dataset and filter to keep.",
            "filters": [{"column": "group", "kind": "categorical",
                         "values": ["keep"]}], "charts": [],
        })
        assert response.status_code == 200, response.text
        assert response.json()["reply"] == "The current selection contains 600 rows."
        assert response.json()["filters"] == [{
            "column": "group", "kind": "categorical", "values": ["keep"]}]
        assert observed["preview"]["total_rows"] == 600
        assert observed["preview"]["matching_rows"] == 600
        assert len(observed["preview"]["preview"]) <= 5
        assert {row["group"] for row in observed["preview"]["preview"]} == {"keep"}
        assert observed["aggregate"]["rows_considered"] == 600
        assert observed["aggregate"]["result"] == {"keep": 299.5}
        assert observed["filters"]["matching_rows"] == 600
        assert "complete source is stored on disk" in observed["system"]
        assert len(datasets.get(dataset_id)["df"]) == 60
        assert datasets.get(dataset_id)["disk_source"]["rows"] == 1000
    finally:
        datasets.close_dataset(dataset_id)


def test_disk_backed_ask_uses_full_disk_profile(monkeypatch, tmp_path):
    dataset_id, complete = _open_disk_fixture(tmp_path)
    observed = {}

    def suggest(question, columns, filters):
        observed.update(question=question, columns=columns, filters=filters)
        return {"filters": [{"column": "group", "kind": "categorical",
                             "values": ["keep"]}]}

    monkeypatch.setattr(main.llm, "suggest_filters", suggest)
    monkeypatch.setattr(main.lineage, "record", lambda *_args, **_kwargs: None)
    try:
        response = client.post(f"/api/datasets/{dataset_id}/ask", json={
            "question": "keep cohort members", "filters": [],
        })
        assert response.status_code == 200, response.text
        assert observed["question"] == "keep cohort members"
        score = next(column for column in observed["columns"]
                     if column["name"] == "score")
        assert (score["min"], score["max"]) == (0, 999)
        group = next(column for column in observed["columns"]
                     if column["name"] == "group")
        assert set(group["values"]) >= {"keep", "drop"}
        assert len(datasets.get(dataset_id)["df"]) == 60
        assert len(complete) == 1000
    finally:
        datasets.close_dataset(dataset_id)
