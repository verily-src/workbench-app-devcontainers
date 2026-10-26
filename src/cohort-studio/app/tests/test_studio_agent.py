import json

import pytest

import agent_sessions
import agent_runtime
import config
import llm
import providers
import studio_agent


def test_studio_agent_runs_bounded_multistep_operations(monkeypatch):
    cfg = {"provider": "openai", "model": "test-model", "api_key": "fake",
           "base_url": None}
    monkeypatch.setattr(config, "get_llm_config", lambda: cfg)
    monkeypatch.setattr(llm, "validate_config", lambda _cfg: None)
    monkeypatch.setattr(agent_sessions, "start", lambda *_args: [
        {"role": "user", "content": "prior question"},
        {"role": "assistant", "content": "prior answer"},
    ])
    events = []
    monkeypatch.setattr(agent_sessions, "event", events.append)
    operations = []

    def record(name):
        def operation(**kwargs):
            operations.append((name, kwargs))
            return {"operation": name, "ok": True}
        return operation

    callbacks = {name: record(name) for name, *_ in studio_agent._TOOLS}
    observed = {}

    def fake_provider(_provider, _model, _key, _base_url, system, messages,
                      tools, **kwargs):
        observed.update(system=system, messages=messages,
                        schemas=kwargs["tool_schemas"], tools=tools)
        assert json.loads(tools["list_sources"]()) == {
            "operation": "list_sources", "ok": True}
        assert json.loads(tools["list_tables"](
            resource_id="cdm-1", kind="aurora", query="person"))["ok"]
        assert json.loads(tools["search_concepts"](
            resource_id="cdm-1", q="asthma", domain="condition"))["ok"]
        spec_json = json.dumps({"criteria": []})
        assert json.loads(tools["count_cohort"](
            resource_id="cdm-1", spec_json=spec_json))["ok"]
        assert json.loads(tools["recommend_join"](
            left_json='{"kind":"aurora"}',
            right_json='{"kind":"s3"}'))["ok"]
        assert json.loads(tools["build_dashboard"](
            source_json='{"kind":"aurora"}', title="Cohort overview",
            charts_json='[]', filters_json='[]'))["ok"]
        assert json.loads(tools["query_dashboard"](
            dataset_id="dashboard-1", filters_json='[]',
            charts_json='[]'))["ok"]
        assert json.loads(tools["list_workflows"]())["ok"]
        assert json.loads(tools["prepare_workflow"](
            dataset_id="dataset-1", input_resource_id="input-1",
            output_resource_id="output-1", filters_json='[]'))["ok"]
        kwargs["on_step"]({"type": "model_start", "turn": 1})
        return {"reply": "I inspected the sources and prepared proposals.",
                "usage": {"total_tokens": 21},
                "tool_calls": [name for name, _ in operations]}

    monkeypatch.setattr(providers, "run", fake_provider)
    result = studio_agent.chat("Plan a cohort dashboard", callbacks,
                               on_step=lambda event: events.append(event))

    assert result["reply"].startswith("I inspected")
    assert result["usage"]["total_tokens"] == 21
    assert len(operations) == 9
    assert next(item for item in operations if item[0] == "count_cohort") == ("count_cohort", {
        "resource_id": "cdm-1", "spec_json": '{"criteria": []}'})
    assert "prior question" in [item["content"] for item in observed["messages"]]
    assert "prior answer" in [item["content"] for item in observed["messages"]]
    names = [item["function"]["name"] for item in observed["schemas"]]
    assert names == [name for name, *_ in studio_agent._TOOLS]
    assert "submit_workflow" not in names
    assert "probabilistic evidence only" in observed["system"]
    assert "Search the selected OMOP CDM" in observed["system"]
    assert events[-1]["type"] == "model_start"


def test_studio_agent_validates_json_and_rejects_unknown_operations():
    called = []
    tools = {tool.__name__: tool for tool in studio_agent.build_tools({
        "count_cohort": lambda **args: called.append(args) or {"ok": True},
    })}
    result = json.loads(tools["count_cohort"](
        resource_id="cdm-1", spec_json="[]"))
    assert "JSON object" in result["error"]
    assert called == []

    with pytest.raises(ValueError, match="Unsupported agent operation"):
        studio_agent.build_tools({"submit_workflow": lambda: None})


def test_chat_input_is_bounded_and_nonblank():
    with pytest.raises(ValueError):
        studio_agent.ChatInput.model_validate({"message": "  "})
    with pytest.raises(ValueError):
        studio_agent.ChatInput.model_validate({"message": "x" * 8001})


def test_tool_schemas_bound_arguments_and_reject_extra_fields():
    validators = agent_runtime._validators(studio_agent.TOOL_SCHEMAS)
    with pytest.raises(ValueError):
        validators["list_tables"].model_validate({
            "resource_id": "cdm-1", "query": "x" * 257})
    with pytest.raises(ValueError):
        validators["list_sources"].model_validate({"submit_workflow": True})
