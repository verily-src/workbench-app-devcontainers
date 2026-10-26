import csv
import hashlib
import io
import json

import pytest

import agent_results


RESOURCE = "nextflow-results"
RUN_ID = "workbench-run-01"
ENGINE_ID = "4806228"
OUTPUT_PATH = "cohort-studio/agent-plans/plan-123/results/job-123"
BASE_URI = "s3://results-bucket/managed"
INPUT_URI = "s3://inputs/cohort-studio/agent-plans/plan-123/cohort.csv"
ROOT_KEY = "managed/" + OUTPUT_PATH
PUBDIR = f"{ROOT_KEY}/{ENGINE_ID}/pubdir/"


def fixture_data():
    notice = agent_results.SYNTHETIC_NOTICE
    fields = agent_results.SUMMARY_COLUMNS
    summary = io.StringIO(newline="")
    writer = csv.DictWriter(summary, fieldnames=fields)
    writer.writeheader()
    writer.writerows([
        {"variant_id": "SYN_VAR_0021", "carrier_status": "carrier",
         "gender_concept_id": "8507", "birth_year_band": "1970s",
         "people": "1", "share_within_status": "1.0",
         "synthetic_notice": notice},
        {"variant_id": "SYN_VAR_0021", "carrier_status": "noncarrier",
         "gender_concept_id": "8532", "birth_year_band": "1980s",
         "people": "2", "share_within_status": "1.0",
         "synthetic_notice": notice},
    ])
    summary_bytes = summary.getvalue().encode()
    dictionary_bytes = (
        f"variant_id,gene_symbol,consequence,synthetic_notice\n"
        f"SYN_VAR_0021,SYN,missense,{notice}\n").encode()
    manifest = {
        "input": {"uri": INPUT_URI, "sha256": "a" * 64, "row_count": 3},
        "variant_dictionary": {"uri": "s3://dictionary/variant.csv",
                               "sha256": hashlib.sha256(dictionary_bytes).hexdigest(),
                               "row_count": 1},
        "cohort": {"cohort_size": 3, "matched_people": 3,
                   "unmatched_cohort_members": 0},
        "analysis": {"variant_id": "SYN_VAR_0021",
                     "carrier_definition": "dosage > 0",
                     "noncarrier_definition": "dosage = 0",
                     "status_counts": {"carrier": 1, "noncarrier": 2},
                     "summary_people_total": 3},
        "outputs": {
            "carrier_summary_csv": f"s3://results-bucket/{PUBDIR}carrier_summary.csv",
            "variant_dictionary_csv": f"s3://results-bucket/{PUBDIR}variant_dictionary.csv",
            "manifest_json": f"s3://results-bucket/{PUBDIR}run_manifest.json",
        },
        "outputs_sha256": {
            "carrier_summary_csv": hashlib.sha256(summary_bytes).hexdigest(),
            "variant_dictionary_csv": hashlib.sha256(dictionary_bytes).hexdigest(),
        },
        "execution": {"workflow_id": agent_results.WORKFLOW_ID,
                      "run_id": RUN_ID, "engine_run_id": ENGINE_ID},
        "synthetic_notice": notice,
    }
    manifest_bytes = json.dumps(manifest).encode()
    keys = {
        PUBDIR + "run_manifest.json": manifest_bytes,
        PUBDIR + "carrier_summary.csv": summary_bytes,
        PUBDIR + "variant_dictionary.csv": dictionary_bytes,
    }
    objects = [{"key": key, "size": len(content)} for key, content in keys.items()]
    calls = {"reads": [], "prefixes": []}
    def list_objects(resource, bucket, prefix):
        calls["prefixes"].append((resource, bucket, prefix))
        return objects
    def read_object(resource, bucket, key, limit):
        calls["reads"].append((resource, bucket, key, limit))
        return keys[key]
    return manifest, keys, objects, calls, list_objects, read_object


def run_info(**updates):
    return {"run_id": RUN_ID, "status": "COMPLETED",
            "output_bucket_resource": RESOURCE,
            "output_bucket_path": OUTPUT_PATH, **updates}


def verify(manifest, objects, list_objects, read_object, **kwargs):
    return agent_results.verify(
        run_info(), RESOURCE, 3, expected_input_uri=INPUT_URI,
        resolve_s3_uri=lambda _resource: BASE_URI,
        list_objects=list_objects, read_object=read_object, **kwargs)


