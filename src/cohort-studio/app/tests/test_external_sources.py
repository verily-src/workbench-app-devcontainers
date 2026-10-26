import json
from datetime import date

import pandas as pd
import pytest
import boto3
from botocore.stub import Stubber
from fastapi.testclient import TestClient

import duck
import external_sources
import main


def _config(databases=None, **extra):
    return {
        "region": "us-east-1", "catalog": "AwsDataCatalog",
        "workgroup": "studio-readonly", "output_location": "s3://results/athena/",
        "databases": databases or ["clinical"], "timeout_seconds": 1,
        **extra,
    }


def test_athena_tables_list_only_allowlisted_databases(monkeypatch):
    monkeypatch.setenv("STUDIO_ATHENA_RESOURCES", json.dumps({
        "clinical-read": _config(databases=["clinical", "genetics"]),
    }))

    class Glue:
        def get_tables(self, DatabaseName, MaxResults, **kwargs):
            return {"TableList": [{"Name": "samples", "Parameters": {}},
                                  {"Name": "variants", "Parameters": {
                                      "table_type": "ICEBERG"}}]}

    monkeypatch.setattr(external_sources, "_client", lambda _settings, service:
                        Glue() if service == "glue" else None)
    tables = external_sources.list_athena_tables("clinical-read")
    assert [t["name"] for t in tables] == [
        "clinical.samples", "clinical.variants", "genetics.samples", "genetics.variants"]
    assert next(t for t in tables if t["name"] == "clinical.variants")["detail"] == "iceberg"
    with pytest.raises(ValueError, match="allowlist"):
        external_sources.list_athena_tables("clinical-read", "other")
    assert external_sources.athena_resources() == [{
        "kind": "athena", "id": "clinical-read", "label": "clinical-read · Athena"}]


def test_glue_list_tables_uses_service_model_max_page_size(monkeypatch):
    monkeypatch.setenv("STUDIO_ATHENA_RESOURCES", json.dumps({
        "clinical-read": _config(),
    }))
    client = boto3.client(
        "glue", region_name="us-east-1", aws_access_key_id="test",
        aws_secret_access_key="test")
    stubber = Stubber(client)
    stubber.add_response("get_tables", {"TableList": [{"Name": "person"}]}, {
        "DatabaseName": "clinical", "MaxResults": 100,
    })
    monkeypatch.setattr(external_sources, "_client",
                        lambda _settings, service: client)
    with stubber:
        assert external_sources.list_athena_tables("clinical-read") == [{
            "name": "clinical.person", "table": "person",
            "schema": "clinical", "detail": "table"}]


def test_invalid_athena_config_does_not_echo_config_values(monkeypatch):
    secret_like = "AWS_SECRET_ACCESS_KEY=do-not-return"
    monkeypatch.setenv("STUDIO_ATHENA_RESOURCES", json.dumps({
        "clinical-read": _config(profile=secret_like),
    }))
    with pytest.raises(ValueError) as err:
        external_sources.athena_resources()
    assert secret_like not in str(err.value)


def test_athena_catalog_is_limited_to_glue_catalog():
    with pytest.raises(ValueError):
        external_sources.AthenaResource.model_validate(
            _config(catalog="unexpected"))


