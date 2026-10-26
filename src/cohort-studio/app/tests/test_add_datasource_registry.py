import json
from datetime import datetime, timezone
from io import BytesIO
import uuid

import pytest

import config
import duck
import external_sources
import postgres_sources
import source_registry
import views


@pytest.fixture
def registry_file(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"llm": {"provider": "anthropic"},
                                "chart_palette": "verily"}))
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    return path


def test_add_sources_preserves_settings_and_returns_safe_metadata(registry_file):
    postgres = source_registry.add({
        "kind": "postgres", "id": "clinical", "label": "Clinical DB",
        "secret_id": "arn:aws:secretsmanager:us-east-1:123456789012:secret:rds",
        "region": "us-east-1",
    })
    s3 = source_registry.add({
        "kind": "s3", "id": "lake", "label": "Lake files",
        "bucket": "clinical-lake", "prefix": "study/data", "region": "us-west-2",
    })
    athena = source_registry.add({
        "kind": "athena", "id": "clinical-read", "label": "Clinical Athena",
        "region": "us-east-1", "workgroup": "studio-read",
        "output_location": "s3://query-results/studio/",
        "databases": ["clinical", "genomics"], "catalog": "AwsDataCatalog",
    })
    assert postgres == {"kind": "postgres", "id": "postgres:clinical", "label": "Clinical DB"}
    assert s3 == {"kind": "s3", "id": "s3:lake", "label": "Lake files"}
    assert athena["kind"] == "athena"
    stored = json.loads(registry_file.read_text())
    assert stored["llm"] == {"provider": "anthropic"}
    assert stored["chart_palette"] == "verily"
    assert "password" not in registry_file.read_text()
    public = source_registry.public_sources()
    assert [item["id"] for item in public] == [
        "postgres:clinical", "s3:lake", "clinical-read",
    ]
    assert "secret_id" not in json.dumps(public)


@pytest.mark.parametrize("payload", [
    {"kind": "postgres", "id": "pg", "label": "PG", "secret_id": "x",
     "username": "forbidden"},
    {"kind": "postgres", "id": "pg", "label": "PG", "secret_id": " "},
    {"kind": "s3", "id": "lake", "label": "Lake", "bucket": "bad",
     "prefix": "../private"},
    {"kind": "athena", "id": "athena", "label": "Athena",
     "region": "us-east-1", "workgroup": "read", "output_location": "s3://result/x",
     "databases": ["clinical", "clinical"], "catalog": "AwsDataCatalog"},
])
def test_registry_rejects_unused_credentials_and_invalid_config(payload, registry_file):
    with pytest.raises(ValueError):
        source_registry.add(payload)


def test_environment_sources_win_and_registered_source_ids_are_reserved(
        registry_file, monkeypatch):
    monkeypatch.setenv("STUDIO_POSTGRES_SOURCES", json.dumps([{
        "id": "protected", "url_env": "STUDIO_DB_URL",
    }]))
    monkeypatch.setenv("STUDIO_ATHENA_RESOURCES", json.dumps({
        "protected-athena": {
            "region": "us-east-1", "catalog": "AwsDataCatalog",
            "workgroup": "env-workgroup", "output_location": "s3://results/",
            "databases": ["env_db"],
        },
    }))
    with pytest.raises(ValueError, match="reserved"):
        source_registry.add({"kind": "postgres", "id": "protected",
                             "label": "Wrong", "secret_id": "secret"})
    with pytest.raises(ValueError, match="reserved"):
        source_registry.add({"kind": "athena", "id": "protected-athena",
                             "label": "Wrong", "region": "us-east-1",
                             "workgroup": "reader", "output_location": "s3://results/",
                             "databases": ["db"]})
    source_registry.add({"kind": "postgres", "id": "registered",
                         "label": "Registered", "secret_id": "secret"})
    source_registry.add({"kind": "athena", "id": "registered-athena",
                         "label": "Registered", "region": "us-east-1",
                         "workgroup": "reader", "output_location": "s3://results/",
                         "databases": ["registered_db"]})
    postgres = postgres_sources.connections()
    assert postgres["postgres:protected"].url_env == "STUDIO_DB_URL"
    assert postgres["postgres:registered"].secret_id == "secret"
    athena = external_sources._resources()
    assert athena["protected-athena"].workgroup == "env-workgroup"
    assert athena["registered-athena"].workgroup == "reader"


