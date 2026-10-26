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


def test_agent_counts_demographics_and_dated_events_against_database(workspace):
    import omop
    ops = agent_mode_api.Operations("count-validation-owner")
    engine, info = main._omop_cdm("omopdb")
    demo = {"criteria": [], "require_observation": True,
            "demographics": {"gender_concept_ids": [8532],
                             "year_of_birth_min": 1930, "year_of_birth_max": 1950}}
    assert ops.count_cohort("omopdb", json.dumps(demo)) == omop.count(engine, info, demo)
    concepts = ops.search_concepts("omopdb", "192671", "condition")["concepts"]
    assert any(c["concept_id"] == 192671 for c in concepts)
    dated = {"criteria": [{"domain": "condition", "concept_ids": [192671],
                           "start": "1900-01-01", "end": "2100-01-01"}]}
    result = ops.count_cohort("omopdb", json.dumps(dated))
    assert result == omop.count(engine, info, dated)
    assert result["persons"] == 40


def test_agent_rejects_filters_instead_of_silently_broadening_cohort(workspace):
    ops = agent_mode_api.Operations("filter-validation-owner")
    ref = {"kind": "aurora", "resource_id": "omopdb", "schema": "cdm", "table": "person"}
    ops.inspect_table(json.dumps(ref))
    built = ops.build_dashboard(json.dumps(ref), "People")
    for filters in [
        [{"column": "unknown_column", "kind": "categorical", "values": ["8532"]}],
    ]:
        with pytest.raises(ValueError, match="no filters were applied"):
            ops.query_dashboard(built["dataset_id"], json.dumps(filters))
    with pytest.raises(ValueError, match="Extra inputs"):
        ops.query_dashboard(built["dataset_id"], json.dumps([
            {"column": "year_of_birth", "kind": "range", "operator": "<", "value": 1950}]))
    assert ops.query_dashboard(built["dataset_id"])["filtered"] == 100


def test_agent_filters_high_cardinality_ids_without_dropdown_membership(workspace):
    from sqlalchemy import text
    ops = agent_mode_api.Operations("identifier-filter-owner")
    ref = {"kind": "aurora", "resource_id": "omopdb", "schema": "cdm", "table": "person"}
    ops.inspect_table(json.dumps(ref))
    built = ops.build_dashboard(json.dumps(ref), "People")
    engine, _ = main._omop_cdm("omopdb")
    with engine.connect() as conn:
        selected = str(conn.execute(text("SELECT person_id FROM cdm.person ORDER BY person_id DESC LIMIT 1")).scalar_one())
    filters = [{"column": "person_id", "kind": "categorical", "values": [selected]}]
    result = ops.query_dashboard(built["dataset_id"], json.dumps(filters))
    assert result["filtered"] == 1
    assert str(result["rows"]["data"][0][result["rows"]["columns"].index("person_id")]) == selected
    missing = [{"column": "person_id", "kind": "categorical", "values": ["not-a-person"]}]
    assert ops.query_dashboard(built["dataset_id"], json.dumps(missing))["filtered"] == 0


def test_agent_omop_dashboard_preserves_demographic_concept_ids(workspace):
    ops = agent_mode_api.Operations("omop-identifiers-owner")
    ref = {"kind": "omop_cohort", "resource_id": "omopdb", "membership_mode": "live",
           "spec": {"criteria": [], "require_observation": True}}
    built = ops.build_dashboard(json.dumps(ref), "OMOP people")
    names = {c["name"] for c in built["columns"]}
    assert {"gender", "gender_concept_id", "race_concept_id", "ethnicity_concept_id"} <= names
    result = ops.query_dashboard(built["dataset_id"])
    assert result["filtered"] == 100


