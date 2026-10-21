"""Cohort agent tool-boundary tests; all external calls are faked."""

import json
import subprocess

import cohort_agent
import llm
import main
import workbench_apps
from fastapi.testclient import TestClient


INFO = {"version": "5.4", "cdm_schema": "cdm", "vocab_schema": "vocab"}
client = TestClient(main.app)


def test_fake_provider_searches_counts_and_proposes_validated_spec(monkeypatch):
    import config

    monkeypatch.setattr("db.get_engine_for_resource", lambda _rid: object())
    monkeypatch.setattr(config, "get_llm_config", lambda: {
        "provider": "openrouter", "api_key": "test-key",
        "model": "test/model", "base_url": "https://example.invalid"})
    monkeypatch.setattr(cohort_agent.omop, "search_concepts", lambda *a, **k: [
        {"concept_id": 123, "concept_name": "Asthma", "domain_id": "Condition"}])
    monkeypatch.setattr(cohort_agent.omop, "count", lambda *a, **k: {
        "persons": 7, "total_persons": 100,
        "attrition": [{"label": "Asthma", "persons": 7}]})

    def fake_provider(_provider, _model, _key, _base, _system, _messages,
                      tool_impls, tool_schemas=None):
        assert [s["function"]["name"] for s in tool_schemas] == [
            "search_concepts", "count_cohort", "propose_cohort",
            "list_workflow_jobs", "list_workbench_apps"]
        found = json.loads(tool_impls["search_concepts"]("asthma", "condition"))
        assert found["concepts"][0]["concept_id"] == 123
        spec_json = json.dumps({"criteria": [{
            "domain": "condition", "concept_ids": [123],
            "descendants": False}]})
        counted = json.loads(tool_impls["count_cohort"](spec_json))
        assert counted["persons"] == 7
        proposed = json.loads(tool_impls["propose_cohort"](
            spec_json, "Asthma diagnosis"))
        assert proposed["proposed"] is True
        assert proposed["counted"] is True
        return {"reply": "I found 7 people and proposed the cohort.",
                "usage": {"total_tokens": 12}}

    monkeypatch.setattr(cohort_agent.providers, "run", fake_provider)
    out = cohort_agent.chat("aurora-resource", INFO,
                            "Build an asthma cohort")
    assert out["reply"].startswith("I found 7")
    assert out["spec"]["criteria"][0]["concept_ids"] == [123]
    assert out["count"]["persons"] == 7
    assert out["reason"] == "Asthma diagnosis"
    assert out["tool_calls"] == ["search_concepts", "count_cohort",
                                 "propose_cohort"]


def test_proposal_rejects_concept_ids_not_in_search_or_current_spec(monkeypatch):
    monkeypatch.setattr("db.get_engine_for_resource", lambda _rid: object())
    tools = {fn.__name__: fn for fn in cohort_agent.build_tools(
        "aurora-resource", INFO, None, {})}
    result = json.loads(tools["propose_cohort"](json.dumps({
        "criteria": [{"domain": "condition", "concept_ids": [999]}]}),
        "fabricated"))
    assert "error" in result
    assert "Search for concept IDs" in result["error"]


def test_count_reencodes_parsed_dates_before_omop_boundary(monkeypatch):
    monkeypatch.setattr("db.get_engine_for_resource", lambda _rid: object())

    def fake_count(_engine, _info, spec):
        # omop.count reparses the public JSON-compatible spec internally.
        return {"persons": len(cohort_agent.omop.parse_spec(spec)["criteria"])}

    monkeypatch.setattr(cohort_agent.omop, "count", fake_count)
    tools = {fn.__name__: fn for fn in cohort_agent.build_tools(
        "aurora-resource", INFO,
        {"criteria": [{"domain": "condition", "concept_ids": [123],
                       "start": "2020-01-01"}]}, {})}
    result = json.loads(tools["count_cohort"](json.dumps({
        "criteria": [{"domain": "condition", "concept_ids": [123],
                      "start": "2020-01-01"}]})))
    assert result == {"persons": 1}


def test_list_workflow_jobs_returns_only_bounded_operational_fields(monkeypatch):
    monkeypatch.setattr(cohort_agent.workflows, "list_jobs", lambda: {
        "available": True, "running_count": 1, "jobs": [{
            "run_id": "run-1", "name": "analysis", "status": "RUNNING",
            "status_message": "secret=do-not-return", "workflow_type": "NEXTFLOW"}]})
    out = json.loads({fn.__name__: fn for fn in cohort_agent.build_tools(
        "aurora-resource", INFO, None, {})}["list_workflow_jobs"]())
    assert out["jobs"][0]["run_id"] == "run-1"
    assert "status_message" not in out["jobs"][0]
    assert "secret" not in json.dumps(out)


def test_app_list_uses_fixed_read_only_command_and_projects_fields(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps([{
            "appId": "app-1", "displayName": "Cohort Studio",
            "status": "RUNNING", "ownerEmail": "user@example.org",
            "accessToken": "must-not-leak"}]), stderr="")

    monkeypatch.setattr(workbench_apps.subprocess, "run", fake_run)
    out = workbench_apps.list_apps()
    assert out["apps"] == [{"id": "app-1", "name": "Cohort Studio",
                            "status": "RUNNING", "config": None,
                            "owner": "user@example.org", "workspace_id": None}]
    assert "must-not-leak" not in json.dumps(out)
    assert calls[0][0] == ["wb", "app", "list", "--format", "JSON"]
    assert calls[0][1]["timeout"] <= 20
    assert calls[0][1]["check"] is True


