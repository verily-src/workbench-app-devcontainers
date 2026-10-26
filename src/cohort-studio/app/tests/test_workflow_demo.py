import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def _demo_frame(extra=False):
    data = {
        "person_id": [1, 2], "sample_id": ["s1", "s2"],
        "variant_id": ["SYN_VAR_0021", "SYN_VAR_0021"],
        "dosage": [0, 1], "gender_concept_id": [8507, 8532],
        "year_of_birth": [1970, 1980],
    }
    if extra:
        data["gene_symbol"] = ["synthetic", "synthetic"]
    return pd.DataFrame(data)


def test_demo_export_projects_exact_workflow_columns(monkeypatch):
    opened = main.datasets.open_dataset(
        _demo_frame(extra=True), "genetics demo cohort")
    exported = {}
    monkeypatch.setattr(main.workflows, "export_cohort_csv",
                        lambda frame, resource, path: exported.update(
                            frame=frame.copy(), resource=resource, path=path)
                        or {"s3_uri": "s3://cohort/input.csv", "rows": len(frame),
                            "resource_id": resource, "path": path})
    monkeypatch.setattr(main.lineage, "record", lambda *args, **kwargs: None)
    try:
        response = client.post(
            f"/api/datasets/{opened['dataset_id']}/export-cohort", json={
                "resource_id": "cohort-input", "path": "demo/input.csv",
                "filters": [], "workflow": "cohort-genetics-demo",
            })
        assert response.status_code == 200, response.text
        assert list(exported["frame"].columns) == [
            "person_id", "sample_id", "variant_id", "dosage",
            "gender_concept_id", "year_of_birth"]
        assert response.json()["rows"] == 2
    finally:
        main.datasets.close_dataset(opened["dataset_id"])


def test_demo_export_requires_all_input_columns(monkeypatch):
    opened = main.datasets.open_dataset(
        _demo_frame().drop(columns=["sample_id"]), "incomplete cohort")
    monkeypatch.setattr(main.workflows, "export_cohort_csv",
                        lambda *args: pytest.fail("invalid shape must not export"))
    try:
        response = client.post(
            f"/api/datasets/{opened['dataset_id']}/export-cohort", json={
                "resource_id": "cohort-input", "path": "demo/input.csv",
                "filters": [], "workflow": "cohort-genetics-demo",
            })
        assert response.status_code == 400
        assert "sample_id" in response.json()["detail"]
    finally:
        main.datasets.close_dataset(opened["dataset_id"])


def test_demo_export_rejects_capped_dataset(monkeypatch):
    opened = main.datasets.open_dataset(
        _demo_frame(), "capped cohort", capped=True)
    monkeypatch.setattr(main, "_export_frame",
                        lambda *args: pytest.fail("capped dataset must not export"))
    try:
        response = client.post(
            f"/api/datasets/{opened['dataset_id']}/export-cohort", json={
                "resource_id": "cohort-input", "path": "demo/input.csv",
                "filters": [], "workflow": "cohort-genetics-demo",
            })
        assert response.status_code == 413
        assert "uncapped" in response.json()["detail"]
    finally:
        main.datasets.close_dataset(opened["dataset_id"])


def test_demo_export_rejects_synchronous_row_limit(monkeypatch):
    monkeypatch.setattr(main.queries, "ROW_CAP", 2)
    opened = main.datasets.open_dataset(
        _demo_frame(), "limit-sized cohort", capped=False)
    monkeypatch.setattr(main.workflows, "export_cohort_csv",
                        lambda *args: pytest.fail("row limit must not export"))
    try:
        response = client.post(
            f"/api/datasets/{opened['dataset_id']}/export-cohort", json={
                "resource_id": "cohort-input", "path": "demo/input.csv",
                "filters": [], "workflow": "cohort-genetics-demo",
            })
        assert response.status_code == 413
        assert "synchronous row limit" in response.json()["detail"]
    finally:
        main.datasets.close_dataset(opened["dataset_id"])