def test_default_read_uses_bounded_cli_range_and_removes_tempfile(monkeypatch):
    from pathlib import Path
    import subprocess

    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        Path(args[-1]).write_bytes(b"bounded result")
        return subprocess.CompletedProcess(args, 0, stdout="{}", stderr="")

    monkeypatch.setattr(agent_results.subprocess, "run", fake_run)
    result = agent_results._default_read("resource", "bucket", "folder/file.json", 64)

    assert result == b"bounded result"
    assert captured["args"][:8] == [
        "aws", "s3api", "get-object", "--bucket", "bucket", "--key",
        "folder/file.json", "--range"]
    assert captured["args"][8] == "bytes=0-64"
    assert captured["args"][9:11] == ["--profile", "resource"]
    assert captured["kwargs"]["timeout"] == 30
    assert not Path(captured["args"][-1]).exists()


def test_default_read_rejects_oversize_response_and_removes_tempfile(monkeypatch):
    from pathlib import Path
    import subprocess

    captured = {}

    def fake_run(args, **kwargs):
        captured["path"] = Path(args[-1])
        captured["path"].write_bytes(b"012345")
        return subprocess.CompletedProcess(args, 0, stdout="{}", stderr="")

    monkeypatch.setattr(agent_results.subprocess, "run", fake_run)
    with pytest.raises(agent_results.ResultVerificationError, match="size limit"):
        agent_results._default_read("resource", "bucket", "key", 5)
    assert not captured["path"].exists()


def test_verify_completed_run_with_bounded_exact_output_prefix_and_checksum():
    _manifest, _keys, _objects, calls, list_objects, read_object = fixture_data()
    result = verify(_manifest, _objects, list_objects, read_object)
    assert result["verified"] is True
    assert result["run_id"] == RUN_ID
    assert result["engine_run_id"] == ENGINE_ID
    assert result["rows"] == 3
    assert result["integrity"] == "output-sha256-counts-schema"
    assert result["source_ref"] == {
        "kind": "s3", "resource_id": RESOURCE,
        "table": f"{OUTPUT_PATH}/{ENGINE_ID}/pubdir/carrier_summary.csv",
    }
    assert result["summary_csv"] == _keys[PUBDIR + "carrier_summary.csv"]
    assert calls["prefixes"] == [(RESOURCE, "results-bucket", ROOT_KEY)]
    assert len(calls["reads"]) == 3
    assert all(item[2].startswith(ROOT_KEY + "/") for item in calls["reads"])


def test_legacy_manifest_verifies_counts_schema_and_copied_dictionary_hash():
    manifest, keys, objects, calls, list_objects, read_object = fixture_data()
    manifest.pop("outputs_sha256")
    keys[PUBDIR + "run_manifest.json"] = json.dumps(manifest).encode()
    objects[0]["size"] = len(keys[PUBDIR + "run_manifest.json"])
    result = verify(manifest, objects, list_objects, read_object)
    assert result["integrity"] == "legacy-counts-schema-dictionary-sha256"


@pytest.mark.parametrize("change,expected", [
    (lambda manifest: manifest["outputs"].__setitem__(
        "carrier_summary_csv", "s3://attacker/out.csv"), "outside the approved"),
    (lambda manifest: manifest["input"].__setitem__("uri", "s3://attacker/in.csv"),
     "approved CSV"),
    (lambda manifest: manifest["execution"].__setitem__("run_id", "other-run"),
     "does not match Workbench"),
])
def test_manifest_cannot_select_unapproved_paths_or_identities(change, expected):
    manifest, keys, objects, _calls, list_objects, read_object = fixture_data()
    change(manifest)
    keys[PUBDIR + "run_manifest.json"] = json.dumps(manifest).encode()
    objects[0]["size"] = len(keys[PUBDIR + "run_manifest.json"])
    with pytest.raises(agent_results.ResultVerificationError, match=expected):
        verify(manifest, objects, list_objects, read_object)


