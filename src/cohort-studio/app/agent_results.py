import csv
import hashlib
import io
import json
import math
import os
import re
import subprocess
import tempfile
from urllib.parse import urlsplit


WORKFLOW_ID = "cohort-genetics-demo"
ENGINE_RUN_ID = re.compile(r"^[0-9]+$")
MAX_OBJECTS = 1000
MAX_MANIFEST_BYTES = 256 * 1024
MAX_SUMMARY_BYTES = 8 * 1024 * 1024
MAX_DICTIONARY_BYTES = 4 * 1024 * 1024
MAX_SUMMARY_ROWS = 2000
DEMO_VARIANT_ID = "SYN_VAR_0021"
SYNTHETIC_NOTICE = (
    "Synthetic genotype values and annotations are for workflow demonstration "
    "only; no clinical or causal interpretation."
)
SUMMARY_COLUMNS = (
    "variant_id", "carrier_status", "gender_concept_id", "birth_year_band",
    "people", "share_within_status", "synthetic_notice",
)
DICTIONARY_COLUMNS = ("variant_id", "gene_symbol", "consequence", "synthetic_notice")


class ResultVerificationError(ValueError):
    pass


def _safe_output_path(path: str) -> str:
    if (not isinstance(path, str) or not path or path.startswith("/")
            or "\\" in path or any(part in {"", ".", ".."}
                                    for part in path.split("/"))):
        raise ResultVerificationError("Workflow output path is invalid.")
    return path


def _default_resolve(resource_id: str) -> str:
    try:
        import database as db
    except ModuleNotFoundError:
        import db
    try:
        return db.resolve_s3_uri(resource_id)
    except Exception as error:
        raise ResultVerificationError("Could not resolve the approved output resource.") from error


def _default_list(resource_id: str, bucket: str, prefix: str) -> list[dict]:
    try:
        result = subprocess.run(
            ["aws", "s3api", "list-objects-v2", "--bucket", bucket,
             "--prefix", prefix.rstrip("/") + "/", "--max-keys", str(MAX_OBJECTS),
             "--profile", resource_id, "--output", "json", "--no-paginate"],
            capture_output=True, text=True, timeout=30, check=True)
    except Exception as error:
        raise ResultVerificationError("Could not list the approved workflow output folder.") from error
    response = json.loads(result.stdout or "{}")
    if response.get("IsTruncated"):
        raise ResultVerificationError("Workflow output folder contains too many objects to verify safely.")
    return [{"key": item.get("Key"), "size": item.get("Size")}
            for item in response.get("Contents", [])]


def _default_read(resource_id: str, bucket: str, key: str,
                  max_bytes: int) -> bytes:
    filename = None
    try:
        with tempfile.NamedTemporaryFile(delete=False) as target:
            filename = target.name
        subprocess.run(
            ["aws", "s3api", "get-object", "--bucket", bucket,
             "--key", key, "--range", f"bytes=0-{max_bytes}",
             "--profile", resource_id, filename],
            capture_output=True, text=True, timeout=30, check=True)
        if os.path.getsize(filename) > max_bytes:
            raise ResultVerificationError(
                "Workflow output file exceeds the verification size limit.")
        with open(filename, "rb") as source:
            content = source.read(max_bytes + 1)
    except Exception as error:
        if isinstance(error, ResultVerificationError):
            raise
        raise ResultVerificationError("Could not read an approved workflow output file.") from error
    finally:
        if filename:
            try:
                os.unlink(filename)
            except FileNotFoundError:
                pass
    return content


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _required_mapping(value: object, name: str) -> dict:
    if not isinstance(value, dict):
        raise ResultVerificationError(f"Workflow manifest {name} section is invalid.")
    return value


