import copy
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import queries
import agent_plan_store
import agent_store


WORKFLOW_ID = "cohort-genetics-demo"
REQUIRED_INPUT_COLUMNS = (
    "person_id", "sample_id", "variant_id", "dosage",
    "gender_concept_id", "year_of_birth",
)
PLAN_TTL = 30 * 60
MAX_PLANS = 128

class PlanNotFound(KeyError):
    pass


class PlanOwnerMismatch(PermissionError):
    pass


class PlanError(ValueError):
    pass


class _PlanValidationFailure(PlanError):
    pass


def _safe_error(error: Exception) -> str:
    if isinstance(error, _PlanValidationFailure):
        return str(error).splitlines()[0][:240] or "Operation failed."
    return "The validation or approval service failed. Check the selected resources and try again."


def _s3_uri(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme == "s3" and bool(parsed.netloc) and not parsed.query and not parsed.fragment


def _fingerprint(info: dict) -> str:
    explicit = info.get("fingerprint")
    encoded = json.dumps({"source_fingerprint": explicit or info.get("source_ref"),
                          "columns": sorted(info.get("columns") or []),
                          "column_mapping": info.get("column_mapping") or {}},
                         sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _public(plan: dict) -> dict:
    return {
        "id": plan["id"],
        "workflow": WORKFLOW_ID,
        "dataset_id": plan["dataset_id"],
        "filters": json.loads(plan["filters_json"]),
        **({"source_ref": copy.deepcopy(plan["source_ref"])} if plan.get("source_ref") else {}),
        "rows": plan["rows"],
        "required_columns": list(REQUIRED_INPUT_COLUMNS),
        "column_mapping": copy.deepcopy(plan["column_mapping"]),
        "input_resource_id": plan["input_resource_id"],
        "output_resource_id": plan["output_resource_id"],
        "output_path": plan["output_path"],
        "status": plan["status"],
        "errors": list(plan["errors"]),
        **({"input_uri": plan["input_uri"]} if plan.get("input_uri") else {}),
        **({"params_uri": plan["params_uri"]} if plan.get("params_uri") else {}),
        **({"export": copy.deepcopy(plan["export"])} if plan.get("export") else {}),
        **({"run": copy.deepcopy(plan["run"])} if plan.get("run") else {}),
        **({"results_location": copy.deepcopy(plan["results_location"])}
           if plan.get("results_location") else {}),
    }


def _repo(store=None):
    return store if store is not None else agent_plan_store.AgentPlanStore()


def _translate_store_error(error):
    if isinstance(error, agent_store.AgentStoreOwnershipError):
        raise PlanOwnerMismatch(str(error)) from error
    if isinstance(error, agent_store.AgentStoreNotFound):
        raise PlanNotFound(str(error)) from error
    raise error


def prepare(dataset_id: str, input_resource_id: str,
            output_resource_id: str, filters: list[dict], owner: str, *,
            inspect_dataset, list_workflows, resolve_s3_resource, store=None) -> dict:
    owner = owner.strip() if isinstance(owner, str) else ""
    if not owner:
        raise PlanError("An authenticated owner is required.")
    if not dataset_id or not input_resource_id or not output_resource_id:
        raise PlanError("Dataset, input S3 resource, and output S3 resource are required.")
    try:
        if not isinstance(filters, list):
            raise PlanError("Filters must be a list.")
        frozen_filters = json.dumps(filters, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise PlanError("Filters must be JSON values.") from error

    errors = []
    rows = 0
    column_mapping = {}
    info = {}
    try:
        info = inspect_dataset(dataset_id, json.loads(frozen_filters))
        rows = int(info.get("rows", 0))
        columns = set(info.get("columns") or [])
        suggested_mapping = info.get("column_mapping") or {}
        for column in REQUIRED_INPUT_COLUMNS:
            actual = column if column in columns else suggested_mapping.get(column)
            if isinstance(actual, str) and actual in columns:
                column_mapping[column] = actual
        missing = [column for column in REQUIRED_INPUT_COLUMNS
                   if column not in column_mapping]
        if info.get("capped"):
            errors.append("The selected dataset is sampled or capped; a complete cohort is required.")
        if rows < 1:
            errors.append("The selected filters match no rows.")
        if rows >= queries.ROW_CAP:
            errors.append(f"The cohort has {rows} rows; synchronous export supports fewer than {queries.ROW_CAP}.")
        if missing:
            errors.append("Required input columns are missing: " + ", ".join(missing))
        dataset_fingerprint = _fingerprint(info)
    except Exception as error:
        errors.append("Dataset validation failed: " + _safe_error(error))
        dataset_fingerprint = ""

    try:
        registry = list_workflows()
        registered = next((item for item in registry.get("workflows", [])
                           if item.get("id") == WORKFLOW_ID), None)
        if not registry.get("available") or not registered:
            errors.append("The cohort genetics workflow is not available in the registry.")
        elif (registered.get("type") or "").upper() != "NEXTFLOW":
            errors.append("The cohort genetics workflow is not registered as Nextflow.")
    except Exception as error:
        errors.append("Workflow registry check failed: " + _safe_error(error))

    resources = {}
    for role, resource_id in (("input", input_resource_id),
                              ("output", output_resource_id)):
        try:
            uri = resolve_s3_resource(resource_id)
            if not isinstance(uri, str) or not _s3_uri(uri):
                errors.append(f"The {role} resource must resolve to an S3 URI.")
            else:
                resources[role] = uri.rstrip("/")
        except Exception as error:
            errors.append(f"The {role} S3 resource could not be validated: "
                          f"{_safe_error(error)}")

    plan_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=PLAN_TTL)
    input_path = f"cohort-studio/agent-plans/{plan_id}/cohort.csv"
    params_path = f"cohort-studio/agent-plans/{plan_id}/params.json"
    output_path = f"cohort-studio/agent-plans/{plan_id}/results"
    plan = {
        "id": plan_id,
        "created_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "dataset_id": dataset_id,
        "filters_json": frozen_filters,
        "source_ref": copy.deepcopy(info.get("source_ref")) if isinstance(info, dict) else None,
        "dataset_fingerprint": dataset_fingerprint,
        "column_mapping": column_mapping,
        "rows": rows,
        "input_resource_id": input_resource_id,
        "output_resource_id": output_resource_id,
        "input_uri": (f"{resources['input']}/{input_path}"
                      if "input" in resources else None),
        "params_uri": (f"{resources['input']}/{params_path}"
                       if "input" in resources else None),
        "input_path": input_path,
        "params_path": params_path,
        "output_path": output_path,
        "job_id": f"cohort-genetics-{plan_id[:12]}",
        "status": "blocked" if errors else "ready",
        "errors": errors,
    }
    try:
        _repo(store).save(plan_id, owner, plan, expires_at)
    except agent_store.AgentStoreError as error:
        _translate_store_error(error)
    return _public(plan)


def get_plan(plan_id: str, owner: str, *, store=None) -> dict:
    try:
        return _public(_repo(store).get(plan_id, owner))
    except agent_store.AgentStoreError as error:
        _translate_store_error(error)


def list_plans(owner: str, *, limit: int = 30, store=None) -> list[dict]:
    try:
        return [_public(plan) for plan in _repo(store).list(owner, limit=limit)]
    except agent_store.AgentStoreError as error:
        _translate_store_error(error)


def approve(plan_id: str, owner: str, *, inspect_dataset, export_cohort,
            submit_workflow, store=None) -> dict:
    repository = _repo(store)
    try:
        snapshot = repository.claim(plan_id, owner)
        if snapshot is None:
            return _public(repository.get(plan_id, owner))
    except agent_store.AgentStoreError as error:
        _translate_store_error(error)

    filters = json.loads(snapshot["filters_json"])
    submission_started = False
    try:
        current = inspect_dataset(snapshot["dataset_id"], copy.deepcopy(filters))
        if _fingerprint(current) != snapshot["dataset_fingerprint"]:
            raise _PlanValidationFailure("Dataset source or columns changed after preparation; prepare again.")
        if int(current.get("rows", 0)) != snapshot["rows"]:
            raise _PlanValidationFailure("Filtered row count changed after preparation; prepare again.")
        if current.get("capped"):
            raise _PlanValidationFailure("Dataset became sampled or capped after preparation; prepare again.")
        if int(current.get("rows", 0)) >= queries.ROW_CAP:
            raise _PlanValidationFailure("The cohort now exceeds the synchronous export row limit; prepare again.")
        current_columns = set(current.get("columns") or [])
        current_mapping = {}
        suggestions = current.get("column_mapping") or {}
        for column in REQUIRED_INPUT_COLUMNS:
            actual = column if column in current_columns else suggestions.get(column)
            if isinstance(actual, str) and actual in current_columns:
                current_mapping[column] = actual
        if current_mapping != snapshot["column_mapping"]:
            raise _PlanValidationFailure("Required input columns changed after preparation; prepare again.")
        exported = export_cohort(
            snapshot["dataset_id"], snapshot["input_resource_id"],
            snapshot["input_path"], filters,
            copy.deepcopy(snapshot["column_mapping"]))
        if int(exported.get("rows", -1)) != snapshot["rows"]:
            raise _PlanValidationFailure("Export row count changed after preparation; no workflow was submitted.")
        if exported.get("s3_uri") != snapshot["input_uri"]:
            raise _PlanValidationFailure("Export did not write to the approved input path; no workflow was submitted.")
        snapshot["export"] = {"s3_uri": exported["s3_uri"], "rows": snapshot["rows"]}
        repository.update(plan_id, owner, snapshot)
        submission_started = True
        run = submit_workflow(
            WORKFLOW_ID, snapshot["input_resource_id"], snapshot["input_path"],
            snapshot["output_resource_id"], snapshot["output_path"],
            snapshot["input_resource_id"], snapshot["params_path"],
            snapshot["job_id"])
        if not isinstance(run, dict):
            raise _PlanValidationFailure("Workflow submit returned no job metadata.")
        if not isinstance(run.get("run_id"), str) or not run["run_id"].strip():
            raise _PlanValidationFailure("Workflow submit returned no run ID.")
        safe_run = {key: run[key] for key in (
            "run_id", "name", "status", "workflow_type", "engine_type",
            "output_bucket_uuid", "output_bucket_resource", "output_bucket_path")
                    if run.get(key) is not None}
        snapshot["run"] = safe_run
        snapshot["status"] = "submitted"
        if any(run.get(key) is not None for key in (
                "output_bucket_uuid", "output_bucket_resource", "output_bucket_path")):
            snapshot["results_location"] = {
                key: run[key] for key in (
                    "output_bucket_uuid", "output_bucket_resource", "output_bucket_path")
                if run.get(key) is not None}
        repository.update(plan_id, owner, snapshot)
        return _public(snapshot)
    except Exception as error:
        snapshot["status"] = "submission_unknown" if submission_started else "failed"
        snapshot["errors"] = (["Submission state is unknown. Check workflow jobs before taking action."]
                               if submission_started else [_safe_error(error)])
        try:
            repository.update(plan_id, owner, snapshot)
        except agent_store.AgentStoreError as store_error:
            _translate_store_error(store_error)
        return _public(snapshot)


def status(plan_id: str, owner: str, *, list_jobs, store=None) -> dict:
    repository = _repo(store)
    try:
        snapshot = copy.deepcopy(repository.get(plan_id, owner))
    except agent_store.AgentStoreError as error:
        _translate_store_error(error)
    run_id = (snapshot.get("run") or {}).get("run_id")
    recovering = snapshot["status"] in {"submitting", "submission_unknown"}
    if not recovering and (snapshot["status"] not in {"submitted", "running"} or not run_id):
        return _public(snapshot)
    try:
        try:
            jobs = list_jobs(limit=1000, force=True)
        except TypeError as error:
            if "limit" not in str(error):
                raise
            jobs = list_jobs(force=True)
        job = None
        if recovering and jobs.get("available", True):
            expected_output = f"{snapshot['output_path'].strip('/')}/{snapshot['job_id']}"
            matches = [item for item in jobs.get("jobs", [])
                       if item.get("name") == snapshot["job_id"]
                       and item.get("output_bucket_resource") == snapshot["output_resource_id"]
                       and isinstance(item.get("output_bucket_path"), str)
                       and item["output_bucket_path"].strip("/") == expected_output]
            if len(matches) > 1:
                snapshot["status"] = "submission_unknown"
                snapshot["errors"] = ["Multiple workflow jobs match this plan; check jobs before taking action."]
            elif matches:
                job = matches[0]
            else:
                snapshot["status"] = "submission_unknown"
                snapshot["errors"] = ["No exact matching workflow job was found. Check workflow jobs manually."]
        elif run_id and jobs.get("available", True):
            job = next((item for item in jobs.get("jobs", [])
                        if item.get("run_id") == run_id), None)
        if job:
            safe_run = {key: job[key] for key in (
                "run_id", "name", "status", "workflow_type", "engine_type",
                "output_bucket_uuid", "output_bucket_resource", "output_bucket_path")
                        if job.get(key) is not None}
            snapshot["run"] = safe_run
            status_value = (safe_run.get("status") or "").upper()
            snapshot["status"] = (
                    "completed" if status_value == "COMPLETED" else
                    "failed" if status_value in {"FAILED", "CANCELLED", "CANCELED", "DELETED"}
                    else "running")
            if any(safe_run.get(key) is not None for key in (
                    "output_bucket_uuid", "output_bucket_resource", "output_bucket_path")):
                snapshot["results_location"] = {
                    key: safe_run[key] for key in (
                        "output_bucket_uuid", "output_bucket_resource", "output_bucket_path")
                    if safe_run.get(key) is not None}
            repository.update(plan_id, owner, snapshot)
            return _public(snapshot)
        if recovering and jobs.get("available", True):
            repository.update(plan_id, owner, snapshot)
            return _public(snapshot)
    except Exception:
        pass
    return _public(snapshot)