def test_registered_s3_listing_and_fetch_use_bucket_prefix_and_app_credentials(
        registry_file, monkeypatch):
    resource_id = "s3:lake-" + uuid.uuid4().hex[:8]
    source_registry.add({"kind": "s3", "id": resource_id.removeprefix("s3:"),
                         "label": "Lake",
                         "bucket": "clinical-lake", "prefix": "study/data",
                         "region": "us-west-2"})
    calls = []

    class S3Client:
        def list_objects_v2(self, **kwargs):
            calls.append(kwargs)
            return {"Contents": [
                {"Key": "study/data/part-1.parquet"},
                {"Key": "study/data/notes.txt"},
            ]}

    class Session:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def client(self, service, **kwargs):
            assert service == "s3"
            calls.append(kwargs)
            return S3Client()

    import boto3
    monkeypatch.setattr(boto3, "Session", Session)
    assert duck.list_s3_files(resource_id) == ["notes.txt", "part-1.parquet"]
    assert calls[0] == {"region_name": "us-west-2"}
    assert calls[1] == {"region_name": "us-west-2"}
    assert calls[2] == {"Bucket": "clinical-lake", "Prefix": "study/data/",
                        "MaxKeys": 1000}

    fetched = {}
    monkeypatch.setattr(duck, "fetch_file",
                        lambda uri, cap, profile=None, region=None, app_credentials=False:
                        fetched.update(uri=uri, cap=cap, profile=profile, region=region,
                                       app_credentials=app_credentials))
    with pytest.raises(ValueError):
        duck.fetch_s3_file(resource_id, "../private.parquet", 10)
    duck.fetch_s3_file(resource_id, "part-1.parquet", 10)
    assert fetched == {"uri": "s3://clinical-lake/study/data/part-1.parquet",
                       "cap": 10, "profile": None, "region": "us-west-2",
                       "app_credentials": True}


def test_duckdb_s3_secret_uses_default_aws_session(monkeypatch):
    statements = []

    class Connection:
        def execute(self, sql):
            statements.append(sql)

    class Credentials:
        def get_frozen_credentials(self):
            return type("Frozen", (), {
                "access_key": "test-access", "secret_key": "test-secret",
                "token": "test-session",
            })()

    class Session:
        def __init__(self, **kwargs):
            assert kwargs == {"region_name": "eu-west-1"}

        def get_credentials(self):
            return Credentials()

    import boto3
    monkeypatch.setattr(boto3, "Session", Session)
    monkeypatch.setattr(duck.duckdb, "connect", Connection)
    duck._connect(None, "eu-west-1", app_credentials=True)
    assert statements[0] == "INSTALL httpfs; LOAD httpfs;"
    assert "KEY_ID 'test-access'" in statements[1]
    assert "SECRET 'test-secret'" in statements[1]
    assert "SESSION_TOKEN 'test-session'" in statements[1]
    assert "REGION 'eu-west-1'" in statements[1]


def test_registered_s3_saved_views_use_app_bucket_without_workbench_cli(
        registry_file, monkeypatch):
    source_registry.add({"kind": "s3", "id": "views-lake", "label": "Views",
                         "bucket": "clinical-lake", "prefix": "study/data",
                         "region": "us-west-2"})
    objects = {}
    calls = []

    class Client:
        def put_object(self, **kwargs):
            calls.append(("put", kwargs["Bucket"], kwargs["Key"]))
            objects[kwargs["Key"]] = kwargs["Body"]

        def get_paginator(self, operation):
            assert operation == "list_objects_v2"
            return self

        def paginate(self, **kwargs):
            calls.append(("list", kwargs["Bucket"], kwargs["Prefix"]))
            return [{"Contents": [{"Key": key, "LastModified": datetime.now(timezone.utc)}
                                   for key in objects]}]

        def get_object(self, **kwargs):
            return {"Body": BytesIO(objects[kwargs["Key"]])}

        def delete_object(self, **kwargs):
            objects.pop(kwargs["Key"], None)

    class Session:
        def __init__(self, **kwargs):
            assert kwargs == {"region_name": "us-west-2"}

        def client(self, service, **kwargs):
            assert service == "s3" and kwargs == {"region_name": "us-west-2"}
            return Client()

    import boto3
    monkeypatch.setattr(boto3, "Session", Session)
    monkeypatch.setattr(views, "_actor", lambda: "test-user")
    monkeypatch.setattr(views.db, "resolve_s3_uri",
                        lambda *_args: pytest.fail("Workbench CLI resolver used"))

    views._s3_save("s3:views-lake", "my view", {"version": 2})
    listed = views._s3_list("s3:views-lake")
    assert len(listed) == 1 and listed[0]["name"] == "my view"
    assert views._s3_get("s3:views-lake", "my view") == {
        "version": 2, "created_by": "test-user",
    }
    assert calls[0] == ("put", "clinical-lake", "study/data/_studio_views/my view.json")
    assert calls[1] == ("list", "clinical-lake", "study/data/_studio_views/")
    views._s3_delete("s3:views-lake", "my view")
    assert objects == {}


def test_registration_api_lists_new_source_and_rejects_secret_payload(registry_file, monkeypatch):
    from fastapi.testclient import TestClient
    import main
    monkeypatch.setattr(main.db, "resources_ready", lambda: False)
    monkeypatch.setattr(main.catalog, "discover", lambda folders: ([], False))
    monkeypatch.setattr(source_registry, "validate_connection", lambda payload: None)
    client = TestClient(main.app)
    added = client.post("/api/sources", json={"kind": "s3", "id": "analysis", "label": "Analysis files",
                                            "bucket": "example-analysis", "prefix": "results", "region": "us-east-1"})
    assert added.status_code == 200, added.text
    assert added.json()["id"] == "s3:analysis"
    listed = client.get("/api/datasources")
    assert any(item["id"] == added.json()["id"] for item in listed.json()["sources"])
    invalid = client.post("/api/sources", json={"kind": "postgres", "id": "bad", "label": "Bad",
                                              "secret_id": "connections/demo", "password": "must-not-echo"})
    assert invalid.status_code == 422
    assert "must-not-echo" not in invalid.text