def test_demo_export_rejects_unsafe_object_path(monkeypatch):
    opened = main.datasets.open_dataset(
        _demo_frame(), "valid cohort", capped=False)
    monkeypatch.setattr(main, "_export_frame",
                        lambda *args: pytest.fail("invalid path must reject first"))
    try:
        response = client.post(
            f"/api/datasets/{opened['dataset_id']}/export-cohort", json={
                "resource_id": "cohort-input", "path": "cohort-studio/../escape.csv",
                "filters": [], "workflow": "cohort-genetics-demo",
            })
        assert response.status_code == 400
        assert response.json()["detail"] == "S3 object path is invalid."
    finally:
        main.datasets.close_dataset(opened["dataset_id"])


def test_demo_submit_writes_params_then_submits_nextflow(monkeypatch):
    calls = {}
    monkeypatch.setattr(main.db, "resolve_s3_uri", lambda resource: {
        "input-resource": "s3://input-bucket/base",
        "output-resource": "s3://output-bucket/results",
    }[resource])

    def write_params(resource_id, path, params):
        calls["params"] = (resource_id, path, params)
        return {"s3_uri": f"s3://input-bucket/base/{path}"}

    def submit(**kwargs):
        calls["submit"] = kwargs
        return {"run_id": "run-1", "name": "genetics-demo", "status": "PENDING"}

    monkeypatch.setattr(main.workflows, "write_params_json", write_params)
    monkeypatch.setattr(main.workflows, "submit_job", submit)
    monkeypatch.setattr(main.lineage, "record", lambda *args, **kwargs: None)

    response = client.post("/api/workflows/submit", json={
        "workflow": "cohort-genetics-demo",
        "output_bucket_id": "output-resource", "job_id": "genetics-demo",
        "params_file_bucket_id": "input-resource",
        "params_file_path": "cohort-studio/params/run-1.json",
        "demo_input_resource_id": "input-resource",
        "demo_input_csv_path": "cohort-studio/cohort.csv",
        "demo_output_path": "cohort-studio/genetics-demo/run-1",
    })

    assert response.status_code == 200, response.text
    resource, path, params = calls["params"]
    assert resource == "input-resource"
    assert path == "cohort-studio/params/run-1.json"
    assert params == {
        "input": "s3://input-bucket/base/cohort-studio/cohort.csv",
        "input_uri": "s3://input-bucket/base/cohort-studio/cohort.csv",
        "variant_id": "SYN_VAR_0021",
        "output_bucket": "output-bucket",
        "output_key": "results/cohort-studio/genetics-demo/run-1/genetics-demo",
        "workflow_id": "cohort-genetics-demo",
    }
    assert calls["submit"] == {
        "workflow": "cohort-genetics-demo",
        "output_bucket_id": "output-resource", "job_id": "genetics-demo",
        "profile": "healthomics",
        "output_path": "cohort-studio/genetics-demo/run-1",
        "params_file_bucket_id": "input-resource",
        "params_file_path": "cohort-studio/params/run-1.json",
    }


@pytest.mark.parametrize("job_id", ["", "../escape", "nested/run", "bad name"])
def test_demo_submit_requires_safe_single_segment_job_id(job_id):
    response = client.post("/api/workflows/submit", json={
        "workflow": "cohort-genetics-demo", "output_bucket_id": "output-resource",
        "job_id": job_id,
        "params_file_bucket_id": "input-resource", "params_file_path": "params.json",
        "demo_input_resource_id": "input-resource",
        "demo_input_csv_path": "cohort.csv", "demo_output_path": "results/run-1",
    })
    assert response.status_code == 422
    assert "safe path segment" in response.text


