import json
import logging
import subprocess
import threading
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_cohorts: dict[str, dict] = {}
_cohorts_lock = threading.Lock()
_folder_resource_id: str | None = None
_bucket_path: str | None = None


def _profile_args() -> list[str]:
    return ["--profile", _folder_resource_id] if _folder_resource_id else []


def _resolve_bucket_path() -> str:
    global _bucket_path
    if _bucket_path:
        return _bucket_path
    result = subprocess.run(
        ["wb", "resource", "resolve", "--id", _folder_resource_id],
        capture_output=True, text=True, check=True, timeout=120,
    ).stdout.strip().rstrip("/")
    _bucket_path = result
    return result


def _cohort_s3_key(name: str) -> str:
    safe_name = name.replace("/", "_").replace(" ", "_")
    return f"{_resolve_bucket_path()}/cohorts/{safe_name}.json"


def _load_from_s3():
    try:
        bucket = _resolve_bucket_path()
        result = subprocess.run(
            ["aws", "s3", "ls", *_profile_args(), f"{bucket}/cohorts/"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            logger.info("No cohorts folder in S3 yet")
            return

        files = [line.split()[-1] for line in result.stdout.strip().split("\n") if line.strip().endswith(".json")]
        for filename in files:
            try:
                content = subprocess.run(
                    ["aws", "s3", "cp", *_profile_args(), f"{bucket}/cohorts/{filename}", "-"],
                    capture_output=True, text=True, timeout=120,
                ).stdout.strip()
                cohort = json.loads(content)
                with _cohorts_lock:
                    _cohorts[cohort["name"]] = cohort
            except Exception as e:
                logger.warning("Failed to load cohort %s: %s", filename, e)

        logger.info("Loaded %d cohorts from S3", len(_cohorts))
    except Exception as e:
        logger.warning("Failed to load cohorts from S3: %s", e)


def _save_to_s3(cohort: dict):
    try:
        content = json.dumps(cohort, indent=2)
        s3_key = _cohort_s3_key(cohort["name"])
        proc = subprocess.run(
            ["aws", "s3", "cp", *_profile_args(), "-", s3_key, "--content-type", "application/json"],
            input=content, capture_output=True, text=True, timeout=120,
        )
        if proc.returncode == 0:
            logger.info("Saved cohort '%s' to S3", cohort["name"])
        else:
            logger.error("Failed to save cohort to S3: %s", proc.stderr)
    except Exception as e:
        logger.error("Failed to save cohort '%s' to S3: %s", cohort["name"], e)


def _delete_from_s3(name: str):
    try:
        s3_key = _cohort_s3_key(name)
        subprocess.run(
            ["aws", "s3", "rm", *_profile_args(), s3_key],
            capture_output=True, text=True, timeout=120,
        )
        logger.info("Deleted cohort '%s' from S3", name)
    except Exception as e:
        logger.error("Failed to delete cohort '%s' from S3: %s", name, e)


def init_cohorts(folder_resource_id: str):
    global _folder_resource_id
    _folder_resource_id = folder_resource_id
    threading.Thread(target=_load_from_s3, daemon=True).start()


def list_cohorts(datasource: str = "") -> list[dict]:
    with _cohorts_lock:
        results = []
        for c in _cohorts.values():
            if datasource and c.get("datasource", "") != datasource:
                continue
            results.append({
                "name": c["name"],
                "description": c.get("description", ""),
                "sampleCount": c.get("sampleCount", 0),
                "createdAt": c.get("createdAt"),
                "updatedAt": c.get("updatedAt"),
            })
        return results


def get_cohort(name: str) -> dict | None:
    with _cohorts_lock:
        return _cohorts.get(name)


def save_cohort(name: str, description: str, filters: dict, sample_count: int, datasource: str = "") -> dict:
    now = datetime.now(timezone.utc).isoformat()
    with _cohorts_lock:
        existing = _cohorts.get(name)
        cohort = {
            "name": name,
            "description": description,
            "datasource": datasource,
            "filters": filters,
            "sampleCount": sample_count,
            "createdAt": existing["createdAt"] if existing else now,
            "updatedAt": now,
        }
        _cohorts[name] = cohort
    if _folder_resource_id:
        threading.Thread(target=_save_to_s3, args=(cohort,), daemon=True).start()
    return cohort


def delete_cohort(name: str) -> bool:
    with _cohorts_lock:
        if name not in _cohorts:
            return False
        del _cohorts[name]
    if _folder_resource_id:
        threading.Thread(target=_delete_from_s3, args=(name,), daemon=True).start()
    return True


def cohort_exists(name: str) -> bool:
    with _cohorts_lock:
        return name in _cohorts
