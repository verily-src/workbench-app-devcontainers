import json


def test_submit_nextflow_params_file_arguments(monkeypatch):
    import subprocess
    import workflows

    captured = {}

    class Result:
        returncode = 0
        stdout = json.dumps({"runId": "run-1", "displayName": "demo",
                             "status": "PENDING"})

    def fake_run(args, **kwargs):
        captured["args"] = args
        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(workflows, "_bucket_map", lambda: {})
    job = workflows.submit_job(
        workflow="demo-nextflow", output_bucket_id="output-resource",
        job_id="demo-run", output_path="demo/run-1",
        profile="test", params_file_bucket_id="input-resource",
        params_file_path="params/run-1.json")

    args = captured["args"]
    assert args[args.index("--output-path") + 1] == "demo/run-1"
    assert args[args.index("--params-file-bucket-id") + 1] == "input-resource"
    assert args[args.index("--params-file-path") + 1] == "params/run-1.json"
    assert args[args.index("--profile") + 1] == "test"
    assert "--batch-input-csv-path" not in args
    assert job["run_id"] == "run-1"


def test_registry_accepts_cli_type_field(monkeypatch):
    import subprocess
    import workflows

    class Result:
        returncode = 0
        stdout = '[{"id":"demo-nextflow","displayName":"Demo",' \
                 '"type":"NEXTFLOW"}]'

    monkeypatch.setattr(workflows, "_registry_cache", None)
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: Result())
    result = workflows.list_workflows(force=True)

    assert result["available"] is True
    assert result["workflows"][0]["type"] == "NEXTFLOW"


def test_list_jobs_refreshes_resource_map_for_unmatched_output_uuid(monkeypatch):
    import workflows

    raw = [{"runId": "run-1", "status": "COMPLETED",
            "outputBucketUuid": "resource-uuid", "outputBucketPath": "demo/run-1"}]
    calls = []

    monkeypatch.setattr(workflows, "_cache", None)
    monkeypatch.setattr(workflows, "_run", lambda limit: raw)

    def bucket_map(refresh=False):
        calls.append(refresh)
        return ({"resource-uuid": {"id": "nextflow_outputs",
                                    "bucket_name": "bucket", "prefix": "prefix"}}
                if refresh else {})

    monkeypatch.setattr(workflows, "_bucket_map", bucket_map)
    result = workflows.list_jobs(force=True)

    assert calls == [False, True]
    assert result["jobs"][0]["output_bucket_resource"] == "nextflow_outputs"