def test_regular_workflow_uses_real_submit_helper_without_demo_fields(monkeypatch):
    import workflows

    captured = {}

    class Result:
        returncode = 0
        stdout = json.dumps({"runId": "regular-1", "displayName": "regular",
                             "status": "PENDING"})
        stderr = ""

    def fake_run(args, **kwargs):
        captured["args"] = args
        return Result()

    monkeypatch.setattr(workflows.subprocess, "run", fake_run)
    monkeypatch.setattr(workflows, "_bucket_map", lambda: {})
    monkeypatch.setattr(main.lineage, "record", lambda *args, **kwargs: None)
    response = client.post("/api/workflows/submit", json={
        "workflow": "hello_world", "output_bucket_id": "output-resource",
        "job_id": "regular-run", "batch_input_bucket_id": "input-resource",
        "batch_input_csv_path": "cohort/input.csv",
        "column_mapping": "main.input=sample_id",
    })

    assert response.status_code == 200, response.text
    args = captured["args"]
    assert args[args.index("--workflow") + 1] == "hello_world"
    assert args[args.index("--batch-input-bucket-id") + 1] == "input-resource"
    assert args[args.index("--batch-input-csv-path") + 1] == "cohort/input.csv"
    assert args[args.index("--column-mapping") + 1] == "main.input=sample_id"


@pytest.mark.parametrize("extra", [
    {"params_file_bucket_id": "input-resource"},
    {"batch_input_bucket_id": "input-resource",
     "batch_input_csv_path": "cohort.csv",
     "params_file_bucket_id": "input-resource",
     "params_file_path": "params.json"},
    {"params_file_bucket_id": "other-resource",
     "params_file_path": "params.json"},
])
def test_demo_submit_rejects_incomplete_or_mixed_inputs(extra):
    body = {
        "workflow": "cohort-genetics-demo", "output_bucket_id": "output-resource",
        "demo_input_resource_id": "input-resource",
        "demo_input_csv_path": "cohort.csv", "demo_output_path": "results/run-1",
        **extra,
    }
    response = client.post("/api/workflows/submit", json=body)
    assert response.status_code == 422


def test_workflow_params_upload_uses_resource_profile(monkeypatch):
    try:
        import database
    except ModuleNotFoundError:
        import db as database
    import workflows

    captured = {}
    monkeypatch.setattr(database, "resolve_s3_uri",
                        lambda resource: f"s3://{resource}/root")

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return Result()

    monkeypatch.setattr(workflows.subprocess, "run", fake_run)
    params = {"input": "s3://input/data.csv", "variant_id": "SYN_VAR_0021"}
    result = workflows.write_params_json(
        "input-resource", "cohort-studio/params/run.json", params)

    assert result["s3_uri"] == "s3://input-resource/root/cohort-studio/params/run.json"
    assert captured["args"] == [
        "aws", "s3", "cp", "-", result["s3_uri"], "--profile",
        "input-resource", "--content-type", "application/json"]
    assert json.loads(captured["kwargs"]["input"]) == params


def test_workflow_submit_rejects_mixed_batch_and_params(monkeypatch):
    import workflows

    monkeypatch.setattr(workflows.subprocess, "run",
                        lambda *args, **kwargs: pytest.fail("must reject before CLI"))
    with pytest.raises(ValueError, match="cannot be combined"):
        workflows.submit_job(
            "workflow", "output", batch_input_bucket_id="input",
            batch_input_csv_path="cohort.csv", params_file_bucket_id="input",
            params_file_path="params.json")


def test_demo_rejects_definition_uri_overflow_before_writes_or_submission(monkeypatch):
    monkeypatch.setattr(main.db, "resolve_s3_uri", lambda _: "s3://bucket/" + "x" * 230)
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid output path must not write params or submit a job")
    monkeypatch.setattr(main.workflows, "write_params_json", forbidden)
    monkeypatch.setattr(main.workflows, "submit_job", forbidden)
    response = client.post("/api/workflows/submit", json={
        "workflow": "cohort-genetics-demo", "output_bucket_id": "output",
        "job_id": "test", "params_file_bucket_id": "input",
        "params_file_path": "params.json", "demo_input_resource_id": "input",
        "demo_input_csv_path": "cohort.csv", "demo_output_path": "results",
    })
    assert response.status_code == 400, response.text
    assert "maximum 256" in response.json()["detail"]