def test_open_athena_stages_all_rows_and_preserves_integer_ids(monkeypatch):
    monkeypatch.setattr(main.queries, "ROW_CAP", 2)
    monkeypatch.setenv("STUDIO_ATHENA_RESOURCES", json.dumps({
        "clinical-read": _config(),
    }))

    class Glue:
        def get_table(self, DatabaseName, Name):
            return {"Table": {"Name": Name}}

    class Athena:
        start = None

        def get_work_group(self, WorkGroup):
            return {"WorkGroup": {"State": "ENABLED", "Configuration": {
                "EnforceWorkGroupConfiguration": True,
                "BytesScannedCutoffPerQuery": 50_000_000,
                "EngineVersion": {"EffectiveEngineVersion": "Athena engine version 3"},
                "ResultConfiguration": {"OutputLocation": "s3://results/athena/"},
            }}}

        def start_query_execution(self, **kwargs):
            self.start = kwargs
            return {"QueryExecutionId": "query-1"}

        def get_query_execution(self, QueryExecutionId):
            return {"QueryExecution": {"Status": {"State": "SUCCEEDED"},
                    "Statistics": {"DataScannedInBytes": 100}}}

        def get_query_results(self, **kwargs):
            if kwargs.get("NextToken"):
                return {"ResultSet": {"Rows": [{"Data": [{"VarCharValue": "3"}, {"VarCharValue": "12345678901234567890123456789012345678"}]}]}}
            return {"ResultSet": {
                "ResultSetMetadata": {"ColumnInfo": [
                    {"Name": "person_id", "Type": "bigint"},
                    {"Name": "exact_id", "Type": "decimal(38,0)", "Precision": 38, "Scale": 0}]},
                "Rows": [
                    {"Data": [{"VarCharValue": "person_id"}, {"VarCharValue": "exact_id"}]},
                    {"Data": [{"VarCharValue": "9007199254740993"}, {}]},
                    {"Data": [{"VarCharValue": "2"}, {"VarCharValue": "42"}]},
                ],
            }, "NextToken": "second"}

    athena = Athena()
    monkeypatch.setattr(external_sources, "_client", lambda _settings, service:
                        Glue() if service == "glue" else athena)
    monkeypatch.setattr(main.lineage, "record", lambda *_args, **_kwargs: None)
    response = TestClient(main.app).post("/api/datasets/open", json={
        "source_ref": {"kind": "athena", "resource_id": "clinical-read",
                       "schema": "clinical", "table": "person"}})

    assert response.status_code == 200, response.text
    assert athena.start["QueryString"] == 'SELECT * FROM "AwsDataCatalog"."clinical"."person"'
    assert response.json()["rows"] == 3
    assert response.json()["sampled"] is False
    dataset = main.datasets.get(response.json()["dataset_id"])
    try:
        assert dataset["df"]["person_id"].tolist() == [9007199254740993, 2, 3]
        queried = TestClient(main.app).post(
            f"/api/datasets/{response.json()["dataset_id"]}/query",
            json={"filters": [{"column": "person_id", "kind": "range", "min": 3, "max": 3}],
                  "charts": [], "page": 0, "page_size": 50})
        assert queried.status_code == 200, queried.text
        assert queried.json()["total"] == 3
        assert queried.json()["filtered"] == 1
        assert queried.json()["rows"]["data"] == [[3, "12345678901234567890123456789012345678"]]
    finally:
        main.datasets.close_dataset(response.json()["dataset_id"])


