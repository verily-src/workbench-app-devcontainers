"""
On-demand technical / semantic profiling with GCS persistence and in-memory job tracking.
"""

from __future__ import annotations

import asyncio
import uuid
from threading import Lock
from typing import Any, Literal, Optional

from verily_profiler import (
    discover_tables,
    profile_technical,
    profile_semantic,
    write_tech_profile,
    write_sem_profile,
    read_tech_profile,
    read_sem_profile,
    read_registry,
    write_registry,
    scan_profile_availability,
    reconcile,
    apply_reconciliation,
    BQTableInfo,
)
from verily_profiler.storage import parse_fq_table, tech_object_path, sem_object_path, read_json_if_exists, regenerate_catalog_context, read_catalog_context
from verily_profiler.llm import detect_available_model

JobKind = Literal["technical", "semantic"]


class ProfilingJobState:
    """Tracks running profiling jobs per (fq_table, kind)."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._running: dict[tuple[str, JobKind], str] = {}

    def try_start(self, fq: str, kind: JobKind) -> tuple[str, bool]:
        """Returns (job_id, started). If already running, returns existing job_id and False."""
        with self._lock:
            key = (fq, kind)
            if key in self._running:
                jid = self._running[key]
                return jid, False
            jid = str(uuid.uuid4())
            self._running[key] = jid
            self._jobs[jid] = {"fq_table": fq, "kind": kind, "status": "running", "error": None}
            return jid, True

    def finish(self, fq: str, kind: JobKind, job_id: str, error: Optional[str] = None) -> None:
        with self._lock:
            key = (fq, kind)
            if self._running.get(key) != job_id:
                return
            del self._running[key]
            if job_id in self._jobs:
                self._jobs[job_id]["status"] = "failed" if error else "available"
                self._jobs[job_id]["error"] = error

    def get_job(self, job_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            return self._jobs.get(job_id)

    def is_running(self, fq: str, kind: JobKind) -> bool:
        with self._lock:
            return (fq, kind) in self._running

    def running_flags(self, fq: str) -> dict[str, bool]:
        """Whether technical/semantic jobs are in-flight for this table."""
        with self._lock:
            return {
                "technical": (fq, "technical") in self._running,
                "semantic": (fq, "semantic") in self._running,
            }


job_state = ProfilingJobState()


def load_table_info(
    fq_table: str,
    billing_project: str,
    data_project: str,
) -> Optional[BQTableInfo]:
    """Load BQTableInfo for fq_table by listing its dataset."""
    try:
        p, d, t = parse_fq_table(fq_table)
    except ValueError:
        return None
    if p != data_project:
        return None
    tables = discover_tables(p, d, billing_project=billing_project)
    for ti in tables:
        if ti.table_id == t:
            return ti
    return None


async def run_technical_profile_async(
    *,
    fq_table: str,
    bucket: str,
    billing_project: str,
    data_project: str,
    job_id: str,
) -> None:
    def _work() -> None:
        try:
            info = load_table_info(fq_table, billing_project, data_project)
            if not info:
                raise RuntimeError(f"Table not found: {fq_table}")
            prof = profile_technical(info, billing_project=billing_project)
            write_tech_profile(bucket, fq_table, prof, project_id=billing_project)
        except Exception as e:
            job_state.finish(fq_table, "technical", job_id, str(e))
            raise
        job_state.finish(fq_table, "technical", job_id, None)

    await asyncio.to_thread(_work)


def _dict_to_tech_profile(d: dict[str, Any]) -> Any:
    from verily_profiler.models import TechColumnProfile, TechTableProfile, ValidationResult

    cols: list[TechColumnProfile] = []
    for c in d.get("columns", []):
        cp = TechColumnProfile(
            column_name=str(c.get("name", "")),
            data_type=str(c.get("data_type", "")),
            nullable=bool(c.get("nullable", True)),
            null_count=int(c.get("null_count", 0)),
            null_percent=float(c.get("null_percent", 0.0)),
            distinct_count=int(c.get("distinct_count", 0)),
            top_values=list(c.get("top_values") or []),
            value_counts=c.get("value_counts"),
        )
        ss = c.get("string_stats") or {}
        if ss:
            cp.min_length = ss.get("min_length")
            cp.max_length = ss.get("max_length")
            cp.avg_length = ss.get("avg_length")
        ns = c.get("numeric_stats") or {}
        if ns:
            cp.min_value = ns.get("min")
            cp.max_value = ns.get("max")
            cp.median = ns.get("median")
            cp.stddev = ns.get("stddev")
        if c.get("pattern"):
            cp.detected_pattern = str(c["pattern"])
        if c.get("anomalies"):
            cp.anomalies = list(c["anomalies"])
        cols.append(cp)
    vr = d.get("validation") or {}
    return TechTableProfile(
        table_name=str(d.get("table", "")),
        row_count=int(d.get("row_count", 0)),
        size_bytes=d.get("size_bytes"),
        profiled_at=str(d.get("profiled_at", "")),
        columns=cols,
        validation=ValidationResult(
            status=str(vr.get("status", "pass")),
            anomalies=list(vr.get("anomalies") or []),
            warnings=list(vr.get("warnings") or []),
        ),
    )


async def run_semantic_profile_async(
    *,
    fq_table: str,
    bucket: str,
    billing_project: str,
    data_project: str,
    model_name: Optional[str],
    job_id: str,
) -> None:
    def _work() -> None:
        try:
            p, d, t = parse_fq_table(fq_table)
            tech_path = tech_object_path(p, d, t)
            tech_json = read_json_if_exists(bucket, tech_path, billing_project)
            if not tech_json:
                raise RuntimeError("Technical profile missing; run technical profiling first.")
            tech_prof = _dict_to_tech_profile(tech_json)
            model = model_name or detect_available_model(billing_project)
            registry = None
            try:
                registry = read_registry(bucket, data_project, billing_project_id=billing_project)
            except Exception:
                pass
            neighbor_ctx = None
            try:
                neighbor_ctx = read_catalog_context(bucket, data_project, billing_project_id=billing_project)
            except Exception:
                pass
            sem, new_entries = profile_semantic(
                tech_prof, model=model, project_id=billing_project, registry=registry,
                neighbor_context=neighbor_ctx,
            )
            write_sem_profile(bucket, fq_table, sem, project_id=billing_project)

            if new_entries and registry is not None:
                for entry in new_entries:
                    registry.upsert(entry)
                try:
                    write_registry(bucket, data_project, registry, billing_project_id=billing_project)
                except Exception as re:
                    print(f"  Registry update failed (non-blocking): {re}")

            if registry is not None and len(registry.entries) >= 2:
                try:
                    _auto_reconcile(registry, model, billing_project, data_project, bucket)
                except Exception as re:
                    print(f"  Auto-reconciliation failed (non-blocking): {re}")

            try:
                regenerate_catalog_context(bucket, data_project, billing_project_id=billing_project)
                try:
                    from chat_handler import invalidate_context_cache
                    invalidate_context_cache(data_project, bucket)
                except Exception:
                    pass
            except Exception as ce:
                print(f"  Catalog context regen failed (non-blocking): {ce}")

        except Exception as e:
            job_state.finish(fq_table, "semantic", job_id, str(e))
            raise
        job_state.finish(fq_table, "semantic", job_id, None)

    await asyncio.to_thread(_work)


def _auto_reconcile(
    registry: "TerminologyRegistry",
    model: str,
    billing_project: str,
    data_project: str,
    bucket: str,
) -> None:
    """Run reconciliation after semantic profiling and apply if duplicates found."""
    print(f"  Auto-reconciling registry ({len(registry.entries)} entries)...")
    groups = reconcile(registry, model=model, project_id=billing_project)
    if not groups:
        print("  No duplicates found — registry is clean.")
        return

    print(f"  Found {len(groups)} reconciliation groups, applying...")
    avail = scan_profile_availability(bucket, data_project, billing_project_id=billing_project)
    sem_profiles: dict[str, dict] = {}
    for fq, info in avail.items():
        if info.get("semantic"):
            s = read_sem_profile(bucket, fq, project_id=billing_project)
            if s:
                sem_profiles[fq] = s

    updated_reg, updated_profs = apply_reconciliation(registry, groups, sem_profiles)
    write_registry(bucket, data_project, updated_reg, billing_project_id=billing_project)

    for fq, prof in updated_profs.items():
        write_sem_profile(bucket, fq, prof, project_id=billing_project)

    print(f"  Reconciliation complete: unified {len(groups)} groups, updated {len(updated_profs)} profiles.")


def profile_status_from_gcs_and_jobs(
    fq_table: str,
    bucket: str,
    billing_project: str,
) -> dict[str, Any]:
    p, d, t = parse_fq_table(fq_table)
    tech_path = tech_object_path(p, d, t)
    sem_path = sem_object_path(p, d, t)
    tech_gcs = read_json_if_exists(bucket, tech_path, billing_project) is not None
    sem_gcs = read_json_if_exists(bucket, sem_path, billing_project) is not None

    if tech_gcs:
        tech = "available"
    elif job_state.is_running(fq_table, "technical"):
        tech = "running"
    else:
        tech = "none"

    if sem_gcs:
        sem = "available"
    elif job_state.is_running(fq_table, "semantic"):
        sem = "running"
    else:
        sem = "none"

    return {"technical": tech, "semantic": sem}
