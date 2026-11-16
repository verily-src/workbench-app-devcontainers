"""Data loading layer for the Harmony Data Harmonization Dashboard.

Directory structure under HARMONY_GCS_PATH (or HARMONY_LOCAL_PATH):
  mapping/
    {run_folder}/                  # any folder containing 'run_' or 'output_'
      {iter_folder}/               # e.g., iter_001, iter_1
        summary.md
        coverage.md
        unmapped_columns.json
        {passed_source_table}/
          rubrics.md               # coverage, dq, llm_judge, reasonableness
          query.sql                # EPIC -> FHIR transformation SQL
          resource.jsonl           # transformed FHIR records
  audit/
    {run_folder}/                  # any folder containing 'run_' or 'output_'
      anomalies_dumped.md          # optional
      {iter_folder}/
        report.md                  # identified issues
        fixes.md                   # remedies applied from library
        sanity_check.md            # post-fix verification

Environment variables:
  HARMONY_GCS_PATH    gs://bucket/experimental/run_artifacts
  HARMONY_LOCAL_PATH  /path/to/run_artifacts
"""

import functools
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path


GCS_BUCKET = os.environ["GCS_BUCKET"]
GCS_ROOT_PREFIX = os.environ["GCS_ROOT_PREFIX"]

@dataclass
class RunMeta:
    run_id: str
    started_at: str = ""
    mapping_path: str = ""
    audit_path: str = ""


@functools.lru_cache(maxsize=1)
def _gcs_client():
    from google.cloud import storage  # noqa: PLC0415
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip() or None
    return storage.Client(project=project)


def _gcs_bucket_and_prefix(gs_path: str) -> tuple[str, str]:
    without = gs_path[5:]
    parts = without.split("/", 1)
    return parts[0], (parts[1] if len(parts) > 1 else "")


def _format_gcs_error(exc: Exception, gs_path: str) -> str:
    msg = str(exc)
    if "vpcServiceControlsUniqueIdentifier" in msg or "403" in msg:
        return (
            f"Access denied (403 / VPC Service Controls) reading `{gs_path}`. "
            "Switch to a mounted local path (`HARMONY_LOCAL_PATH`) or a bucket within this workspace's perimeter."
        )
    return f"GCS error accessing `{gs_path}`: {msg}"


def _gcs_read_text(gs_path: str) -> str | None:
    try:
        bucket_name, blob_name = _gcs_bucket_and_prefix(gs_path)
        blob = _gcs_client().bucket(bucket_name).blob(blob_name)
        return blob.download_as_text()
    except Exception:
        return None


def _gcs_list_prefixes_safe(gs_prefix: str) -> tuple[list[str], str]:
    """Return (immediate child directory prefixes, error_message)."""
    bucket_name, prefix = _gcs_bucket_and_prefix(gs_prefix)
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    try:
        iterator = _gcs_client().list_blobs(bucket_name, prefix=prefix, delimiter="/")
        result = []
        for page in iterator.pages:
            for p in page.prefixes:
                result.append(f"gs://{bucket_name}/{p}")
        return sorted(result), ""
    except Exception as exc:
        return [], _format_gcs_error(exc, gs_prefix)


def _gcs_list_files(gs_prefix: str) -> list[str]:
    bucket_name, prefix = _gcs_bucket_and_prefix(gs_prefix)
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    try:
        iterator = _gcs_client().list_blobs(bucket_name, prefix=prefix, delimiter="/")
        files = []
        for page in iterator.pages:
            for blob in page:
                name = blob.name[len(prefix):]
                if name and "/" not in name:
                    files.append(name)
        return sorted(files)
    except Exception:
        return []


def _read_text(path: str) -> str | None:
    if not path:
        return None
    if path.startswith("gs://"):
        return _gcs_read_text(path)
    try:
        p = Path(path)
        return p.read_text() if p.exists() else None
    except Exception:
        return None