def test_athena_fetch_uses_enforced_engine3_workgroup_and_decodes_results(monkeypatch):
    monkeypatch.setenv("STUDIO_ATHENA_RESOURCES", json.dumps({
        "clinical-read": _config(),
    }))

    class Glue:
        def get_table(self, DatabaseName, Name):
            return {"Table": {"Name": Name}}

    class Athena:
        def __init__(self):
            self.start = None

        def get_work_group(self, WorkGroup):
            return {"WorkGroup": {
                "State": "ENABLED",
                "Configuration": {
                    "EnforceWorkGroupConfiguration": True,
                    "BytesScannedCutoffPerQuery": 50_000_000,
                    "ResultConfiguration": {"OutputLocation": "s3://results/athena/"},
                    "EngineVersion": {
                        "EffectiveEngineVersion": "Athena engine version 3"},
                },
            }}

        def start_query_execution(self, **kwargs):
            self.start = kwargs
            return {"QueryExecutionId": "query-1"}

        def get_query_execution(self, QueryExecutionId):
            return {"QueryExecution": {
                "Status": {"State": "SUCCEEDED"},
                "Statistics": {"DataScannedInBytes": 100},
            }}

        def get_query_results(self, **kwargs):
            return {"ResultSet": {
                "ResultSetMetadata": {"ColumnInfo": [
                    {"Name": "person_id", "Type": "bigint"},
                    {"Name": "birth_date", "Type": "date"},
                ]},
                "Rows": [
                    {"Data": [{"VarCharValue": "person_id"},
                              {"VarCharValue": "birth_date"}]},
                    {"Data": [{"VarCharValue": "9007199254740993"},
                              {"VarCharValue": "2024-07-01"}]},
                    {"Data": [{}, {}]},
                ],
            }}

    athena = Athena()
    monkeypatch.setattr(external_sources, "_client", lambda _settings, service:
                        Glue() if service == "glue" else athena)
    frame = external_sources.fetch_athena_table(
        "clinical-read", "clinical", "person", 10)
    assert frame.to_dict(orient="records") == [
        {"person_id": 9007199254740993, "birth_date": date(2024, 7, 1)},
        {"person_id": None, "birth_date": None}]
    assert str(frame["person_id"].dtype) == "Int64"
    assert athena.start["WorkGroup"] == "studio-readonly"
    assert athena.start["ResultConfiguration"] == {
        "OutputLocation": "s3://results/athena/"}
    assert '"AwsDataCatalog"."clinical"."person" LIMIT 11' in athena.start["QueryString"]


def test_athena_requires_workgroup_scan_cap_before_start(monkeypatch):
    monkeypatch.setenv("STUDIO_ATHENA_RESOURCES", json.dumps({
        "clinical-read": _config(),
    }))

    class Glue:
        def get_table(self, DatabaseName, Name):
            return {"Table": {"Name": Name}}

    class Athena:
        started = False

        def get_work_group(self, WorkGroup):
            return {"WorkGroup": {"State": "ENABLED",
                                   "Configuration": {
                                       "EnforceWorkGroupConfiguration": True,
                                       "EngineVersion": {
                                           "EffectiveEngineVersion": "Athena engine version 3"}}}}

        def start_query_execution(self, **kwargs):
            self.started = True
            raise AssertionError("query must not start")

    athena = Athena()
    monkeypatch.setattr(external_sources, "_client", lambda _settings, service:
                        Glue() if service == "glue" else athena)
    with pytest.raises(ValueError, match="bytes-scanned cutoff"):
        external_sources.fetch_athena_table("clinical-read", "clinical", "person", 10)
    assert athena.started is False


