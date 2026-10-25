import pandas as pd

import agent
import agent_instructions
import cohort_agent
import datasets
import llm
import providers


def _tool_names(schemas):
    return [schema["function"]["name"] for schema in schemas]


def test_tab_agent_provider_gets_shared_guide_and_exact_tool_registry(monkeypatch):
    captured = {}
    monkeypatch.setattr(agent.config, "get_llm_config", lambda: {
        "provider": "openrouter", "model": "m-test", "api_key": "secret",
        "base_url": None})

    def fake_provider(provider, model, api_key, base_url, system, messages,
                      tool_impls, tool_schemas=None, vertex_config=None):
        captured.update(system=system,
                        tool_schemas=tool_schemas or providers.TOOL_SCHEMAS)
        return {"reply": "Ready.", "usage": {}}

    monkeypatch.setattr(agent.providers, "run", fake_provider)
    data = datasets.open_dataset(pd.DataFrame({"person_id": [1], "score": [2]}),
                                 "loaded sample", capped=False)
    try:
        agent.chat(data["dataset_id"], "Summarize this table.", [], [], [])
    finally:
        datasets.close_dataset(data["dataset_id"])

    assert _tool_names(captured["tool_schemas"]) == _tool_names(providers.TOOL_SCHEMAS)
    assert "expert bioinformatics, data science, and data engineering" in captured["system"]
    assert "run_query" in captured["system"]
    assert "add_chart" in captured["system"]
    assert "search_knowledge_base" not in captured["system"]
    assert "full-source results" in captured["system"]


def test_cohort_agent_provider_gets_actual_tools_and_scientific_guidance(monkeypatch):
    captured = {}
    monkeypatch.setattr(cohort_agent.config, "get_llm_config", lambda: {
        "provider": "openrouter", "model": "m-test", "api_key": "secret",
        "base_url": None})
    monkeypatch.setattr(cohort_agent, "build_tools", lambda *args: [])

    def fake_provider(provider, model, api_key, base_url, system, messages,
                      tool_impls, tool_schemas=None, vertex_config=None):
        captured.update(system=system, tool_schemas=tool_schemas)
        return {"reply": "Ready.", "usage": {}}

    monkeypatch.setattr(cohort_agent.providers, "run", fake_provider)
    cohort_agent.chat("omop", {"version": "5.4", "cdm_schema": "cdm"},
                      "What tools are available?")

    names = _tool_names(captured["tool_schemas"])
    assert names == _tool_names(cohort_agent.COHORT_TOOL_SCHEMAS)
    assert all(name in captured["system"] for name in names)
    assert "submit_workflow" not in captured["system"]
    assert "person-level cohorts" in captured["system"]


def test_filter_suggestion_prompt_uses_shared_guide_without_claiming_tools(monkeypatch):
    captured = {}
    monkeypatch.setattr(llm, "_cfg", lambda: {
        "provider": "openai", "model": "m-test", "api_key": "secret",
        "base_url": None})

    def fake_suggestion(_cfg, system, _prompt):
        captured["system"] = system
        return llm.FilterSuggestion(filters=[], explanation="No change.")

    monkeypatch.setattr(llm, "_openai_suggestion", fake_suggestion)
    result = llm.suggest_filters("clear", [], [])

    assert result["filters"] == []
    assert "None. Do not imply" in captured["system"]
    assert "available structured response fields: filters, explanation" in captured["system"].lower()
    assert "search_concepts" not in captured["system"]


def test_tool_registry_formats_names_from_supplied_schemas_only():
    system = agent_instructions.system_guidance(
        "data science", tool_schemas=[{"function": {
            "name": "actual_tool", "description": "Checks the actual source."}}])

    assert "actual_tool: Checks the actual source." in system
    assert "search_concepts" not in system