def _parse_summary(content: bytes, manifest: dict, expected_rows: int | None) -> dict:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ResultVerificationError("Carrier summary is not valid UTF-8 CSV.") from error
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if tuple(reader.fieldnames or ()) != SUMMARY_COLUMNS:
        raise ResultVerificationError("Carrier summary has an unexpected column schema.")

    analysis = _required_mapping(manifest.get("analysis"), "analysis")
    variant_id = analysis.get("variant_id")
    notice = manifest.get("synthetic_notice")
    status_people = {"carrier": 0, "noncarrier": 0}
    status_shares = {"carrier": 0.0, "noncarrier": 0.0}
    total_people = 0
    rows = []
    for row in reader:
        if len(rows) >= MAX_SUMMARY_ROWS:
            raise ResultVerificationError("Carrier summary has too many strata.")
        if None in row:
            raise ResultVerificationError("Carrier summary contains extra CSV fields.")
        status = row.get("carrier_status")
        if status not in status_people or row.get("variant_id") != variant_id:
            raise ResultVerificationError("Carrier summary has an invalid variant or carrier status.")
        if row.get("synthetic_notice") != notice or not isinstance(notice, str) or not notice:
            raise ResultVerificationError("Carrier summary is missing the synthetic-data notice.")
        gender = row.get("gender_concept_id", "")
        band = row.get("birth_year_band", "")
        if gender != "unknown" and not gender.isdigit():
            raise ResultVerificationError("Carrier summary contains an invalid gender stratum.")
        if band != "unknown" and re.fullmatch(r"[0-9]{4}s", band) is None:
            raise ResultVerificationError("Carrier summary contains an invalid birth-year band.")
        try:
            people = int(row["people"])
            share = float(row["share_within_status"])
        except (TypeError, ValueError) as error:
            raise ResultVerificationError("Carrier summary contains invalid count values.") from error
        if people < 1 or not math.isfinite(share) or not 0 < share <= 1:
            raise ResultVerificationError("Carrier summary contains invalid count or share values.")
        status_people[status] += people
        status_shares[status] += share
        total_people += people
        rows.append(row)

    expected_status_counts = _required_mapping(
        analysis.get("status_counts"), "analysis status_counts")
    if status_people != {key: int(expected_status_counts.get(key, -1))
                         for key in status_people}:
        raise ResultVerificationError("Carrier summary counts do not match manifest status counts.")
    if any(count and not math.isclose(status_shares[key], 1.0, rel_tol=1e-6, abs_tol=1e-6)
           for key, count in status_people.items()):
        raise ResultVerificationError("Carrier summary shares do not sum to one within each status.")
    if int(analysis.get("summary_people_total", -1)) != total_people:
        raise ResultVerificationError("Carrier summary total does not match the manifest.")
    if expected_rows is not None and total_people != expected_rows:
        raise ResultVerificationError("Carrier summary rows do not match the prepared cohort count.")
    return {"strata": len(rows), "people": total_people,
            "status_counts": status_people}


def _parse_dictionary(content: bytes, manifest: dict) -> int:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ResultVerificationError("Variant dictionary is not valid UTF-8 CSV.") from error
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if tuple(reader.fieldnames or ()) != DICTIONARY_COLUMNS:
        raise ResultVerificationError("Variant dictionary has an unexpected column schema.")
    metadata = _required_mapping(manifest.get("variant_dictionary"), "variant_dictionary")
    seen = set()
    count = 0
    for row in reader:
        if count >= MAX_SUMMARY_ROWS:
            raise ResultVerificationError("Variant dictionary has too many rows to verify safely.")
        if None in row or any(not row.get(column) for column in DICTIONARY_COLUMNS):
            raise ResultVerificationError("Variant dictionary contains an invalid row.")
        if row["variant_id"] in seen:
            raise ResultVerificationError("Variant dictionary contains duplicate variant IDs.")
        if row["synthetic_notice"] != SYNTHETIC_NOTICE:
            raise ResultVerificationError("Variant dictionary is missing the synthetic-data notice.")
        seen.add(row["variant_id"])
        count += 1
    if count != metadata.get("row_count") or DEMO_VARIANT_ID not in seen:
        raise ResultVerificationError("Variant dictionary row count or variant identity is invalid.")
    return count