def test_athena_timeout_stops_running_query(monkeypatch):
    class Client:
        stopped = False

        def get_query_execution(self, QueryExecutionId):
            return {"QueryExecution": {"Status": {"State": "RUNNING"}}}

        def stop_query_execution(self, QueryExecutionId):
            self.stopped = True

    client = Client()
    now = [0.0]
    monkeypatch.setattr(external_sources.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(external_sources.time, "sleep", lambda delay: now.__setitem__(0, now[0] + delay))
    with pytest.raises(external_sources.AthenaTimeout):
        external_sources._wait(client, "q1", 1.0)
    assert client.stopped is True


@pytest.mark.parametrize("next_token, succeeds", [(None, True), ("next", False)])
def test_athena_result_deadline_allows_complete_page_only(
        monkeypatch, next_token, succeeds):
    monkeypatch.setenv("STUDIO_ATHENA_RESOURCES", json.dumps({
        "clinical-read": _config(),
    }))
    now = [0.0]
    monkeypatch.setattr(external_sources.time, "monotonic", lambda: now[0])

    class Glue:
        def get_table(self, DatabaseName, Name):
            return {"Table": {"Name": Name}}

    class Athena:
        stopped = False

        def get_work_group(self, WorkGroup):
            return {"WorkGroup": {"State": "ENABLED", "Configuration": {
                "EnforceWorkGroupConfiguration": True,
                "BytesScannedCutoffPerQuery": 50_000_000,
                "EngineVersion": {"EffectiveEngineVersion": "Athena engine version 3"},
                "ResultConfiguration": {"OutputLocation": "s3://results/athena/"},
            }}}

        def start_query_execution(self, **kwargs):
            return {"QueryExecutionId": "query-1"}

        def get_query_execution(self, QueryExecutionId):
            return {"QueryExecution": {"Status": {"State": "SUCCEEDED"},
                    "Statistics": {"DataScannedInBytes": 1}}}

        def get_query_results(self, **kwargs):
            now[0] = 2.0
            return {"ResultSet": {
                "ResultSetMetadata": {"ColumnInfo": [
                    {"Name": "id", "Type": "bigint"}]},
                "Rows": [
                    {"Data": [{"VarCharValue": "id"}]},
                    {"Data": [{"VarCharValue": "9007199254740993"}]},
                ],
            }, **({"NextToken": next_token} if next_token else {})}

        def stop_query_execution(self, QueryExecutionId):
            self.stopped = True

    athena = Athena()
    monkeypatch.setattr(external_sources, "_client", lambda _settings, service:
                        Glue() if service == "glue" else athena)
    if succeeds:
        frame = external_sources.fetch_athena_table(
            "clinical-read", "clinical", "person", 10)
        assert frame["id"].tolist() == [9007199254740993]
        assert athena.stopped is False
    else:
        with pytest.raises(external_sources.AthenaTimeout):
            external_sources.fetch_athena_table(
                "clinical-read", "clinical", "person", 10)
        assert athena.stopped is True


def test_s3_parquet_hive_partition_open_and_relative_path_validation(tmp_path):
    partition = tmp_path / "year=2024"
    partition.mkdir()
    path = partition / "part.parquet"
    pd.DataFrame({"sample_id": ["a", "b"]}).to_parquet(path)
    frame = duck.fetch_file(str(path), 10)
    assert frame.to_dict(orient="records") == [
        {"sample_id": "a", "year": 2024},
        {"sample_id": "b", "year": 2024},
    ]
    assert "hive_partitioning = true" in duck._reader_sql(
        "s3://bucket/year=2024/part.parquet", hive=True)
    with pytest.raises(ValueError, match="path"):
        duck._validate_relative_key("../outside/data.parquet")
    with pytest.raises(ValueError, match="supported data file"):
        duck._validate_relative_key("valid/file.exe")


def test_existing_catalog_opens_complete_disk_source(monkeypatch):
    import catalog
    import disk_data
    import duckdb

    def attach(*_args):
        connection = duckdb.connect()
        connection.execute("ATTACH ':memory:' AS cat")
        connection.execute("CREATE TABLE cat.main.items AS SELECT * FROM range(7) values_table(id)")
        return connection

    monkeypatch.setattr(catalog, "resolve", lambda *_args: ("local.duckdb", None))
    monkeypatch.setattr(catalog, "_attach", attach)
    monkeypatch.setattr(catalog, "_objects", lambda connection: [
        {"name": "items", "schema": "main", "object": "items", "sql": "SELECT * FROM items"}])
    monkeypatch.setattr(disk_data, "_catalog_size", lambda *_args: 100)
    monkeypatch.setattr(main.lineage, "record", lambda *_args, **_kwargs: None)
    client = TestClient(main.app)
    opened = client.post("/api/datasets/open", json={"source_ref": {
        "kind": "catalog", "resource_id": "existing-catalog", "table": "items"}})
    assert opened.status_code == 200, opened.text
    dataset_id = opened.json()["dataset_id"]
    try:
        queried = client.post(f"/api/datasets/{dataset_id}/query", json={
            "filters": [], "charts": [{"kind": "histogram", "x": "id", "bins": 3}],
            "page": 0, "page_size": 2})
        assert queried.status_code == 200, queried.text
        assert queried.json()["total"] == 7
        assert len(queried.json()["rows"]["data"]) == 2
        assert queried.json()["charts"]
    finally:
        main.datasets.close_dataset(dataset_id)