def _read_json(path: str) -> dict | list | None:
    text = _read_text(path)
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _join(base: str, *parts: str) -> str:
    if base.startswith("gs://"):
        return base.rstrip("/") + "/" + "/".join(p.strip("/") for p in parts)
    return str(Path(base).joinpath(*parts))


def _list_dirs_safe(path: str) -> tuple[list[str], str]:
    if not path:
        return [], ""
    if path.startswith("gs://"):
        prefixes, err = _gcs_list_prefixes_safe(path)
        return [p.rstrip("/").split("/")[-1] for p in prefixes], err
    try:
        d = Path(path)
        if not d.exists():
            return [], ""
        return sorted(p.name for p in d.iterdir() if p.is_dir()), ""
    except Exception as exc:
        return [], str(exc)


def _list_dirs(path: str) -> list[str]:
    dirs, _ = _list_dirs_safe(path)
    return dirs


def _list_files(path: str) -> list[str]:
    if not path:
        return []
    if path.startswith("gs://"):
        return _gcs_list_files(path)
    try:
        d = Path(path)
        if not d.exists():
            return []
        return sorted(p.name for p in d.iterdir() if p.is_file())
    except Exception:
        return []


def _iter_sort_key(name: str) -> tuple[int, str]:
    m = re.search(r"(\d+)", name)
    return (int(m.group(1)) if m else 10**9, name)


def _list_iteration_dirs(run_path: str) -> list[str]:
    if not run_path:
        return []
    excluded = {"work", "combined", "tmp", "__pycache__"}
    dirs = [d for d in _list_dirs(run_path) if d not in excluded and not d.startswith(".")]
    iter_dirs = [d for d in dirs if re.match(r"^(iter|iteration|step|epoch)_?\d+", d, re.IGNORECASE)]
    target = iter_dirs if iter_dirs else dirs
    return sorted(target, key=_iter_sort_key)


def get_configured_root(override_path: str = "") -> str:
    if override_path.strip():
        base = override_path.strip().rstrip("/")
    else:
        gcs_base = os.environ.get("HARMONY_GCS_PATH", "").strip().rstrip("/")
        local_base = (
            os.environ.get("HARMONY_LOCAL_PATH", "").strip()
            or os.environ.get("WORK_ROOT", "").strip()
        ).rstrip("/")
        base = local_base or gcs_base or f"gs://{GCS_BUCKET}/{GCS_ROOT_PREFIX}"

    if base.endswith("/mapping") or base.endswith("/audit"):
        base = base.rsplit("/", 1)[0]
    return base


def _resolve_roots(override_path: str = "") -> tuple[str, str]:
    base = get_configured_root(override_path)
    return _join(base, "mapping"), _join(base, "audit")


def _extract_timestamp(folder_name: str) -> str:
    m = re.search(r"(\d{4})[-_]?(\d{2})[-_]?(\d{2})[-_T]?(\d{2})[-_:]?(\d{2})", folder_name)
    if m:
        y, mo, d, h, mi = m.groups()
        return f"{y}-{mo}-{d} {h}:{mi}"
    m_date = re.search(r"(\d{4})[-_]?(\d{2})[-_]?(\d{2})", folder_name)
    if m_date:
        y, mo, d = m_date.groups()
        return f"{y}-{mo}-{d}"
    return ""


def _is_run_folder(name: str) -> bool:
    return ("run_" in name or "output_" in name) and not name.startswith(".")


