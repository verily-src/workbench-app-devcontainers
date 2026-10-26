import uuid

import pytest

import agent_workflows as plans


def callbacks(*, rows=42, columns=None, capped=False, workflow_type="NEXTFLOW",
              input_uri="s3://input/cohort-studio", output_uri="s3://output/results"):
    columns = columns or list(plans.REQUIRED_INPUT_COLUMNS)
    return {
        "inspect_dataset": lambda _dataset_id, _filters: {
            "rows": rows, "columns": columns, "capped": capped},
        "list_workflows": lambda: {"available": True, "workflows": [
            {"id": plans.WORKFLOW_ID, "type": workflow_type}]},
        "resolve_s3_resource": lambda resource_id: {
            "input": input_uri, "output": output_uri}[resource_id],
    }


def prepare(owner="alice", **overrides):
    options = callbacks(**overrides)
    return plans.prepare("dataset-1", "input", "output", [
        {"column": "cohort", "op": "in", "values": ["case"]}], owner,
        **options)


def test_prepare_validates_workflow_resources_and_full_filtered_dataset():
    plan = prepare()
    assert plan["status"] == "ready"
    assert plan["workflow"] == "cohort-genetics-demo"
    assert plan["rows"] == 42
    assert plan["required_columns"] == list(plans.REQUIRED_INPUT_COLUMNS)
    assert plan["column_mapping"] == {
        column: column for column in plans.REQUIRED_INPUT_COLUMNS}
    assert plan["input_resource_id"] == "input"
    assert plan["output_resource_id"] == "output"
    assert plan["output_path"] == f"cohort-studio/agent-plans/{plan['id']}/results"
    assert plan["errors"] == []


@pytest.mark.parametrize("overrides,expected", [
    ({"capped": True}, "sampled or capped"),
    ({"columns": ["person_id"]}, "Required input columns are missing"),
    ({"workflow_type": "WDL"}, "not registered as Nextflow"),
    ({"input_uri": "https://example.test/data"}, "input resource must resolve"),
    ({"rows": 0}, "match no rows"),
    ({"rows": 100_000}, "synchronous export supports fewer"),
])
def test_prepare_returns_blocked_plan_with_reasons(overrides, expected):
    plan = prepare(**overrides)
    assert plan["status"] == "blocked"
    assert any(expected in error for error in plan["errors"])


def test_approval_exports_frozen_filters_submits_once_and_refreshes_exact_run():
    selected_filters = [{"column": "cohort", "op": "in", "values": ["case"]}]
    options = callbacks()
    plan = plans.prepare("dataset-1", "input", "output", selected_filters,
                         "alice", **options)
    selected_filters[0]["values"].append("control")
    calls = {"export": 0, "submit": 0}

    def export(dataset_id, resource_id, path, filters, column_mapping):
        calls["export"] += 1
        assert dataset_id == "dataset-1"
        assert resource_id == "input"
        assert path == f"cohort-studio/agent-plans/{plan['id']}/cohort.csv"
        assert filters == [{"column": "cohort", "op": "in", "values": ["case"]}]
        assert column_mapping == {
            column: column for column in plans.REQUIRED_INPUT_COLUMNS}
        return {"s3_uri": plan["input_uri"], "rows": 42,
                "person_id": "must not enter plan state"}

    def submit(*args):
        calls["submit"] += 1
        assert args == (
            plans.WORKFLOW_ID, "input",
            f"cohort-studio/agent-plans/{plan['id']}/cohort.csv",
            "output", f"cohort-studio/agent-plans/{plan['id']}/results",
            "input", f"cohort-studio/agent-plans/{plan['id']}/params.json",
            f"cohort-genetics-{plan['id'][:12]}")
        return {"run_id": "run-123", "name": "genetics-demo",
                "status": "PENDING", "output_bucket_resource": "output",
                "output_bucket_path": "results/job-123", "secret": "do-not-return"}

    result = plans.approve(plan["id"], "alice",
                           inspect_dataset=options["inspect_dataset"], export_cohort=export,
                           submit_workflow=submit)
    assert result["status"] == "submitted"
    assert result["run"]["run_id"] == "run-123"
    assert result["results_location"] == {
        "output_bucket_resource": "output", "output_bucket_path": "results/job-123"}
    assert "do-not-return" not in str(result)
    assert "must not enter plan state" not in str(result)
    assert plans.approve(plan["id"], "alice",
                         inspect_dataset=options["inspect_dataset"], export_cohort=export,
                         submit_workflow=submit) == result
    assert calls == {"export": 1, "submit": 1}

    refreshed = plans.status(
        plan["id"], "alice", list_jobs=lambda **_kwargs: {"jobs": [
            {"run_id": "other", "status": "COMPLETED"},
            {"run_id": "run-123", "status": "COMPLETED",
             "output_bucket_path": "results/job-123"}]})
    assert refreshed["status"] == "completed"
    assert refreshed["run"]["run_id"] == "run-123"


