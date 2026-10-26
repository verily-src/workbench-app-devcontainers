import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
import zipfile

import duckdb
import pandas as pd
import pytest
from fastapi import Request, Response

import agent
import agent_mode_api
import agent_results
import agent_sessions
import agent_workflows
import datasets
import disk_data
import main
from tests.test_studio_agent_api import workspace
from tests.test_agent_store import agent_store


ROOT = Path(__file__).resolve().parents[2]


def test_omop_genetics_dictionary_nextflow_results_roundtrip(workspace, engine, ref,
                                                           tmp_path, monkeypatch, record_property):
    runner = os.environ.get("STUDIO_EVAL_NEXTFLOW")
    if not runner:
        pytest.skip("Set STUDIO_EVAL_NEXTFLOW to run the local Nextflow acceptance test.")
    flow = Path(os.environ.get("COHORT_TEST_APP", ROOT / "app")).parent / "workflows/cohort-genetics-demo"
    table = "eval_genetics_" + uuid.uuid4().hex[:10]
    opened = []
    jobs = []
    stored_params = {}
    output = tmp_path / "results"
    input_csv = tmp_path / "input.csv"
    dictionary = flow / "variant_dictionary.csv"
    sources = [{"kind": "aurora", "id": "omopdb"}] + [
        {"kind": "s3", "id": key} for key in ("input", "output", "dictionary")]
    monkeypatch.setattr(main, "datasources", lambda: {"sources": sources})
    monkeypatch.setattr(main, "_lineage_engine", lambda: None)
    monkeypatch.setattr(main.workflows, "list_workflows", lambda: {
        "available": True, "workflows": [{"id": agent_workflows.WORKFLOW_ID, "type": "NEXTFLOW"}]})
    monkeypatch.setattr(main.db, "resolve_s3_uri", lambda rid: f"s3://fixture/{rid}")
    monkeypatch.setattr(agent_mode_api.db, "resolve_s3_uri", lambda rid: f"s3://fixture/{rid}")
    monkeypatch.setattr(main.workflows, "list_jobs", lambda **kw: {"jobs": jobs})

    def post(path, body):
        response = workspace.post(path, json=body)
        assert response.status_code == 200, response.text
        result = response.json()
        if "dataset_id" in result:
            opened.append(result["dataset_id"])
        return result

    def s3_open(_ref):
        path = disk_data._new_path()
        con = duckdb.connect(path)
        con.execute("CREATE TABLE data AS SELECT * FROM read_csv_auto(?)", [str(dictionary)])
        frame = con.execute("SELECT * FROM data").df()
        con.close()
        return frame, {"path": path, "table": "data", "columns": list(frame.columns),
                       "rows": len(frame), "estimated_bytes": Path(path).stat().st_size,
                       "scan_bytes": dictionary.stat().st_size, "large_warning": False}

    def export(frame, resource, path):
        frame.to_csv(input_csv, index=False)
        return {"s3_uri": f"s3://fixture/{resource}/{path}", "rows": len(frame)}

    def params(resource, path, value):
        stored_params.update(value)
        return {"s3_uri": f"s3://fixture/{resource}/{path}"}

    def submit(**kwargs):
        assert not jobs, "Duplicate workflow submission"
        vendor = tmp_path / "empty-vendor.zip"
        with zipfile.ZipFile(vendor, "w"):
            pass
        job_path = kwargs["output_path"] + "/" + kwargs["job_id"]
        prefix = "s3://fixture/output/" + job_path
        command = [runner, "-log", str(tmp_path / "nextflow.log"), "run", str(flow / "main.nf"),
                   "-profile", "local", "-work-dir", str(tmp_path / "work"),
                   "--input", str(input_csv), "--input_uri", stored_params["input_uri"],
                   "--variant_dictionary", str(dictionary), "--variant_dictionary_uri", "s3://fixture/dictionary/variant_dictionary.csv",
                   "--vendor_archive", str(vendor), "--python", sys.executable,
                   "--publish_dir", str(output), "--output_uri_prefix", prefix,
                   "--workflow_id", agent_workflows.WORKFLOW_ID, "--run_id", "local-eval-run"]
        run = subprocess.run(command, cwd=tmp_path, env={**os.environ, "NXF_OFFLINE": "true", "AWS_WORKFLOW_RUN_ID": "900001"},
                             capture_output=True, text=True, timeout=120)
        if run.returncode:
            pytest.fail(run.stdout + run.stderr)
        job = {"run_id": "local-eval-run", "status": "COMPLETED",
               "output_bucket_resource": "output", "output_bucket_path": job_path}
        jobs.append(job)
        return job

    monkeypatch.setattr(disk_data, "open_s3", s3_open)
    monkeypatch.setattr(main.workflows, "export_cohort_csv", export)
    monkeypatch.setattr(main.workflows, "write_params_json", params)
    monkeypatch.setattr(main.workflows, "submit_job", submit)
    with engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE TABLE public."{table}" AS SELECT person_id, '
            "'s' || person_id AS sample_id, 'SYN_VAR_0021'::text AS variant_id, "
            "mod(person_id, 3)::integer AS dosage FROM cdm.person")
    try:
        spec = {"criteria": [], "demographics": {"gender_concept_ids": [8532]}, "require_observation": True}
        expected = ref["person"].loc[lambda x: x.gender_concept_id == 8532]
        expected = expected[expected.person_id.isin(ref["observation_period"].person_id)]
        cohort = post("/api/omop/omopdb/cohort/open", {"spec": spec, "name": "Evaluation cohort"})
        assert cohort["rows"] == len(expected) > 0
        genetic = post("/api/datasets/open", {"source_ref": {"kind": "aurora", "resource_id": "omopdb", "schema": "public", "table": table}})
        joined = post("/api/datasets/join", {"base_id": cohort["dataset_id"], "steps": [{
            "right_id": genetic["dataset_id"], "how": "inner", "alias": "genetics",
            "columns": ["sample_id", "variant_id", "dosage"],
            "conditions": [{"left": "person_id", "op": "=", "right": "person_id"}]}]})
        assert joined["query_scope"] == "database"
        mapping = post("/api/datasets/open", {"source_ref": {"kind": "s3", "resource_id": "dictionary", "table": "variant_dictionary.csv"}})
        enriched = post("/api/datasets/join", {"base_id": joined["dataset_id"], "allow_loaded": True, "steps": [{
            "right_id": mapping["dataset_id"], "how": "inner", "alias": "annotation",
            "columns": ["gene_symbol", "consequence"],
            "conditions": [{"left": "genetics → variant_id", "op": "=", "right": "variant_id"}]}]})
        assert enriched["rows"] == len(expected)
        assert enriched["join"]["engine"] == "duckdb"
        assert enriched["join"]["complete_source"] is True
        workspace.get("/api/agent/chat/history")
        request = Request({"type": "http", "headers": [(b"cookie", "; ".join(
            f"{k}={v}" for k, v in workspace.cookies.items()).encode())]})
        owner = agent_sessions.owner(request, Response())
        did = enriched["dataset_id"]
        agent_mode_api._dashboards[did] = {"owner": owner, "title": "Enriched cohort",
            "source_ref": enriched["source_ref"], "filters": [], "created": time.monotonic()}
        ops = agent_mode_api.Operations(owner)
        plan = ops.prepare_workflow(did, "input", "output")
        assert plan["status"] == "ready" and plan["rows"] == len(expected), plan["errors"]
        assert not jobs and not input_csv.exists()
        url = f"/api/agent/workflows/{plan['id']}/approve"
        submitted = post(url, {})
        assert submitted["status"] == "submitted", submitted["errors"]
        post(url, {})
        assert len(jobs) == 1
        frame = pd.read_csv(input_csv)
        assert set(frame.person_id) == set(expected.person_id)
        assert list(frame.columns) == list(agent_workflows.REQUIRED_INPUT_COLUMNS)
        manifest = json.loads((output / "run_manifest.json").read_text())
        summary = pd.read_csv(output / "carrier_summary.csv")
        assert summary.groupby("carrier_status").people.sum().to_dict() == {
            "carrier": int((expected.person_id % 3 > 0).sum()),
            "noncarrier": int((expected.person_id % 3 == 0).sum())}
        objects = {uri.removeprefix("s3://fixture/"): output / Path(uri).name
                   for uri in manifest["outputs"].values()}
        monkeypatch.setattr(agent_results, "_default_resolve", lambda rid: "s3://fixture/output")
        monkeypatch.setattr(agent_results, "_default_list", lambda *args: [
            {"key": key, "size": path.stat().st_size} for key, path in objects.items()])
        monkeypatch.setattr(agent_results, "_default_read", lambda rid, bucket, key, limit: objects[key].read_bytes())
        result = post(f"/api/agent/workflows/{plan['id']}/results/open", {})
        assert result["verification"]["verified"] is True
        assert result["verification"]["rows"] == len(expected)
        result_id = result["action"]["dataset"]["dataset_id"]
        opened.append(result_id)
        query = post(f"/api/datasets/{result_id}/query", {"page_size": 100})
        idx = query["rows"]["columns"].index("people")
        assert sum(row[idx] for row in query["rows"]["data"]) == len(expected)
        assert result["action"]["charts"]
        tools = {fn.__name__: fn for fn in agent.build_tools(
            datasets.get(result_id)["df"], result["action"]["dataset"]["columns"], {"filters": [], "charts": []}, [])}
        totals = json.loads(tools["aggregate"](agg="sum", column="people", group_by="carrier_status"))
        expected_counts = {"carrier": int((expected.person_id % 3 > 0).sum()),
                           "noncarrier": int((expected.person_id % 3 == 0).sum())}
        assert totals["result"] == expected_counts
        record_property("cohort_people", len(expected))
        record_property("carrier_people", expected_counts["carrier"])
        record_property("noncarrier_people", expected_counts["noncarrier"])
        record_property("workflow_submissions", len(jobs))
        record_property("result_integrity", result["verification"]["integrity"])
        assert len(jobs) == 1
    finally:
        for did in reversed(opened):
            agent_mode_api._dashboards.pop(did, None)
            datasets.close_dataset(did)
        with engine.begin() as conn:
            conn.exec_driver_sql(f'DROP TABLE public."{table}"')