def test_projected_omop_genetics_join_prepares_complete_workflow(workspace, monkeypatch, engine):
    from sqlalchemy import text
    import agent_workflows
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE cdm.agent_samples AS SELECT person_id, 'sample_' || person_id AS sample_id FROM cdm.person ORDER BY person_id LIMIT 5"))
        conn.execute(text("CREATE TABLE cdm.agent_genotypes AS SELECT sample_id, v.variant_id, 1 AS dosage FROM cdm.agent_samples CROSS JOIN (VALUES ('SYN_VAR_0021'), ('OTHER_VARIANT')) AS v(variant_id)"))
        conn.execute(text("CREATE TABLE cdm.agent_variants AS SELECT DISTINCT variant_id, 'SYN_GENE'::text AS gene FROM cdm.agent_genotypes"))
    tables = ["person", "agent_samples", "agent_genotypes", "agent_variants"]
    monkeypatch.setattr(main, "tables", lambda *args: [
        {"name": "cdm." + name, "schema": "cdm", "table": name} for name in tables])
    monkeypatch.setattr(main, "datasources", lambda: {"sources": [
        {"kind": "aurora", "id": "omopdb"}, {"kind": "s3", "id": "input"}, {"kind": "s3", "id": "output"}]})
    monkeypatch.setattr(main.workflows, "list_workflows", lambda: {"available": True, "workflows": [
        {"id": "cohort-genetics-demo", "type": "NEXTFLOW"}]})
    monkeypatch.setattr(agent_mode_api.db, "resolve_s3_uri", lambda rid: "s3://test-bucket/" + rid)
    ops = agent_mode_api.Operations("projected-workflow-owner")
    refs = {name: {"kind": "aurora", "resource_id": "omopdb", "schema": "cdm", "table": name} for name in tables}
    for ref in refs.values():
        ops.inspect_table(json.dumps(ref))
    source = {"kind": "join", "base": {"kind": "omop_cohort", "resource_id": "omopdb",
              "membership_mode": "live", "spec": {}}, "steps": []}
    for name, alias, left, right, columns in [
        ("agent_samples", "samples", "person_id", "person_id", ["sample_id"]),
        ("agent_genotypes", "genotypes", "samples → sample_id", "sample_id", ["variant_id", "dosage"]),
        ("agent_variants", "variants", "genotypes → variant_id", "variant_id", ["gene"]),
    ]:
        source["steps"].append({"source": refs[name], "alias": alias, "how": "inner", "columns": columns,
                                "conditions": [{"left": left, "op": "=", "right": right}]})
    filters = [{"column": "genotypes → variant_id", "kind": "categorical", "values": ["SYN_VAR_0021"]}]
    built = ops.build_dashboard(json.dumps(source), "Projected genetics", filters_json=json.dumps(filters))
    assert built["total"] == 10 and built["filtered"] == 5
    distinct = ops.query_dashboard(built["dataset_id"], entity_column="person_id")
    assert distinct["entity"] == {"column": "person_id", "total": 5, "filtered": 5}
    assert ops.actions[0]["dataset"]["query_scope"] == "database"
    plan = ops.prepare_workflow(built["dataset_id"], "input", "output")
    assert plan["status"] == "ready", plan
    assert plan["rows"] == 5
    assert set(plan["column_mapping"]) == set(agent_workflows.REQUIRED_INPUT_COLUMNS)
    assert plan["column_mapping"]["sample_id"] == "samples → sample_id"
    assert plan["column_mapping"]["variant_id"] == "genotypes → variant_id"

    import agent_runtime
    import agent_sessions
    import studio_agent
    from langchain_core.messages import AIMessage
    model_calls = []
    def provider(_provider, _model, _key, _base, system, messages, impls, **kwargs):
        def model_call(*args):
            model_calls.append(1)
            assert len(model_calls) == 1, "No paid model call is needed after the ready plan"
            return AIMessage(content="", tool_calls=[
                {"name": "prepare_workflow", "id": "prepare", "args": {
                    "dataset_id": built["dataset_id"], "input_resource_id": "input", "output_resource_id": "output"}},
                {"name": "list_sources", "id": "unnecessary", "args": {}},
            ])
        return agent_runtime.run("openai", "test", system, messages, impls,
                                 kwargs["tool_schemas"], model_call, on_step=kwargs.get("on_step"), max_turns=1)
    monkeypatch.setattr(providers, "run", provider)
    with agent_sessions.bind(ops.owner, "workspace:agent-mode", None):
        reply = studio_agent.chat("Prepare this workflow and stop for approval", ops.callbacks())
        agent_sessions.finish(reply)
    assert reply["completion_reason"] == "approval_required"
    assert reply["run_status"] == "completed"
    assert not reply["limit_reached"]
    assert reply["tool_calls"] == ["prepare_workflow"]
    assert "No workflow has been submitted" in reply["reply"]
    assert ops.workflow_plans[-1]["status"] == "ready"
    with store_module.AgentStore().engine.connect() as conn:
        status = conn.execute(text("SELECT status FROM _studio_agent.runs WHERE run_id=:id"),
                              {"id": reply["trace_id"]}).scalar_one()
    assert status == "completed"
    with store_module.AgentStore().engine.connect() as conn:
        boundary = conn.execute(text("SELECT count(*) FROM _studio_agent.events WHERE run_id=:id AND kind='approval_required'"),
                                {"id": reply["trace_id"]}).scalar_one()
    assert boundary == 1


def test_agent_literature_tools_return_citations_and_preserve_history(workspace, monkeypatch):
    import literature
    calls = []
    monkeypatch.setattr(config, "get_ncbi_api_key", lambda: "private-ncbi-key")
    def pubmed(query, limit=5, api_key=""):
        calls.append((query, limit, api_key))
        return {"articles": [{"title": "Example study", "pmid": "123", "url": "https://pubmed.ncbi.nlm.nih.gov/123/"}]}
    monkeypatch.setattr(literature, "search_pubmed", pubmed)
    monkeypatch.setattr(literature, "search_biorxiv", lambda query, start_date, end_date, limit=5: {
        "articles": [], "coverage": "bounded date-window scan"})
    def provider(provider, model, api_key, base_url, system, messages, impls, **kwargs):
        assert "untrusted data" in system and "preprints" in system
        result = json.loads(impls["search_pubmed"](query="genetic association", limit=3))
        assert result["articles"][0]["pmid"] == "123"
        assert "private-ncbi-key" not in json.dumps(result)
        preprints = json.loads(impls["search_biorxiv"](query="genetics", start_date="2026-01-01", end_date="2026-01-02"))
        assert "bounded" in preprints["coverage"]
        return {"reply": "Found [Example study](https://pubmed.ncbi.nlm.nih.gov/123/).", "usage": {}, "tool_calls": ["search_pubmed", "search_biorxiv"]}
    monkeypatch.setattr(providers, "run", provider)
    response = workspace.post("/api/agent/chat", json={"message": "Find genetics literature on genetic association"})
    assert response.status_code == 200, response.text
    assert calls == [("genetic association", 3, "private-ncbi-key")]
    assert response.json()["actions"] == []
    history = workspace.get("/api/agent/chat/history").json()
    assert history["messages"][-1]["content"] == response.json()["reply"]
    assert "private-ncbi-key" not in response.text + json.dumps(history)
