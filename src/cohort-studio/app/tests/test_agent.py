"""Agent tool tests — the callables the LLM drives, no network."""

import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import agent
import datasets
import main

FIXTURE = Path(__file__).parent / "fixtures" / "samples.csv"
client = TestClient(main.app)


@pytest.fixture
def toolkit():
    df = pd.read_csv(FIXTURE)
    columns = datasets.profile_columns(df)
    ui = {"filters": [], "charts": []}
    actions = []
    tools = {fn.__name__: fn
             for fn in agent.build_tools(df, columns, ui, actions)}
    return df, ui, actions, tools


def test_run_query_counts_and_previews(toolkit):
    _df, _ui, _actions, tools = toolkit
    out = json.loads(tools["run_query"](json.dumps(
        [{"column": "tissue", "kind": "categorical", "values": ["liver"]}])))
    assert out["total_rows"] == 100
    assert out["matching_rows"] == 25
    assert len(out["preview"]) == 5
    assert out["preview"][0]["tissue"] == "liver"


def test_aggregate_grouped_mean(toolkit):
    df, _ui, _actions, tools = toolkit
    out = json.loads(tools["aggregate"](
        agg="mean", column="rin_score", group_by="tissue"))
    assert set(out["result"]) == {"liver", "lung", "heart", "skin"}
    expected = round(float(df[df.tissue == "liver"].rin_score.mean()), 4)
    assert out["result"]["liver"] == expected


def test_aggregate_rejects_unknown(toolkit):
    _df, _ui, _actions, tools = toolkit
    assert "error" in json.loads(tools["aggregate"](agg="stddev"))
    assert "error" in json.loads(tools["aggregate"](
        agg="mean", column="nope"))


def test_set_filters_mutates_ui_and_validates(toolkit):
    _df, ui, actions, tools = toolkit
    out = json.loads(tools["set_filters"](json.dumps([
        {"column": "tissue", "kind": "categorical",
         "values": ["liver", "BOGUS"]},
        {"column": "nope", "kind": "categorical", "values": ["x"]},
    ]), reason="liver only"))
    assert out["matching_rows"] == 25
    assert ui["filters"] == [
        {"column": "tissue", "kind": "categorical", "values": ["liver"]}]
    assert actions == ["Filters: liver only"]


def test_add_and_remove_chart(toolkit):
    _df, ui, actions, tools = toolkit
    assert "added" in json.loads(tools["add_chart"]("histogram", "rin_score"))
    assert "error" in json.loads(tools["add_chart"]("scatter", "rin_score"))
    assert "error" in json.loads(tools["add_chart"]("pie", "tissue"))
    out = json.loads(tools["add_chart"]("scatter", "rin_score", "age"))
    assert out["added"]["wide"] is True
    assert len(ui["charts"]) == 2
    json.loads(tools["remove_chart"](0))
    assert len(ui["charts"]) == 1
    assert ui["charts"][0]["kind"] == "scatter"
    assert actions[-1].startswith("Removed histogram")


def _open_fixture() -> str:
    with open(FIXTURE, "rb") as f:
        resp = client.post("/api/datasets/upload",
                           files={"file": ("samples.csv", f, "text/csv")})
    return resp.json()["dataset_id"]


def test_chat_endpoint_applies_agent_result(monkeypatch):
    def fake_chat(dataset_id, message, history, filters, charts):
        assert message == "show rin by tissue"
        assert history[-1]["content"] == "earlier question"
        return {"reply": "Added a chart.", "filters": filters,
                "charts": charts + [{"kind": "bar", "x": "tissue"}],
                "actions": ["Added bar of tissue"]}

    monkeypatch.setattr(agent, "chat", fake_chat)
    dataset_id = _open_fixture()
    resp = client.post(f"/api/datasets/{dataset_id}/chat", json={
        "message": "show rin by tissue",
        "history": [{"role": "user", "content": "earlier question"}],
        "filters": [], "charts": []})
    assert resp.status_code == 200
    body = resp.json()
    assert body["charts"] == [{"kind": "bar", "x": "tissue"}]
    assert body["actions"] == ["Added bar of tissue"]


def test_openai_compatible_tool_loop_runs_tools(monkeypatch):
    # Drive providers.run with a fake OpenAI client: round 1 asks for a
    # tool, round 2 replies with text. Verify the tool actually executed
    # and token usage accumulated across turns.
    import providers

    class Fn:
        def __init__(self, name, args):
            self.name, self.arguments = name, args

    class Call:
        def __init__(self, name, args):
            self.id, self.function = "call_1", Fn(name, args)

    class Msg:
        def __init__(self, content, tool_calls):
            self.content, self.tool_calls = content, tool_calls

        def model_dump(self, exclude_none=False):
            return {"role": "assistant", "content": self.content}

    class Usage:
        prompt_tokens, completion_tokens, total_tokens = 10, 4, 14

    class Resp:
        def __init__(self, msg):
            self.choices = [type("C", (), {"message": msg})()]
            self.usage = Usage()

    scripted = [
        Resp(Msg(None, [Call("add_chart",
                             '{"kind": "bar", "x": "tissue"}')])),
        Resp(Msg("Added a bar of tissue.", None)),
    ]

    class FakeCompletions:
        def create(self, **kwargs):
            return scripted.pop(0)

    class FakeClient:
        chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr(providers, "_client",
                        lambda api_key, base_url: FakeClient())

    df = pd.read_csv(FIXTURE)
    columns = datasets.profile_columns(df)
    ui = {"filters": [], "charts": []}
    actions = []
    impls = {fn.__name__: fn
             for fn in agent.build_tools(df, columns, ui, actions)}
    out = providers.run("openai", "m-1", "key", None, "sys",
                        [{"role": "user", "content": "plot tissue"}], impls)
    assert out["reply"] == "Added a bar of tissue."
    assert out["tool_calls"] == ["add_chart"]
    assert out["usage"]["total_tokens"] == 28  # 14 per call × 2 rounds
    assert ui["charts"] == [{"kind": "bar", "x": "tissue", "wide": False}]


def test_chat_unconfigured_is_400(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    import config
    monkeypatch.setattr(config, "CONFIG_PATH", Path("/nonexistent/cfg.json"))
    dataset_id = _open_fixture()
    resp = client.post(f"/api/datasets/{dataset_id}/chat",
                       json={"message": "hi"})
    assert resp.status_code == 400
    assert "Settings" in resp.json()["detail"]