def verify(run: dict, output_resource_id: str,
           expected_rows: int | None = None, *, expected_input_uri: str,
           resolve_s3_uri=None, list_objects=None, read_object=None) -> dict:
    if not isinstance(run, dict):
        raise ResultVerificationError("Workflow run metadata is invalid.")
    run_id = run.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ResultVerificationError("Workflow run ID is missing.")
    if (run.get("status") or "").upper() != "COMPLETED":
        raise ResultVerificationError("Workflow results are available only after a completed run.")
    if run.get("output_bucket_resource") != output_resource_id:
        raise ResultVerificationError("Workflow output resource does not match the approved resource.")
    if not isinstance(expected_input_uri, str) or urlsplit(expected_input_uri).scheme != "s3":
        raise ResultVerificationError("Approved input URI is invalid.")
    input_parts = urlsplit(expected_input_uri)
    if (not input_parts.netloc or input_parts.username or input_parts.password
            or input_parts.query or input_parts.fragment):
        raise ResultVerificationError("Approved input URI is invalid.")

    output_path = _safe_output_path(run.get("output_bucket_path"))
    resolve = resolve_s3_uri or _default_resolve
    list_fn = list_objects or _default_list
    read_fn = read_object or _default_read
    if expected_rows is not None and (not isinstance(expected_rows, int)
                                      or isinstance(expected_rows, bool)
                                      or expected_rows < 0):
        raise ResultVerificationError("Expected cohort row count is invalid.")
    try:
        base_uri = resolve(output_resource_id)
    except ResultVerificationError:
        raise
    except Exception as error:
        raise ResultVerificationError("Could not resolve the approved output resource.") from error
    parsed_base = urlsplit(base_uri)
    if (parsed_base.scheme != "s3" or not parsed_base.netloc
            or parsed_base.username or parsed_base.password
            or parsed_base.query or parsed_base.fragment):
        raise ResultVerificationError("Output resource did not resolve to a valid S3 folder.")
    base_key = parsed_base.path.strip("/")
    relative_prefix = "/".join(part for part in (base_key, output_path) if part)
    try:
        objects = list_fn(output_resource_id, parsed_base.netloc, relative_prefix)
    except ResultVerificationError:
        raise
    except Exception as error:
        raise ResultVerificationError("Could not list the approved workflow output folder.") from error
    if not isinstance(objects, list) or len(objects) > MAX_OBJECTS:
        raise ResultVerificationError("Workflow output listing exceeded the verification limit.")

    listed = {}
    prefix_with_slash = relative_prefix.rstrip("/") + "/"
    for item in objects:
        if not isinstance(item, dict):
            raise ResultVerificationError("Workflow output listing is invalid.")
        key = item.get("key", item.get("Key"))
        size = item.get("size", item.get("Size"))
        if (not isinstance(key, str) or not key.startswith(prefix_with_slash)
                or not isinstance(size, int) or size < 0):
            raise ResultVerificationError("Workflow output listing escaped the approved run folder.")
        listed[key] = size

    suffix = re.compile(re.escape(prefix_with_slash) + r"([0-9]+)/pubdir/run_manifest\.json$")
    manifests = [(key, match.group(1)) for key in listed
                 if (match := suffix.fullmatch(key))]
    if len(manifests) != 1:
        raise ResultVerificationError("Expected one run manifest under the completed output path.")
    manifest_key, engine_run_id = manifests[0]
    if not ENGINE_RUN_ID.fullmatch(engine_run_id):
        raise ResultVerificationError("HealthOmics engine run ID is invalid.")
    pubdir = f"{prefix_with_slash}{engine_run_id}/pubdir/"
    summary_key = pubdir + "carrier_summary.csv"
    dictionary_key = pubdir + "variant_dictionary.csv"
    if summary_key not in listed or dictionary_key not in listed:
        raise ResultVerificationError("Completed workflow output is missing required files.")
    limits = {manifest_key: MAX_MANIFEST_BYTES,
              summary_key: MAX_SUMMARY_BYTES,
              dictionary_key: MAX_DICTIONARY_BYTES}
    if any(listed[key] > limit for key, limit in limits.items()):
        raise ResultVerificationError("Workflow output file exceeds the verification size limit.")

    manifest_uri = f"s3://{parsed_base.netloc}/{manifest_key}"
    summary_uri = f"s3://{parsed_base.netloc}/{summary_key}"
    dictionary_uri = f"s3://{parsed_base.netloc}/{dictionary_key}"
    try:
        manifest_bytes = read_fn(output_resource_id, parsed_base.netloc,
                                 manifest_key, MAX_MANIFEST_BYTES)
        summary_bytes = read_fn(output_resource_id, parsed_base.netloc,
                                summary_key, MAX_SUMMARY_BYTES)
        dictionary_bytes = read_fn(output_resource_id, parsed_base.netloc,
                                   dictionary_key, MAX_DICTIONARY_BYTES)
    except ResultVerificationError:
        raise
    except Exception as error:
        raise ResultVerificationError("Could not read approved workflow output files.") from error
    if not all(isinstance(value, bytes) for value in
               (manifest_bytes, summary_bytes, dictionary_bytes)):
        raise ResultVerificationError("S3 output reader returned invalid data.")
    if (len(manifest_bytes) != listed[manifest_key]
            or len(summary_bytes) != listed[summary_key]
            or len(dictionary_bytes) != listed[dictionary_key]
            or len(manifest_bytes) > MAX_MANIFEST_BYTES
            or len(summary_bytes) > MAX_SUMMARY_BYTES
            or len(dictionary_bytes) > MAX_DICTIONARY_BYTES):
        raise ResultVerificationError("Workflow output size changed during bounded verification.")
    try:
        manifest = json.loads(manifest_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ResultVerificationError("Workflow manifest is not valid JSON.") from error
    if not isinstance(manifest, dict):
        raise ResultVerificationError("Workflow manifest is invalid.")

    execution = _required_mapping(manifest.get("execution"), "execution")
    if execution.get("workflow_id") != WORKFLOW_ID:
        raise ResultVerificationError("Workflow manifest identity does not match this workflow.")
    if execution.get("run_id") and execution["run_id"] != run_id:
        raise ResultVerificationError("Workflow manifest run ID does not match Workbench.")
    if str(execution.get("engine_run_id")) != engine_run_id:
        raise ResultVerificationError("Workflow manifest engine run ID does not match its output folder.")

    input_info = _required_mapping(manifest.get("input"), "input")
    if input_info.get("uri") != expected_input_uri:
        raise ResultVerificationError("Workflow manifest input does not match the approved CSV.")
    input_count = input_info.get("row_count")
    if not isinstance(input_count, int) or input_count < 0:
        raise ResultVerificationError("Workflow manifest input row count is invalid.")
    if expected_rows is not None and input_count != expected_rows:
        raise ResultVerificationError("Workflow manifest input count does not match the prepared cohort.")
    for name in ("input", "variant_dictionary"):
        section = _required_mapping(manifest.get(name), name)
        digest = section.get("sha256")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-fA-F]{64}", digest) is None:
            raise ResultVerificationError(f"Workflow manifest {name} checksum is invalid.")

    cohort = _required_mapping(manifest.get("cohort"), "cohort")
    analysis = _required_mapping(manifest.get("analysis"), "analysis")
    if (analysis.get("variant_id") != DEMO_VARIANT_ID
            or analysis.get("carrier_definition") != "dosage > 0"
            or analysis.get("noncarrier_definition") != "dosage = 0"):
        raise ResultVerificationError("Workflow manifest analysis identity is invalid.")
    if manifest.get("synthetic_notice") != SYNTHETIC_NOTICE:
        raise ResultVerificationError("Workflow manifest is missing the synthetic-data notice.")
    matched = cohort.get("matched_people")
    if not isinstance(matched, int) or matched != input_count:
        raise ResultVerificationError("Workflow manifest matched-person count is inconsistent.")
    if expected_rows is not None and matched != expected_rows:
        raise ResultVerificationError("Workflow matched-person count does not match the prepared cohort.")
    if int(analysis.get("summary_people_total", -1)) != matched:
        raise ResultVerificationError("Workflow summary count does not match matched people.")
    output_locations = _required_mapping(manifest.get("outputs"), "outputs")
    expected_locations = {
        "carrier_summary_csv": summary_uri,
        "variant_dictionary_csv": dictionary_uri,
        "manifest_json": manifest_uri,
    }
    for name, expected_uri in expected_locations.items():
        if output_locations.get(name) != expected_uri:
            raise ResultVerificationError("Workflow manifest output path is outside the approved run folder.")

    summary = _parse_summary(summary_bytes, manifest, expected_rows)
    _parse_dictionary(dictionary_bytes, manifest)
    actual_hashes = {"carrier_summary_csv": _sha256(summary_bytes),
                     "variant_dictionary_csv": _sha256(dictionary_bytes)}
    if actual_hashes["variant_dictionary_csv"] != manifest["variant_dictionary"]["sha256"]:
        raise ResultVerificationError("Copied variant dictionary checksum does not match manifest.")
    checksums = manifest.get("outputs_sha256")
    if checksums is None:
        integrity = "legacy-counts-schema-dictionary-sha256"
    else:
        checksums = _required_mapping(checksums, "outputs_sha256")
        if any(checksums.get(name) != digest for name, digest in actual_hashes.items()):
            raise ResultVerificationError("Workflow output checksum does not match the manifest.")
        integrity = "output-sha256-counts-schema"

    summary_relative = "/".join(part for part in (output_path, engine_run_id,
                                                   "pubdir", "carrier_summary.csv") if part)
    return {
        "verified": True,
        "run_id": run_id,
        "engine_run_id": engine_run_id,
        "rows": summary["people"],
        "integrity": integrity,
        "summary_sha256": actual_hashes["carrier_summary_csv"],
        "dictionary_sha256": actual_hashes["variant_dictionary_csv"],
        "summary_uri": summary_uri,
        "manifest_uri": manifest_uri,
        "source_ref": {"kind": "s3", "resource_id": output_resource_id,
                       "table": summary_relative},
        "summary_csv": summary_bytes,
        "strata": summary["strata"],
        "status_counts": summary["status_counts"],
    }
