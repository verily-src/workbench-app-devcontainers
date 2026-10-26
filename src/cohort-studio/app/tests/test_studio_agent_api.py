import json

import pytest
from fastapi.testclient import TestClient

import agent_mode_api
import agent_store as store_module
import config
import main
import providers
from tests.test_agent_store import agent_store


@pytest.fixture
def workspace(client, agent_store, monkeypatch):
    monkeypatch.setattr(store_module, "AgentStore", lambda: agent_store)
    monkeypatch.setattr(config, "get_llm_config", lambda: {
        "provider": "openai", "model": "test", "api_key": "not-real", "base_url": None})
    monkeypatch.setattr(main, "datasources", lambda: {"ready": True, "sources": [
        {"kind": "aurora", "id": "omopdb"}]})
    monkeypatch.setattr(main, "tables", lambda kind, resource_id: [
        {"name": "cdm.person", "table": "person", "schema": "cdm", "detail": "table"}])
    agent_mode_api._dashboards.clear()
    return client


def test_agent_inspects_builds_queries_and_restores_owner_history(workspace, monkeypatch):
    calls = []
    def provider(provider, model, api_key, base_url, system, messages, impls, **kwargs):
        calls.append(messages)
        sources = json.loads(impls["list_sources"]())
        assert sources["sources"] == [{"kind": "aurora", "id": "omopdb"}]
        ref = {"kind": "aurora", "resource_id": "omopdb", "schema": "cdm", "table": "person"}
        inspected = json.loads(impls["inspect_table"](source_json=json.dumps(ref)))
        assert inspected["metadata"]["columns"]
        built = json.loads(impls["build_dashboard"](source_json=json.dumps(ref), title="People",
            charts_json='[{"kind":"bar","x":"gender_concept_id"}]', filters_json="[]"))
        assert built["total"] == 100, built
        result = json.loads(impls["query_dashboard"](dataset_id=built["dataset_id"], filters_json="[]", charts_json="[]"))
        assert result["total"] == 100 and len(result["rows"]["data"]) <= 5
        assert "submit_workflow" not in impls
        return {"reply": "Built a 100-person dashboard.", "usage": {},
                "tool_calls": ["inspect_table", "build_dashboard", "query_dashboard"]}
    monkeypatch.setattr(providers, "run", provider)
    first = workspace.post("/api/agent/chat", json={"message": "Build a people dashboard"})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["actions"][0]["dataset"]["query_scope"] == "database"
    history = workspace.get("/api/agent/chat/history").json()
    assert history["messages"][-1]["content"] == body["reply"]
    second = workspace.post("/api/agent/chat", json={"message": "Build another", "session_id": body["session_id"]})
    assert second.status_code == 200, second.text
    assert any(m["content"] == "Built a 100-person dashboard." for m in calls[1])
    outsider = TestClient(main.app)
    response = outsider.get("/api/agent/chat/history", params={"session_id": body["session_id"]})
    assert response.status_code in (403, 404)
    with pytest.raises(ValueError, match="your Agent session"):
        agent_mode_api._owned("different-owner", body["actions"][0]["dataset"]["dataset_id"])


def test_agent_blocks_unknown_uninspected_internal_and_sql_sources(workspace):
    ops = agent_mode_api.Operations("test-owner")
    ref = {"kind": "aurora", "resource_id": "omopdb", "schema": "cdm", "table": "person"}
    with pytest.raises(ValueError, match="Inspect"):
        ops.build_dashboard(json.dumps(ref), "Uninspected")
    with pytest.raises(ValueError, match="Internal"):
        ops.inspect_table(json.dumps({**ref, "table": "_agent_session"}))
    with pytest.raises(ValueError, match="datasource"):
        ops.inspect_table(json.dumps({**ref, "resource_id": "not-listed"}))
    with pytest.raises(ValueError, match="raw SQL"):
        ops.build_dashboard(json.dumps({"kind": "sql", "resource_id": "omopdb", "sql": "SELECT 1"}), "SQL")
    with pytest.raises(ValueError, match="Search concepts"):
        ops.count_cohort("omopdb", json.dumps({"criteria": [{"domain": "condition", "concept_ids": [192671]}]}))
    assert workspace.post("/api/agent/chat", json={"message": "test", "approval": True}).status_code == 422
    assert workspace.post("/api/agent/workflows/unknown/approve", json={}).status_code == 404