def list_runs_with_errors(override_path: str = "") -> tuple[list[RunMeta], list[str]]:
    """Discover runs across mapping/ and audit/ (any folder with 'run_' or 'output_')."""
    mapping_root, audit_root = _resolve_roots(override_path)
    errors: list[str] = []

    map_dirs, map_err = _list_dirs_safe(mapping_root)
    if map_err:
        errors.append(map_err)

    aud_dirs, aud_err = _list_dirs_safe(audit_root)
    if aud_err and aud_err not in errors:
        errors.append(aud_err)

    mapping_runs = {d: _join(mapping_root, d) for d in map_dirs if _is_run_folder(d)}
    audit_runs = {d: _join(audit_root, d) for d in aud_dirs if _is_run_folder(d)}

    all_ids = sorted(set(mapping_runs.keys()) | set(audit_runs.keys()))
    runs = [
        RunMeta(
            run_id=rid,
            started_at=_extract_timestamp(rid),
            mapping_path=mapping_runs.get(rid, ""),
            audit_path=audit_runs.get(rid, ""),
        )
        for rid in all_ids
    ]
    return sorted(runs, key=lambda r: (r.started_at, r.run_id), reverse=True), errors


def list_runs(override_path: str = "") -> list[RunMeta]:
    runs, _ = list_runs_with_errors(override_path)
    return runs


def list_mapping_iterations(run: RunMeta) -> list[str]:
    return _list_iteration_dirs(run.mapping_path)


def get_mapping_iter_summary(run: RunMeta, iter_name: str) -> str:
    if not run.mapping_path or not iter_name:
        return ""
    return _read_text(_join(run.mapping_path, iter_name, "summary.md")) or ""


def get_mapping_iter_coverage(run: RunMeta, iter_name: str) -> str:
    if not run.mapping_path or not iter_name:
        return ""
    return _read_text(_join(run.mapping_path, iter_name, "coverage.md")) or ""


def get_mapping_unmapped_columns(run: RunMeta, iter_name: str) -> dict | list | None:
    if not run.mapping_path or not iter_name:
        return None
    return _read_json(_join(run.mapping_path, iter_name, "unmapped_columns.json"))


def list_passed_tables(run: RunMeta, iter_name: str) -> list[str]:
    """Each subdirectory inside mapping/{run}/{iter}/ represents a passed source table."""
    if not run.mapping_path or not iter_name:
        return []
    return _list_dirs(_join(run.mapping_path, iter_name))


def get_table_rubrics(run: RunMeta, iter_name: str, table_name: str) -> str:
    if not run.mapping_path or not iter_name or not table_name:
        return ""
    return _read_text(_join(run.mapping_path, iter_name, table_name, "rubrics.md")) or ""


def get_table_query_sql(run: RunMeta, iter_name: str, table_name: str) -> str:
    if not run.mapping_path or not iter_name or not table_name:
        return ""
    return _read_text(_join(run.mapping_path, iter_name, table_name, "query.sql")) or ""


def get_table_resource_jsonl(
    run: RunMeta, iter_name: str, table_name: str, max_records: int = 200
) -> tuple[list[dict], int]:
    """Read transformed FHIR records from resource.jsonl. Returns (sample_records, total_lines)."""
    if not run.mapping_path or not iter_name or not table_name:
        return [], 0
    raw = _read_text(_join(run.mapping_path, iter_name, table_name, "resource.jsonl"))
    if not raw:
        return [], 0
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    total = len(lines)
    records = []
    for ln in lines[:max_records]:
        try:
            obj = json.loads(ln)
            records.append(obj if isinstance(obj, dict) else {"value": obj})
        except Exception:
            records.append({"raw": ln})
    return records, total


def get_audit_anomalies_dumped(run: RunMeta) -> str:
    if not run.audit_path:
        return ""
    return _read_text(_join(run.audit_path, "anomalies_dumped.md")) or ""


def list_audit_iterations(run: RunMeta) -> list[str]:
    return _list_iteration_dirs(run.audit_path)


def get_audit_iter_artifacts(run: RunMeta, iter_name: str) -> dict[str, str]:
    """Load report.md, fixes.md, and sanity_check.md for an audit iteration."""
    if not run.audit_path or not iter_name:
        return {"report": "", "fixes": "", "sanity_check": ""}
    base = _join(run.audit_path, iter_name)
    return {
        "report": _read_text(_join(base, "report.md")) or "",
        "fixes": _read_text(_join(base, "fixes.md")) or "",
        "sanity_check": _read_text(_join(base, "sanity_check.md")) or "",
    }


