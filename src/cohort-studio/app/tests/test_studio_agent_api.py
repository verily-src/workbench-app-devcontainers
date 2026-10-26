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

def test_completed_workflow_results_verify_open_and_restore(workspace, monkeypatch, engine):
    import agent_results
    import agent_workflows
    import agent_sessions
    from fastapi import Request, Response
    from tests.test_agent_results import fixture_data, run_info, RESOURCE, BASE_URI, PUBDIR
    workspace.get("/api/agent/chat/history")
    request = Request({"type": "http", "headers": [(b"cookie", "; ".join(
        f"{k}={v}" for k, v in workspace.cookies.items()).encode())]})
    owner = agent_sessions.owner(request, Response())
    info = {"rows": 3, "columns": list(agent_workflows.REQUIRED_INPUT_COLUMNS), "capped": False}
    registry = lambda: {"available": True, "workflows": [{"id": "cohort-genetics-demo", "type": "NEXTFLOW"}]}
    plan = agent_workflows.prepare("fixture-dataset", "input", RESOURCE, [], owner,
        inspect_dataset=lambda *args: info, list_workflows=registry,
        resolve_s3_resource=lambda rid: BASE_URI if rid == RESOURCE else "s3://inputs")
    agent_workflows.approve(plan["id"], owner, inspect_dataset=lambda *args: info,
        export_cohort=lambda *args: {"rows": 3, "s3_uri": plan["input_uri"]},
        submit_workflow=lambda *args: run_info())
    monkeypatch.setattr(main, "datasources", lambda: {"sources": [{"kind": "s3", "id": RESOURCE}]})
    monkeypatch.setattr(main.workflows, "list_jobs", lambda **kw: {"jobs": [run_info()]})
    monkeypatch.setattr(main, "_lineage_engine", lambda: engine)
    manifest, keys, objects, calls, listing, reading = fixture_data()
    manifest["input"]["uri"] = plan["input_uri"]
    keys[PUBDIR + "run_manifest.json"] = json.dumps(manifest).encode()
    objects[0]["size"] = len(keys[PUBDIR + "run_manifest.json"])
    monkeypatch.setattr(agent_results, "_default_resolve", lambda rid: BASE_URI)
    monkeypatch.setattr(agent_results, "_default_list", listing)
    monkeypatch.setattr(agent_results, "_default_read", reading)
    monkeypatch.setattr(main, "_open_source", lambda *a, **kw: pytest.fail("must load the verified bytes"))
    url = f"/api/agent/workflows/{plan['id']}/results/open"
    response = workspace.post(url, json={})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["verification"]["verified"] and body["verification"]["rows"] == 3
    assert body["action"]["dataset"]["rows"] == 2
    assert "summary_csv" not in response.text
    did = body["action"]["dataset"]["dataset_id"]
    query = workspace.post(f"/api/datasets/{did}/query", json={}).json()
    column = query["rows"]["columns"].index("people")
    assert sum(row[column] for row in query["rows"]["data"]) == 3
    restored = workspace.get("/api/agent/workflows").json()["plans"]
    assert restored[0]["id"] == plan["id"] and restored[0]["status"] == "completed"
    outsider = TestClient(main.app)
    assert outsider.get("/api/agent/workflows").json()["plans"] == []
    assert outsider.post(url, json={}).status_code == 404
    manifest["outputs_sha256"]["carrier_summary_csv"] = "0" * 64
    keys[PUBDIR + "run_manifest.json"] = json.dumps(manifest).encode()
    objects[0]["size"] = len(keys[PUBDIR + "run_manifest.json"])
    before = len(agent_mode_api._dashboards)
    rejected = workspace.post(url, json={})
    assert rejected.status_code == 400 and "checksum" in rejected.text
    assert len(agent_mode_api._dashboards) == before

def test_pending_workflow_reopens_aurora_source_after_restart(workspace, monkeypatch, engine):
    import agent_sessions
    import agent_workflows
    from fastapi import Request, Response
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("""CREATE TABLE cdm.workflow_input AS
            SELECT person_id, 's' || person_id AS sample_id,
            'SYN_VAR_0021'::text AS variant_id, 1::integer AS dosage,
            gender_concept_id, year_of_birth FROM cdm.person"""))
    workspace.get("/api/agent/chat/history")
    request = Request({"type": "http", "headers": [(b"cookie", "; ".join(
        f"{k}={v}" for k,v in workspace.cookies.items()).encode())]})
    owner = agent_sessions.owner(request, Response())
    monkeypatch.setattr(main, "tables", lambda *args: [
        {"name": "cdm.workflow_input", "schema": "cdm", "table": "workflow_input"}])
    ops = agent_mode_api.Operations(owner)
    ref = {"kind": "aurora", "resource_id": "omopdb", "schema": "cdm", "table": "workflow_input"}
    ops.inspect_table(json.dumps(ref))
    built = ops.build_dashboard(json.dumps(ref), "Workflow inputs")
    did = built["dataset_id"]
    plan = agent_workflows.prepare(did, "input", "output", [], owner,
        inspect_dataset=lambda d,f: agent_mode_api._inspect_dataset(owner,d,f),
        list_workflows=lambda: {"available": True, "workflows": [{"id":"cohort-genetics-demo", "type":"NEXTFLOW"}]},
        resolve_s3_resource=lambda rid: "s3://bucket/" + rid)
    assert plan["status"] == "ready", plan
    main.datasets.close_dataset(did)
    agent_mode_api._dashboards.clear()
    calls = []
    def export(frame, rid, path):
        calls.append("export")
        assert len(frame) == 100 and list(frame.columns) == list(agent_workflows.REQUIRED_INPUT_COLUMNS)
        return {"rows":100, "s3_uri": plan["input_uri"]}
    monkeypatch.setattr(main.workflows, "export_cohort_csv", export)
    monkeypatch.setattr(main, "submit_workflow", lambda req: calls.append("submit") or {"run_id":"restored-run"})
    monkeypatch.setattr(main, "_lineage_engine", lambda: engine)
    response = workspace.post(f"/api/agent/workflows/{plan['id']}/approve", json={})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "submitted", response.json()
    assert calls == ["export", "submit"]
    assert not agent_mode_api._dashboards
