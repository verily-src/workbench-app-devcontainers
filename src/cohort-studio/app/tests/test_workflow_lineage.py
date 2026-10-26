import json
import uuid

import pandas as pd
from sqlalchemy import select

import datasets
import lineage
import main


def test_workflow_lineage_links_postgres_api_events(client, engine, monkeypatch):
    token = uuid.uuid4().hex
    cohort_source = f"omop-db / selected cohort {token}"
    dataset_id = datasets.open_dataset(pd.DataFrame({
        "person_id": [101, 102], "sample_id": ["sample-a", "sample-b"],
        "variant_id": ["SYN_VAR_0021", "SYN_VAR_0021"],
        "dosage": [0, 1], "gender_concept_id": [8507, 8532],
        "year_of_birth": [1970, 1980],
    }), cohort_source, capped=False)["dataset_id"]
    csv_uri = f"s3://input-bucket/cohort/{token}.csv"
    params_uri = f"s3://input-bucket/params/{token}.json"
    run_id = f"run-{token}"

    monkeypatch.setattr(main, "_lineage_engine", lambda: engine)
    monkeypatch.setattr(lineage, "_actor", lambda: "lineage-test")
    lineage.record(engine, "omop_cohort_opened", "cohort", cohort_source,
                   payload={"resource_id": "omop-db", "rows": 2,
                            "dataset_id": dataset_id,
                            "source_ref": {"kind": "omop_cohort",
                                           "resource_id": "omop-db"}},
                   parents=[("dataset", dataset_id)])

    exported = {}

    def export_csv(frame, resource_id, path):
        exported["columns"] = list(frame.columns)
        exported["rows"] = len(frame)
        return {"s3_uri": csv_uri, "resource_id": resource_id,
                "path": path, "rows": len(frame)}

    monkeypatch.setattr(main.workflows, "export_cohort_csv", export_csv)
    monkeypatch.setattr(main.db, "resolve_s3_uri", lambda resource_id: {
        "input-resource": "s3://input-bucket",
        "output-resource": "s3://output-bucket/results",
    }[resource_id])
    monkeypatch.setattr(main.workflows, "write_params_json",
                        lambda *args: {"s3_uri": params_uri})

    def submit(**kwargs):
        return {
            "run_id": run_id, "name": f"genetics-{token}",
            "status": "PENDING", "output_bucket_uuid": "output-uuid",
            "output_bucket_resource": "output-resource",
            "output_bucket_path": f"demo/{token}/genetics-{token}",
        }

    monkeypatch.setattr(main.workflows, "submit_job", submit)
    try:
        export_response = client.post(
            f"/api/datasets/{dataset_id}/export-cohort", json={
                "resource_id": "input-resource",
                "path": f"cohort/{token}.csv", "filters": [],
                "workflow": "cohort-genetics-demo",
            })
        assert export_response.status_code == 200, export_response.text
        assert exported["rows"] == 2
        assert exported["columns"] == [
            "person_id", "sample_id", "variant_id", "dosage",
            "gender_concept_id", "year_of_birth"]

        submit_response = client.post("/api/workflows/submit", json={
            "workflow": "cohort-genetics-demo",
            "output_bucket_id": "output-resource",
            "job_id": f"genetics-{token}",
            "params_file_bucket_id": "input-resource",
            "params_file_path": f"params/{token}.json",
            "demo_input_resource_id": "input-resource",
            "demo_input_csv_path": f"cohort/{token}.csv",
            "demo_output_path": f"demo/{token}",
        })
        assert submit_response.status_code == 200, submit_response.text

        with engine.connect() as conn:
            event_rows = conn.execute(select(
                lineage.event_table.c.id, lineage.event_table.c.event_type,
                lineage.event_table.c.entity_type, lineage.event_table.c.entity_id,
                lineage.event_table.c.payload,
            ).where(lineage.event_table.c.entity_id.in_(
                [csv_uri, params_uri, f"genetics-{token}", cohort_source]))
            ).mappings().all()
            compatibility_event = conn.execute(select(
                lineage.event_table.c.id, lineage.event_table.c.event_type,
                lineage.event_table.c.entity_type, lineage.event_table.c.entity_id,
                lineage.event_table.c.payload,
            ).where(lineage.event_table.c.event_type == "cohort_exported",
                    lineage.event_table.c.entity_id == cohort_source)
             .order_by(lineage.event_table.c.id.desc()).limit(1)
             ).mappings().one()
            ids = [row["id"] for row in event_rows]
            ids.append(compatibility_event["id"])
            edge_rows = conn.execute(select(
                lineage.edge_table.c.event_id,
                lineage.edge_table.c.parent_entity_type,
                lineage.edge_table.c.parent_entity_id,
            ).where(lineage.edge_table.c.event_id.in_(ids))).all()

        events = {(row["event_type"], row["entity_type"], row["entity_id"]): row
                  for row in event_rows}
        assert events[("artifact_exported", "artifact", csv_uri)]
        assert events[("workflow_params_written", "artifact", params_uri)]
        assert events[("workflow_submitted", "workflow", f"genetics-{token}")]
        assert events[("omop_cohort_opened", "cohort", cohort_source)]
        assert compatibility_event["event_type"] == "cohort_exported"
        assert json.loads(compatibility_event["payload"])["to"] == csv_uri

        parents = {}
        for event_id, parent_type, parent_id in edge_rows:
            parents.setdefault(event_id, set()).add((parent_type, parent_id))
        csv_event = events[("artifact_exported", "artifact", csv_uri)]
        params_event = events[("workflow_params_written", "artifact", params_uri)]
        run_event = events[("workflow_submitted", "workflow", f"genetics-{token}")]
        cohort_event = events[("omop_cohort_opened", "cohort", cohort_source)]
        assert ("event", str(csv_event["id"])) in parents[compatibility_event["id"]]
        assert ("dataset", dataset_id) in parents[csv_event["id"]]
        assert ("event", str(cohort_event["id"])) in parents[csv_event["id"]]
        assert ("dataset", dataset_id) in parents[cohort_event["id"]]
        assert ("event", str(csv_event["id"])) in parents[params_event["id"]]
        assert {("event", str(csv_event["id"])),
                ("event", str(params_event["id"]))} <= parents[run_event["id"]]

        payloads = [json.loads(row["payload"]) for row in event_rows]
        assert all("person_id" not in json.dumps(item) for item in payloads)
        assert all("dosage" not in json.dumps(item) for item in payloads)
        assert all("api_key" not in json.dumps(item) for item in payloads)
        run_payload = json.loads(run_event["payload"])
        assert run_payload["run_id"] == run_id
        assert run_payload["status"] == "PENDING"
        assert run_payload["output_bucket_resource"] == "output-resource"
        assert run_payload["output_bucket_path"] == f"demo/{token}/genetics-{token}"
    finally:
        datasets.close_dataset(dataset_id)


def test_lineage_source_ref_excludes_sql_and_settings():
    safe = lineage.safe_source_ref({
        "kind": "join", "base": {
            "kind": "sql", "resource_id": "source-one",
            "sql": "SELECT * FROM private_table WHERE token = 'secret'",
        },
        "steps": [{"alias": "joined", "how": "inner",
                   "source": {"kind": "aurora", "resource_id": "db-one",
                              "schema": "public", "table": "person",
                              "settings": [{"column": "secret", "values": ["x"]}]},
                   "conditions": [{"left": "id", "right": "id"}] }],
        "settings": [{"api_key": "never-record"}],
    })
    encoded = json.dumps(safe)
    assert safe == {
        "kind": "join",
        "base": {"kind": "sql", "resource_id": "source-one"},
        "steps": [{"alias": "joined", "how": "inner",
                   "source": {"kind": "aurora", "resource_id": "db-one",
                              "schema": "public", "table": "person"}}],
    }
    assert "private_table" not in encoded
    assert "secret" not in encoded
    assert "api_key" not in encoded