def test_joined_workflow_mapping_exports_and_approves_once(workspace, monkeypatch):
    import time
    import agent_sessions
    import agent_workflows
    import pandas as pd
    names = list(agent_workflows.REQUIRED_INPUT_COLUMNS)
    frame = pd.DataFrame([[1, "s1", "SYN_VAR_0021", 1, 8532, 1950]],
                         columns=["joined → " + name for name in names])
    opened = main.datasets.open_dataset(frame, "Joined genetics")
    workspace.get("/api/agent/chat/history")
    from fastapi import Request, Response
    owner_request = Request({"type": "http", "headers": [(b"cookie", "; ".join(
        f"{k}={v}" for k, v in workspace.cookies.items()).encode())]})
    owner = agent_sessions.owner(owner_request, Response())
    agent_mode_api._dashboards[opened["dataset_id"]] = {
        "owner": owner, "title": "Joined genetics", "source_ref": {}, "filters": [], "created": time.monotonic()}
    monkeypatch.setattr(main.workflows, "list_workflows", lambda: {"available": True, "workflows": [
        {"id": "cohort-genetics-demo", "type": "NEXTFLOW"}]})
    monkeypatch.setattr(agent_mode_api.db, "resolve_s3_uri", lambda rid: "s3://test-bucket/" + rid)
    plan = agent_workflows.prepare(opened["dataset_id"], "input", "output", [], owner,
        inspect_dataset=lambda did, f: agent_mode_api._inspect_dataset(owner, did, f),
        list_workflows=main.workflows.list_workflows, resolve_s3_resource=agent_mode_api.db.resolve_s3_uri)
    assert plan["status"] == "ready", plan
    calls = []
    def exported(data, rid, path):
        assert list(data.columns) == names
        assert data.iloc[0]["sample_id"] == "s1"
        calls.append("export")
        return {"rows": 1, "s3_uri": "s3://test-bucket/input/" + path}
    monkeypatch.setattr(main.workflows, "export_cohort_csv", exported)
    monkeypatch.setattr(main, "_lineage_engine", lambda: None)
    monkeypatch.setattr(main, "submit_workflow", lambda req: calls.append("submit") or {"run_id": "run-1"})
    url = f"/api/agent/workflows/{plan['id']}/approve"
    first = workspace.post(url, json={})
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "submitted", first.json()
    assert workspace.post(url, json={}).status_code == 200
    assert calls == ["export", "submit"]
    monkeypatch.setattr(main.workflows, "list_jobs", lambda force=False: {"jobs": [
        {"run_id": "run-1", "status": "COMPLETED"}]})
    refreshed = workspace.get(f"/api/agent/workflows/{plan['id']}/status")
    assert refreshed.status_code == 200
    assert refreshed.json()["status"] == "completed", refreshed.json()

def test_agent_builds_real_aurora_join_dashboard(workspace, monkeypatch):
    monkeypatch.setattr(main, "tables", lambda *args: [
        {"name": f"cdm.{table}", "table": table, "schema": "cdm"}
        for table in ("person", "drug_exposure")])
    ops = agent_mode_api.Operations("join-owner")
    base = {"kind": "aurora", "resource_id": "omopdb", "schema": "cdm", "table": "person"}
    right = {**base, "table": "drug_exposure"}
    ops.inspect_table(json.dumps(base))
    ops.inspect_table(json.dumps(right))
    result = ops.build_dashboard(json.dumps({"kind": "join", "base": base, "steps": [
        {"source": right, "how": "inner", "conditions": [
            {"left": "person_id", "op": "=", "right": "person_id"}], "alias": "drugs"}]}),
        "People and drugs", '[{"kind":"bar","x":"gender_concept_id"}]')
    assert result["total"] > 100
    assert ops.actions[0]["dataset"]["query_scope"] == "database"
    rows = ops.query_dashboard(result["dataset_id"])["rows"]
    assert len(rows["data"]) == 5
    assert "drugs → drug_concept_id" in rows["columns"]
