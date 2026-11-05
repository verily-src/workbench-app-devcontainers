"""Durable datasource discovery: snapshot, failure messages, partial kinds, backoff."""

import json
import os
import stat
import subprocess

import pytest
from fastapi.testclient import TestClient

import db
import main
import resource_discovery as discovery

client = TestClient(main.app)

AURORA = {"id": "omop", "resourceType": "AWS_AURORA_DATABASE", "uuid": "u-a",
          "databaseName": "omopdb", "region": "us-east-1"}
FOLDER = {"id": "patient-data", "resourceType": "AWS_S3_STORAGE_FOLDER", "uuid": "u-s",
          "bucketName": "bucket-1", "prefix": "patient-data", "region": "us-east-1"}
BQ = {"id": "bq-ref", "resourceType": "BQ_DATASET", "uuid": "u-b",
      "projectId": "proj", "datasetId": "ds"}


class Done:
    def __init__(self, stdout):
        self.stdout = stdout
        self.returncode = 0


def fail(stderr, rc=1):
    def raise_it(args):
        raise subprocess.CalledProcessError(rc, args, output="", stderr=stderr)
    return raise_it


class FakeCli:
    """Answers `wb resource list` calls from a table keyed by --type (None = full list)."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        if args[:3] != ["wb", "resource", "list"]:
            raise AssertionError(f"unexpected CLI call: {args}")
        rtype = next((a.split("=", 1)[1] for a in args if a.startswith("--type=")), None)
        answer = self.answers.get(rtype, self.answers.get("*", []))
        if callable(answer):
            return answer(args)
        if isinstance(answer, BaseException):
            raise answer
        return Done(json.dumps(answer))


@pytest.fixture
def disc(monkeypatch, tmp_path):
    path = tmp_path / "discovery.json"
    monkeypatch.setenv("STUDIO_DISCOVERY_CACHE_PATH", str(path))
    for name in ("STUDIO_WORKSPACE_ID", "WORKBENCH_WORKSPACE_ID", "WORKSPACE_ID"):
        monkeypatch.delenv(name, raising=False)
    db._reset_for_tests()
    timers, spawned = [], []
    monkeypatch.setattr(db, "_start_timer", lambda delay, fn: timers.append((delay, fn)))
    monkeypatch.setattr(db, "_spawn", lambda fn: spawned.append(fn))
    monkeypatch.setattr(db, "configure_aws_profiles", lambda ids=None: None)
    monkeypatch.setattr(db, "warm_connection_string", lambda rid: None)
    monkeypatch.setattr(db, "_warm_catalogs", lambda: None)
    monkeypatch.setattr(main.catalog, "discover", lambda ids: ([], False))
    monkeypatch.setattr(main.omop, "hint", lambda rid: None)

    def use(answers):
        cli = FakeCli(answers)
        monkeypatch.setattr(db.cloud_cli, "run", cli)
        return cli

    yield {"path": path, "timers": timers, "spawned": spawned, "use": use}
    db._reset_for_tests()


def _ids(body, kind):
    return sorted(s["id"] for s in body["sources"] if s["kind"] == kind)


def test_cold_start_with_snapshot_serves_sources_immediately(disc):
    discovery.save([AURORA, FOLDER, BQ], {"patient-data": "s3://bucket-1/patient-data"})
    disc["use"]({"*": AssertionError("no CLI call should run before the refresh thread")})

    db.warm_resource_cache()

    assert db.resources_ready()
    assert len(disc["spawned"]) == 1          # the refresh runs in the background
    body = client.get("/api/datasources").json()
    assert body["ready"] is True
    assert _ids(body, "aurora") == ["omop"]
    assert _ids(body, "s3") == ["patient-data"]
    assert _ids(body, "bq") == ["bq-ref"]
    assert body["discovery"]["status"] == "refreshing"
    assert body["discovery"]["from_cache"] is True
    assert body["discovery"]["updated_at"].endswith("Z")
    assert db.resolve_s3_uri("patient-data") == "s3://bucket-1/patient-data"
    assert db.list_aurora_resources()[0] == {"id": "omop", "database": "omopdb",
                                             "region": "us-east-1"}

    disc["use"]({None: [AURORA, FOLDER]})
    disc["spawned"].pop()()                    # the background refresh lands
    body = client.get("/api/datasources").json()
    assert body["discovery"]["status"] == "fresh"
    assert body["discovery"]["from_cache"] is False
    assert _ids(body, "bq") == []


def test_refresh_failure_keeps_snapshot_and_reports_mapped_message(disc, monkeypatch):
    monkeypatch.setenv("STUDIO_WORKSPACE_ID", "ws-123")
    discovery.save([AURORA, FOLDER], {})
    db.load_cached_resources()
    cli = disc["use"]({None: fail("ERROR: No workspace set. token=s3cr3t-value")})

    db._refresh_resource_cache()

    # Retried once against the configured workspace before giving up.
    assert ["wb", "resource", "list", "--format", "json", "--workspace=ws-123"] in cli.calls
    assert not any(any(a.startswith("--type=") for a in c) for c in cli.calls)
    body = client.get("/api/datasources").json()
    assert _ids(body, "aurora") == ["omop"] and _ids(body, "s3") == ["patient-data"]
    d = body["discovery"]
    assert d["status"] == "stale"
    assert d["error_code"] == "no_workspace"
    assert d["error"] == ("The Workbench CLI has no workspace set on the app VM; "
                          "run `wb workspace set --id=ws-123`.")
    assert "s3cr3t" not in json.dumps(body)
    assert d["retry_at"]
    assert [delay for delay, _ in disc["timers"]] == [discovery.RETRY_BASE_S]


@pytest.mark.parametrize("exc, code, phrase", [
    (subprocess.CalledProcessError(1, ["wb"], stderr="Error: No workspace set"), "no_workspace",
     "wb workspace set --id=<workspace>"),
    (subprocess.CalledProcessError(1, ["wb"], stderr="User not logged in."),
     "auth", "wb auth login"),
    (subprocess.TimeoutExpired(["wb"], 120), "timeout", "retrying"),
    (FileNotFoundError("wb"), "cli_missing", "not installed"),
    (json.JSONDecodeError("bad", "x", 0), "parse", "could not be read"),
    (subprocess.CalledProcessError(2, ["wb"], stderr="password=hunter2 boom"), "cli_error",
     "exit 2"),
])
def test_errors_map_to_short_safe_messages(exc, code, phrase, monkeypatch):
    for name in ("STUDIO_WORKSPACE_ID", "WORKBENCH_WORKSPACE_ID", "WORKSPACE_ID"):
        monkeypatch.delenv(name, raising=False)
    err = discovery.classify(exc)
    assert err.code == code
    assert phrase in err.message
    assert "hunter2" not in err.message and len(err.message) < 200


def test_failure_without_snapshot_reports_failed(disc):
    disc["use"]({None: fail("Unauthorized: credentials expired")})
    db.warm_resource_cache()
    disc["spawned"].pop()()
    body = client.get("/api/datasources").json()
    assert body["ready"] is True
    assert body["discovery"]["status"] == "failed"
    assert body["discovery"]["error_code"] == "auth"
    assert not disc["path"].exists()


def test_missing_cli_is_unavailable_not_failed(disc):
    disc["use"]({None: FileNotFoundError("wb")})
    db._refresh_resource_cache()
    assert db.discovery_status()["status"] == "unavailable"


def test_one_broken_kind_still_lists_the_others(disc):
    discovery.save([AURORA, BQ], {})
    db.load_cached_resources()
    new_folder = dict(FOLDER, id="new-folder", uuid="u-n")
    cli = disc["use"]({
        None: fail("Error: BigQuery dataset reference cannot be resolved in an AWS workspace"),
        "AWS_AURORA_DATABASE": [AURORA],
        "AWS_S3_STORAGE_FOLDER": [new_folder],
        "BQ_DATASET": fail("Error: BigQuery dataset reference cannot be resolved"),
        "*": [],
    })

    db._refresh_resource_cache()

    listed = {next((a for a in c if a.startswith("--type=")), "--all") for c in cli.calls}
    assert {"--all", "--type=BQ_DATASET", "--type=AWS_S3_STORAGE_FOLDER"} <= listed
    body = client.get("/api/datasources").json()
    assert _ids(body, "aurora") == ["omop"]
    assert _ids(body, "s3") == ["new-folder"]       # current listing
    assert _ids(body, "bq") == ["bq-ref"]           # kept from the snapshot
    d = body["discovery"]
    assert d["status"] == "stale"
    assert d["failed_kinds"] == ["bq"]
    assert d["error_code"] == "partial"
    assert d["error"].startswith("BigQuery resources could not be listed")
    # A partial result does not overwrite the last complete snapshot.
    saved = json.loads(disc["path"].read_text())
    assert sorted(r["id"] for r in saved["resources"]) == ["bq-ref", "omop"]


def test_snapshot_holds_no_secrets_and_is_private(disc):
    leaky = dict(AURORA, password="hunter2", connectionString="postgresql://u:hunter2@h/db",
                 credentials={"secretAccessKey": "hunter2"}, description="x" * 10)
    ref = {"id": "omop-ref", "resourceType": "AWS_AURORA_DATABASE_REFERENCE",
           "referencedResource": dict(AURORA, password="hunter2",
                                      nested={"token": "hunter2"})}
    disc["use"]({None: [leaky, ref, FOLDER, {"id": "nb", "resourceType": "AWS_SAGEMAKER_NOTEBOOK"}]})
    db._s3_uri_cache["patient-data"] = "s3://bucket-1/patient-data"

    db._refresh_resource_cache()

    path = disc["path"]
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    text = path.read_text()
    assert "hunter2" not in text and "postgresql://" not in text
    saved = json.loads(text)
    assert set(saved) == {"version", "updated_at", "workspace_id", "resources", "s3_uris"}
    allowed = set(discovery._RESOURCE_FIELDS) | {"referencedResource"}
    for r in saved["resources"]:
        assert set(r) <= allowed
        assert set(r.get("referencedResource", {})) <= set(discovery._RESOURCE_FIELDS)
    assert [r["id"] for r in saved["resources"]] == ["omop", "omop-ref", "patient-data"]
    assert saved["s3_uris"] == {"patient-data": "s3://bucket-1/patient-data"}
    # The reference keeps what list_aurora_resources needs.
    db._reset_for_tests()
    db.load_cached_resources()
    assert {"id": "omop-ref", "database": "omopdb", "region": "us-east-1"} in db.list_aurora_resources()


def test_retry_backoff_is_bounded_and_never_stacks(disc, monkeypatch):
    delays = [discovery.retry_delay(n) for n in range(1, 12)]
    assert delays[:4] == [10, 20, 40, 80]
    assert max(delays) == discovery.RETRY_MAX_S == delays[-1]

    clock = [1000.0]
    monkeypatch.setattr(db, "_clock", lambda: clock[0])
    cli = disc["use"]({None: subprocess.TimeoutExpired(["wb"], 120)})

    assert db.request_refresh() is True
    assert db.request_refresh() is False            # in flight: no second listing
    assert db.request_refresh(manual=True) is False
    disc["spawned"].pop()()
    assert len(cli.calls) == 1                      # timeout is global: no per-type fan-out
    assert db.discovery_status()["error_code"] == "timeout"
    assert len(disc["timers"]) == 1

    # Polls during the backoff window do not start CLI calls.
    clock[0] += 5
    db.retry_if_empty()
    db.list_aurora_resources()
    assert disc["spawned"] == []

    # The timer fires: one retry, which fails again and doubles the wait.
    delay, fire = disc["timers"].pop()
    clock[0] += delay
    fire()
    assert len(disc["spawned"]) == 1
    disc["spawned"].pop()()
    assert disc["timers"][-1][0] == 2 * delay

    # Many failures later the wait stays capped.
    for _ in range(10):
        _, fire = disc["timers"].pop()
        fire()
        disc["spawned"].pop()()
    assert disc["timers"][-1][0] == discovery.RETRY_MAX_S
    assert len(disc["timers"]) == 1

    # A manual retry skips the wait (once per debounce window).
    assert db.request_refresh(manual=True) is True
    assert db.request_refresh(manual=True) is False
    disc["spawned"].pop()()
    clock[0] += discovery.MANUAL_DEBOUNCE_S + 1
    assert db.request_refresh(manual=True) is True


def test_refresh_endpoint_starts_background_refresh(disc):
    disc["use"]({None: [AURORA]})
    body = client.post("/api/datasources/refresh").json()
    assert body["started"] is True
    assert body["discovery"]["status"] == "refreshing"
    assert len(disc["spawned"]) == 1
    assert client.post("/api/datasources/refresh").json()["started"] is False
    disc["spawned"].pop()()
    assert db.discovery_status()["status"] == "fresh"