def test_approval_stops_before_submit_when_export_does_not_match_plan():
    plan = prepare()
    submits = []
    result = plans.approve(
        plan["id"], "alice",
        inspect_dataset=callbacks()["inspect_dataset"],
        export_cohort=lambda *_args: {"s3_uri": plan["input_uri"], "rows": 41},
        submit_workflow=lambda *_args: submits.append(True))
    assert result["status"] == "failed"
    assert submits == []
    again = plans.approve(plan["id"], "alice",
                          inspect_dataset=callbacks()["inspect_dataset"],
                          export_cohort=lambda *_: pytest.fail(),
                          submit_workflow=lambda *_: pytest.fail())
    assert again == result


def test_owner_isolation_expiration_and_no_retry_after_submit_failure(monkeypatch):
    plan = prepare()
    with pytest.raises(plans.PlanOwnerMismatch):
        plans.approve(plan["id"], "bob", inspect_dataset=callbacks()["inspect_dataset"],
                      export_cohort=lambda *_: None,
                      submit_workflow=lambda *_: None)
    calls = {"export": 0, "submit": 0}

    def export(*_args):
        calls["export"] += 1
        return {"s3_uri": plan["input_uri"], "rows": plan["rows"]}

    def submit(*_args):
        calls["submit"] += 1
        raise RuntimeError("submission failed")

    failed = plans.approve(plan["id"], "alice",
                           inspect_dataset=callbacks()["inspect_dataset"], export_cohort=export,
                           submit_workflow=submit)
    assert failed["status"] == "failed"
    assert plans.approve(plan["id"], "alice",
                         inspect_dataset=callbacks()["inspect_dataset"], export_cohort=export,
                         submit_workflow=submit) == failed
    assert calls == {"export": 1, "submit": 1}

    now = time_value = plans.time.monotonic()
    monkeypatch.setattr(plans.time, "monotonic", lambda: time_value + plans.PLAN_TTL)
    with pytest.raises(plans.PlanNotFound):
        plans.status(plan["id"], "alice", list_jobs=lambda **_: {"jobs": []})


def test_approval_revalidates_dataset_source_and_row_count_before_export():
    current = callbacks()
    plan = plans.prepare("dataset-1", "input", "output", [], "alice", **current)
    changed = {**current["inspect_dataset"]("dataset-1", []),
               "source_ref": {"kind": "aurora", "resource_id": "other"}}
    exports = []
    result = plans.approve(
        plan["id"], "alice",
        inspect_dataset=lambda *_args: changed,
        export_cohort=lambda *_args: exports.append(True),
        submit_workflow=lambda *_args: pytest.fail())
    assert result["status"] == "failed"
    assert "source or columns changed" in result["errors"][0]
    assert exports == []


def test_joined_source_column_mapping_is_validated_and_frozen():
    actual_columns = [f"genetics → {name}" for name in plans.REQUIRED_INPUT_COLUMNS]
    mapping = dict(zip(plans.REQUIRED_INPUT_COLUMNS, actual_columns))
    options = callbacks(columns=actual_columns)
    options["inspect_dataset"] = lambda *_args: {
        "rows": 42, "columns": actual_columns, "column_mapping": mapping,
        "source_ref": {"kind": "join", "resource_id": "joined-source"}}
    plan = plans.prepare("joined-1", "input", "output", [], "alice", **options)
    assert plan["status"] == "ready"
    assert plan["column_mapping"] == mapping

    result = plans.approve(
        plan["id"], "alice", inspect_dataset=options["inspect_dataset"],
        export_cohort=lambda _ds, _resource, _path, _filters, selected: (
            {"s3_uri": plan["input_uri"], "rows": 42}
            if selected == mapping else pytest.fail("mapping changed")),
        submit_workflow=lambda *_: {"run_id": "mapped-run"})
    assert result["status"] == "submitted"


def test_invalid_join_mapping_and_raw_exception_details_are_not_returned():
    options = callbacks(columns=["person_id", "genetics → sample_id"])
    options["inspect_dataset"] = lambda *_args: {
        "rows": 12, "columns": ["person_id", "genetics → sample_id"],
        "column_mapping": {"person_id": "person_id", "sample_id": "other.sample_id"}}
    plan = plans.prepare("joined-2", "input", "output", [], "alice", **options)
    assert plan["status"] == "blocked"
    assert "sample_id" in plan["errors"][0]

    secret = "AKIA1234567890123456"
    failure = RuntimeError(f"provider failure: {secret} token=supersecret")
    safe = plans._safe_error(failure)
    assert secret not in safe and "supersecret" not in safe
