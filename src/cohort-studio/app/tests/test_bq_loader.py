import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

import bq
import db
import main
import source_registry


def test_billing_project_precedence(monkeypatch):
    monkeypatch.delenv("STUDIO_BQ_BILLING_PROJECT", raising=False)
    assert bq.billing_project("", "bigquery-public-data") == "bigquery-public-data"
    monkeypatch.setenv("STUDIO_BQ_BILLING_PROJECT", "my-billing-1")
    assert bq.billing_project("", "bigquery-public-data") == "my-billing-1"
    assert bq.billing_project("explicit-proj", "bigquery-public-data") == "explicit-proj"


def test_nested_bigquery_values_flatten_to_text():
    df = pd.DataFrame({
        "alternate_bases": [np.array([{"alt": "A"}, {"alt": "G"}], dtype=object), np.array([], dtype=object)],
        "CLNSIG": [np.array(["Pathogenic"], dtype=object), None],
        "call": [[{"name": "s1", "genotype": [0, 1]}], []],
        "pos": [10, 20],
    })
    out = bq.flatten(df)
    assert out["alternate_bases"].tolist() == ["A, G", ""]
    assert out["CLNSIG"][0] == "Pathogenic" and pd.isna(out["CLNSIG"][1])
    assert out["call"][0] == '[{"genotype": [0, 1], "name": "s1"}]'
    assert out["pos"].tolist() == [10, 20]


def test_fetch_table_bills_the_billing_project(monkeypatch):
    seen = {}

    class Job:
        def to_dataframe(self):
            return pd.DataFrame({"rs": [np.array(["123"], dtype=object)]})

    class Client:
        def __init__(self, project):
            seen["billing"] = project

        def query(self, sql):
            seen["sql"] = sql
            return Job()
    monkeypatch.setattr(bq, "_clients", {})
    monkeypatch.setattr("google.cloud.bigquery.Client", lambda project: Client(project))
    df = bq.fetch_table.__wrapped__("bigquery-public-data", "human_variant_annotation",
                                    "ncbi_clinvar_hg38_20180701", 5, billing="my-billing-1") \
        if hasattr(bq.fetch_table, "__wrapped__") else bq.fetch_table(
            "bigquery-public-data", "human_variant_annotation", "ncbi_clinvar_hg38_20180701", 5,
            billing="my-billing-1")
    assert seen["billing"] == "my-billing-1"
    assert "`bigquery-public-data.human_variant_annotation.ncbi_clinvar_hg38_20180701`" in seen["sql"]
    assert df["rs"].tolist() == ["123"]


def test_registration_and_discovery(monkeypatch):
    item = {"kind": "bq", "id": "clinvar", "label": "ClinVar", "project": "bigquery-public-data",
            "dataset": "human_variant_annotation", "table": "ncbi_clinvar_hg38_20180701",
            "billing_project": "my-billing-1"}
    monkeypatch.setattr(source_registry, "_validated_entries",
                        lambda raw=None: [source_registry.BigQueryRegistration(**item).model_dump()])
    monkeypatch.setattr(db, "_ensure_cache", lambda wait=False: [
        {"id": "ws-clinvar", "resourceType": "BQ_DATA_TABLE", "projectId": "bigquery-public-data",
         "datasetId": "human_variant_annotation", "dataTableId": "ncbi_clinvar_hg38_20180701"},
        {"id": "ws-dataset", "resourceType": "BQ_DATASET", "projectId": "p-1234567",
         "datasetId": "ds"}])
    found = {d["id"]: d for d in db.list_bq_datasets()}
    assert found["ws-clinvar"]["table"] == "ncbi_clinvar_hg38_20180701"
    assert found["ws-dataset"]["table"] == ""
    assert found["bq:clinvar"]["billing_project"] == "my-billing-1"
    assert "bq:clinvar" not in {d["id"] for d in db.list_workbench_bq_datasets()}
    public = [s for s in source_registry.public_sources() if s["kind"] == "bq"]
    assert public == [{"kind": "bq", "id": "bq:clinvar", "label": "ClinVar",
                       "project": "bigquery-public-data", "dataset": "human_variant_annotation",
                       "table": "ncbi_clinvar_hg38_20180701"}]

    monkeypatch.setattr(bq, "table_info", lambda *a: {"rows": 393209, "bytes": 137839293, "columns": 31})
    listed = TestClient(main.app).get("/api/tables", params={"kind": "bq", "resource_id": "bq:clinvar"}).json()
    assert listed == [{"name": "ncbi_clinvar_hg38_20180701", "detail": "table",
                       "rows": 393209, "bytes": 137839293, "columns": 31}]


@pytest.mark.parametrize("bad", [
    {"project": "Bad_Project"}, {"dataset": "has space"}, {"table": "x;drop"}, {"billing_project": "UP"},
    {"table": "events$20261104"}])
def test_registration_rejects_unsafe_identifiers(bad):
    item = {"kind": "bq", "id": "clinvar", "label": "ClinVar", "project": "bigquery-public-data",
            "dataset": "human_variant_annotation", **bad}
    with pytest.raises(Exception):
        source_registry.BigQueryRegistration(**item)



def test_mcp_open_uses_the_registered_billing_project(monkeypatch):
    import asyncio
    import mcp_server
    if mcp_server.mcp is None:
        pytest.skip("MCP SDK not installed")
    seen = {}
    monkeypatch.setattr(db, "list_bq_datasets", lambda *a, **k: [{
        "id": "bq:clinvar", "project": "bigquery-public-data", "dataset": "human_variant_annotation",
        "table": "t1", "billing_project": "my-billing-1"}])

    def fetch(project, dataset, table, cap, billing=""):
        seen["billing"] = billing
        return pd.DataFrame({"a": [1]})
    monkeypatch.setattr(bq, "fetch_table", fetch)
    asyncio.run(mcp_server.mcp.call_tool("open_dataset", {
        "kind": "bq", "resource_id": "bq:clinvar", "table": "t1"}))
    assert seen["billing"] == "my-billing-1"