def test_invalid_checksum_schema_counts_and_status_are_rejected():
    manifest, keys, objects, _calls, list_objects, read_object = fixture_data()
    manifest["outputs_sha256"]["carrier_summary_csv"] = "0" * 64
    keys[PUBDIR + "run_manifest.json"] = json.dumps(manifest).encode()
    objects[0]["size"] = len(keys[PUBDIR + "run_manifest.json"])
    with pytest.raises(agent_results.ResultVerificationError, match="checksum"):
        verify(manifest, objects, list_objects, read_object)

    manifest, keys, objects, _calls, list_objects, read_object = fixture_data()
    manifest["analysis"]["summary_people_total"] = 4
    keys[PUBDIR + "run_manifest.json"] = json.dumps(manifest).encode()
    objects[0]["size"] = len(keys[PUBDIR + "run_manifest.json"])
    with pytest.raises(agent_results.ResultVerificationError, match="summary count"):
        verify(manifest, objects, list_objects, read_object)

    manifest, keys, objects, _calls, list_objects, read_object = fixture_data()
    malformed = b"person_id,carrier_status\n1,carrier\n"
    keys[PUBDIR + "carrier_summary.csv"] = malformed
    manifest["outputs_sha256"]["carrier_summary_csv"] = hashlib.sha256(malformed).hexdigest()
    keys[PUBDIR + "run_manifest.json"] = json.dumps(manifest).encode()
    objects[0]["size"] = len(keys[PUBDIR + "run_manifest.json"])
    objects[1]["size"] = len(malformed)
    with pytest.raises(agent_results.ResultVerificationError, match="column schema"):
        verify(manifest, objects, list_objects, read_object)

    manifest, keys, objects, _calls, list_objects, read_object = fixture_data()
    manifest["variant_dictionary"]["row_count"] = 2
    keys[PUBDIR + "run_manifest.json"] = json.dumps(manifest).encode()
    objects[0]["size"] = len(keys[PUBDIR + "run_manifest.json"])
    with pytest.raises(agent_results.ResultVerificationError, match="dictionary row count"):
        verify(manifest, objects, list_objects, read_object)

    with pytest.raises(agent_results.ResultVerificationError, match="only after a completed"):
        agent_results.verify(run_info(status="RUNNING"), RESOURCE, 3,
                             expected_input_uri=INPUT_URI,
                             resolve_s3_uri=lambda _resource: BASE_URI,
                             list_objects=list_objects, read_object=read_object)


def test_listing_cannot_escape_run_prefix_or_exceed_size_limits():
    _manifest, _keys, objects, _calls, _list_objects, read_object = fixture_data()
    outside = lambda *_args: [{"key": "managed/other/run_manifest.json", "size": 1}]
    with pytest.raises(agent_results.ResultVerificationError, match="escaped"):
        verify({}, objects, outside, read_object)

    _manifest, _keys, objects, _calls, _list_objects, read_object = fixture_data()
    objects[0]["size"] = agent_results.MAX_MANIFEST_BYTES + 1
    with pytest.raises(agent_results.ResultVerificationError, match="size limit"):
        verify({}, objects, lambda *_args: objects, read_object)


def test_wrong_resource_and_expected_row_count_are_rejected():
    _manifest, _keys, _objects, _calls, list_objects, read_object = fixture_data()
    with pytest.raises(agent_results.ResultVerificationError, match="does not match the approved"):
        agent_results.verify(run_info(), "another-resource", 3,
                             expected_input_uri=INPUT_URI,
                             resolve_s3_uri=lambda _resource: BASE_URI,
                             list_objects=list_objects, read_object=read_object)

    with pytest.raises(agent_results.ResultVerificationError, match="prepared cohort"):
        agent_results.verify(run_info(), RESOURCE, 4,
                             expected_input_uri=INPUT_URI,
                             resolve_s3_uri=lambda _resource: BASE_URI,
                             list_objects=list_objects, read_object=read_object)


def test_default_listing_reads_one_bounded_s3_profile_page(monkeypatch):
    called = {}

    class Result:
        stdout = json.dumps({"IsTruncated": False, "Contents": [
            {"Key": "managed/run/file.csv", "Size": 5}]})

    def run(args, **kwargs):
        called["args"] = args
        called["kwargs"] = kwargs
        return Result()

    monkeypatch.setattr(agent_results.subprocess, "run", run)
    out = agent_results._default_list("resource-profile", "bucket", "managed/run")
    assert out == [{"key": "managed/run/file.csv", "size": 5}]
    assert called["args"][called["args"].index("--max-keys") + 1] == "1000"
    assert "--no-paginate" in called["args"]
    assert called["args"][called["args"].index("--profile") + 1] == "resource-profile"
    assert called["kwargs"]["timeout"] == 30