def test_app_list_extracts_resource_id_from_proxy_url():
    app = workbench_apps._public_app({
        "displayName": "Cohort Studio",
        "proxyUrl": "https://workbench.example/app/123e4567-e89b-12d3-a456-426614174000/"})
    assert app["id"] == "123e4567-e89b-12d3-a456-426614174000"


def test_cohort_agent_endpoint_rejects_invalid_spec_with_400(monkeypatch):
    import config

    monkeypatch.setattr(main, "_omop_cdm", lambda _rid: (object(), INFO))
    monkeypatch.setattr(config, "get_llm_config", lambda: {
        "provider": "openrouter", "api_key": "key", "model": "model"})
    response = client.post("/api/omop/test-resource/cohort/agent", json={
        "message": "Build a cohort", "spec": {"unexpected": True}})
    assert response.status_code == 400
    assert "Unknown cohort spec key" in json.dumps(response.json()["detail"])


def test_cohort_agent_endpoint_reports_missing_config_400(monkeypatch):
    import config

    monkeypatch.setattr(main, "_omop_cdm", lambda _rid: (object(), INFO))
    monkeypatch.setattr(config, "get_llm_config", lambda: {
        "provider": "openrouter", "api_key": None, "model": "model"})
    recorded = []
    monkeypatch.setattr(main, "_record_turn", lambda *a, **k: recorded.append(k))
    response = client.post("/api/omop/test-resource/cohort/agent", json={
        "message": "Build a cohort"})
    assert response.status_code == 400
    assert "No OpenRouter API key" in response.json()["detail"]
    assert recorded[-1]["status"] == "unconfigured"


def test_cohort_agent_endpoint_records_telemetry_and_returns_result(monkeypatch):
    monkeypatch.setattr(main, "_omop_cdm", lambda _rid: (object(), INFO))
    monkeypatch.setattr(cohort_agent, "chat", lambda rid, info, message,
                        history, spec: {
                            "reply": "Proposed asthma cohort.",
                            "spec": {"criteria": []}, "count": None,
                            "reason": "asthma", "provider": "openrouter",
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
        ("/api/omop/test-resource/cohort/count",
         {"require_observation": "false"}),
        ("/api/omop/test-resource/cohort/open",
         {"spec": {}, "name": "", "unexpected": True}),
        ("/api/omop/test-resource/domain/open",
         {"table": "person", "concept_names": "false"}),
        ("/api/omop/test-resource/cohort/agent",
         {"message": "   "}),
        ("/api/omop/test-resource/cohort/agent",
         {"message": "Build", "unexpected": True}),
    ]
    for path, body in cases:
        response = client.post(path, json=body)
        assert response.status_code == 400, (path, response.text)


def test_non_omop_request_validation_remains_422():
    response = client.post("/api/datasets/unknown/chat", json={})
    assert response.status_code == 422


def test_missing_provider_key_is_actionable(monkeypatch):
    import config
    import pytest

    monkeypatch.setattr(config, "get_llm_config", lambda: {
        "provider": "openrouter", "api_key": None, "model": "model"})
    with pytest.raises(llm.LLMNotConfigured, match="No OpenRouter API key"):
        cohort_agent.chat("aurora-resource", INFO, "Build a cohort")


def test_bedrock_uses_iam_helper_and_cohort_tool_schemas(monkeypatch):
    import agent
    import config

    monkeypatch.setattr("db.get_engine_for_resource", lambda _rid: object())
    monkeypatch.setattr(config, "get_llm_config", lambda: {
        "provider": "bedrock", "api_key": None, "model": "model-id",
        "region": "us-east-1"})
    called = {}

    def fake_bedrock(cfg, system, messages, tool_impls, tool_schemas):
        called.update(cfg=cfg, system=system, messages=messages,
                      tool_impls=tool_impls, tool_schemas=tool_schemas)
        return {"reply": "Ready to help.", "usage": {"total_tokens": 0}}

    monkeypatch.setattr(agent, "run_bedrock", fake_bedrock, raising=False)
    out = cohort_agent.chat("aurora-resource", INFO, "Help build a cohort")
    assert out["reply"] == "Ready to help."
    assert called["cfg"]["region"] == "us-east-1"
    assert called["tool_schemas"] is cohort_agent.COHORT_TOOL_SCHEMAS
    assert set(called["tool_impls"]) == {
        "search_concepts", "count_cohort", "propose_cohort",
        "list_workflow_jobs", "list_workbench_apps"}


def test_bedrock_requires_region_and_uses_display_label(monkeypatch):
    import config
    import pytest

    monkeypatch.setattr(config, "get_llm_config", lambda: {
        "provider": "bedrock", "api_key": None, "model": "model-id",
        "region": None})
    with pytest.raises(llm.LLMNotConfigured,
                       match="AWS region required; set AWS_REGION or AWS_DEFAULT_REGION"):
        cohort_agent.chat("aurora-resource", INFO, "Build a cohort")

    monkeypatch.setattr(config, "get_llm_config", lambda: {
        "provider": "bedrock", "api_key": None, "model": "",
        "region": "us-east-1"})
    with pytest.raises(llm.LLMNotConfigured,
                       match="No Amazon Bedrock model set"):
        cohort_agent.chat("aurora-resource", INFO, "Build a cohort")


def test_omop_nonfinite_validation_returns_json_400():
    from fastapi.testclient import TestClient
    import main
    response = TestClient(main.app).post(
        "/api/omop/example/cohort/count",
        content='{"demographics":{"age_min":NaN}}',
        headers={"content-type": "application/json"})
    assert response.status_code == 400
    assert "finite" in response.json()["detail"][0]["msg"]