def _work_dir(run: RunMeta) -> str:
    return _join(run.mapping_path, "work")


def load_workspace_resources(run: RunMeta) -> list[dict]:
    """Read all work/resources/{name}/status.json + latest_evaluation.json."""
    rroot = _join(_work_dir(run), "resources")
    names = _list_dirs(rroot)
    result = []
    for name in sorted(names):
        rdir = _join(rroot, name)
        status = _read_json(_join(rdir, "status.json")) or {}
        ev = _read_json(_join(rdir, "latest_evaluation.json")) or {}
        result.append({
            "name": name,
            "resource": status.get("resource", name),
            "source_table": status.get("source_table", ""),
            "state": status.get("state", "unknown"),
            "iteration": status.get("iteration") or ev.get("iteration", 0),
            "judge_score": ev.get("judge_score"),
            "dq_passed": ev.get("dq_passed"),
            "reasonableness_passed": ev.get("reasonableness_passed"),
            "coverage_pct": ev.get("coverage_pct"),
            "all_passed": ev.get("all_passed"),
            "blocked_reason": status.get("blocked_reason", ""),
        })
    return result


def load_resource_findings(run: RunMeta, resource_name: str) -> str:
    rdir = _join(_work_dir(run), "resources", resource_name)
    return _read_text(_join(rdir, "findings.md")) or ""


def load_resource_mapping_sql(run: RunMeta, resource_name: str) -> str:
    rdir = _join(_work_dir(run), "resources", resource_name)
    return _read_text(_join(rdir, "mapping.sql")) or ""


def load_resource_draft_sqls(run: RunMeta, resource_name: str) -> list[tuple[str, str]]:
    """Return [(label, sql), ...] in version order: Draft 1, Draft 2, ..., Final."""
    rdir = _join(_work_dir(run), "resources", resource_name)
    files = _list_files(rdir)
    drafts = sorted(
        (f for f in files if re.match(r"mapping_draft_\d+\.sql", f)),
        key=lambda f: int(re.search(r"\d+", f).group()),
    )
    result = [
        (f"Draft {re.search(r'\d+', f).group()}", _read_text(_join(rdir, f)) or "")
        for f in drafts
    ]
    final = _read_text(_join(rdir, "mapping.sql"))
    if final:
        result.append(("Final", final))
    return result


def load_combined_sqls(run: RunMeta) -> dict[str, str]:
    """Read combined/*.sql → {resource_type: sql}."""
    combined_dir = _join(run.mapping_path, "combined")
    result = {}
    for f in _list_files(combined_dir):
        if f.endswith(".sql"):
            sql = _read_text(_join(combined_dir, f))
            if sql:
                result[f[:-4]] = sql
    return result


def load_coverage_snapshots(run: RunMeta) -> dict:
    return _read_json(_join(_work_dir(run), "coverage_snapshots.json")) or {}


def load_iter_summary_json(run: RunMeta, iter_name: str) -> dict:
    return _read_json(_join(run.mapping_path, iter_name, "summary.json")) or {}


def load_iter_resource_eval(run: RunMeta, iter_name: str, resource_name: str) -> dict[str, str]:
    base = _join(run.mapping_path, iter_name, resource_name)
    return {
        "dq": _read_text(_join(base, "dq.md")) or "",
        "judge": _read_text(_join(base, "llm_judge.md")) or "",
        "coverage": _read_text(_join(base, "coverage.md")) or "",
        "reasonableness": _read_text(_join(base, "reasonableness.md")) or "",
        "sql": _read_text(_join(base, "query.sql")) or "",
    }


def load_audit_report(run: RunMeta) -> str:
    return _read_text(_join(run.mapping_path, "audit_report_t1.md")) or ""
