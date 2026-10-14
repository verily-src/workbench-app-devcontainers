"""GCS storage: paths, read, write for profiling outputs."""

from __future__ import annotations

import json
from typing import Any, Optional

from verily_profiler.models import SemanticTableProfile, TechTableProfile, TerminologyRegistry


# ── Path conventions ──────────────────────────────────────────────────────────

TECH_FILENAME = "tech_profile.json"
SEM_FILENAME = "semantic_profile.json"
REGISTRY_FILENAME = "_terminology_registry.json"
CATALOG_CONTEXT_FILENAME = "_catalog_context.md"


def profile_prefix(project_id: str, dataset_id: str, table_id: str) -> str:
    """Prefix ending with / for one table's profiling folder."""
    return f"profiling/{project_id}/{dataset_id}/{table_id}/"


def tech_object_path(project_id: str, dataset_id: str, table_id: str) -> str:
    return f"{profile_prefix(project_id, dataset_id, table_id)}{TECH_FILENAME}"


def sem_object_path(project_id: str, dataset_id: str, table_id: str) -> str:
    return f"{profile_prefix(project_id, dataset_id, table_id)}{SEM_FILENAME}"


def parse_fq_table(fq: str) -> tuple[str, str, str]:
    parts = fq.split(".", 2)
    if len(parts) != 3:
        raise ValueError(f"Invalid fully-qualified table: {fq}")
    return parts[0], parts[1], parts[2]


# ── GCS client helper ─────────────────────────────────────────────────────────

def _client(project_id: Optional[str] = None):
    from google.cloud import storage
    return storage.Client(project=project_id) if project_id else storage.Client()


# ── Upload ────────────────────────────────────────────────────────────────────

def upload_json(
    bucket_name: str,
    object_path: str,
    data: dict[str, Any],
    project_id: Optional[str] = None,
) -> str:
    client = _client(project_id)
    bucket = client.bucket(bucket_name.replace("gs://", ""))
    blob = bucket.blob(object_path)
    blob.upload_from_string(
        json.dumps(data, indent=2),
        content_type="application/json",
    )
    return f"gs://{bucket.name}/{object_path}"


def write_tech_profile(
    bucket_name: str,
    fq_table: str,
    profile: TechTableProfile | dict[str, Any],
    project_id: Optional[str] = None,
) -> str:
    """Write a technical profile to GCS. Accepts dataclass or dict."""
    p, d, t = parse_fq_table(fq_table)
    path = tech_object_path(p, d, t)
    data = profile.to_json_dict() if isinstance(profile, TechTableProfile) else profile
    return upload_json(bucket_name, path, data, project_id)


def write_sem_profile(
    bucket_name: str,
    fq_table: str,
    profile: SemanticTableProfile | dict[str, Any],
    project_id: Optional[str] = None,
) -> str:
    """Write a semantic profile to GCS. Accepts dataclass or dict."""
    p, d, t = parse_fq_table(fq_table)
    path = sem_object_path(p, d, t)
    data = profile.to_json_dict() if isinstance(profile, SemanticTableProfile) else profile
    return upload_json(bucket_name, path, data, project_id)


# ── Read ──────────────────────────────────────────────────────────────────────

def blob_exists(bucket_name: str, object_path: str, project_id: Optional[str] = None) -> bool:
    client = _client(project_id)
    b = client.bucket(bucket_name.replace("gs://", ""))
    return b.blob(object_path).exists(client)


def read_json_if_exists(
    bucket_name: str,
    object_path: str,
    project_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    client = _client(project_id)
    b = client.bucket(bucket_name.replace("gs://", ""))
    blob = b.blob(object_path)
    if not blob.exists(client):
        return None
    return json.loads(blob.download_as_text())


def read_tech_profile(
    bucket_name: str,
    fq_table: str,
    project_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Read a technical profile from GCS. Returns dict or None."""
    p, d, t = parse_fq_table(fq_table)
    return read_json_if_exists(bucket_name, tech_object_path(p, d, t), project_id)


def read_sem_profile(
    bucket_name: str,
    fq_table: str,
    project_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Read a semantic profile from GCS. Returns dict or None."""
    p, d, t = parse_fq_table(fq_table)
    return read_json_if_exists(bucket_name, sem_object_path(p, d, t), project_id)


# ── Scan ──────────────────────────────────────────────────────────────────────

def scan_profile_availability(
    bucket_name: str,
    data_project_id: str,
    billing_project_id: Optional[str] = None,
) -> dict[str, dict[str, Any]]:
    """
    List all profiling/* under data_project and return
    fq_table -> {technical, semantic, business_name?, table_definition?}.
    """
    client = _client(billing_project_id)
    bucket = client.bucket(bucket_name.replace("gs://", ""))
    prefix = f"profiling/{data_project_id}/"
    out: dict[str, dict[str, Any]] = {}
    sem_blobs: list[tuple[str, Any]] = []
    for blob in client.list_blobs(bucket, prefix=prefix):
        name = blob.name
        if not name.startswith(prefix):
            continue
        rel = name[len(prefix):].strip("/")
        parts = rel.split("/")
        if len(parts) < 3:
            continue
        ds, tbl, fname = parts[0], parts[1], parts[2]
        fq = f"{data_project_id}.{ds}.{tbl}"
        entry = out.setdefault(fq, {"technical": False, "semantic": False})
        if fname == TECH_FILENAME:
            entry["technical"] = True
        elif fname == SEM_FILENAME:
            entry["semantic"] = True
            sem_blobs.append((fq, blob))

    for fq, blob in sem_blobs:
        try:
            data = json.loads(blob.download_as_text())
            out[fq]["business_name"] = data.get("business_name", "")
            out[fq]["table_definition"] = data.get("table_definition", "")
        except Exception:
            pass

    return out


# ── Terminology Registry ─────────────────────────────────────────────────────

def registry_object_path(data_project_id: str) -> str:
    return f"profiling/{data_project_id}/{REGISTRY_FILENAME}"


def read_registry(
    bucket_name: str,
    data_project_id: str,
    billing_project_id: Optional[str] = None,
) -> TerminologyRegistry:
    """Load the terminology registry from GCS, or return empty if not found."""
    path = registry_object_path(data_project_id)
    data = read_json_if_exists(bucket_name, path, billing_project_id)
    if data:
        return TerminologyRegistry.from_dict(data)
    return TerminologyRegistry()


def write_registry(
    bucket_name: str,
    data_project_id: str,
    registry: TerminologyRegistry,
    billing_project_id: Optional[str] = None,
) -> str:
    """Save the terminology registry to GCS."""
    path = registry_object_path(data_project_id)
    return upload_json(bucket_name, path, registry.to_json_dict(), billing_project_id)


# ── Catalog context (.md) ────────────────────────────────────────────────────

def catalog_context_object_path(data_project_id: str) -> str:
    return f"profiling/{data_project_id}/{CATALOG_CONTEXT_FILENAME}"


def read_catalog_context(
    bucket_name: str,
    data_project_id: str,
    billing_project_id: Optional[str] = None,
) -> Optional[str]:
    """Read the pre-generated catalog context markdown from GCS."""
    client = _client(billing_project_id)
    b = client.bucket(bucket_name.replace("gs://", ""))
    blob = b.blob(catalog_context_object_path(data_project_id))
    if not blob.exists(client):
        return None
    return blob.download_as_text()


def write_catalog_context(
    bucket_name: str,
    data_project_id: str,
    content: str,
    billing_project_id: Optional[str] = None,
) -> str:
    """Write catalog context markdown to GCS."""
    client = _client(billing_project_id)
    b = client.bucket(bucket_name.replace("gs://", ""))
    path = catalog_context_object_path(data_project_id)
    blob = b.blob(path)
    blob.upload_from_string(content, content_type="text/markdown")
    return f"gs://{b.name}/{path}"


def regenerate_catalog_context(
    bucket_name: str,
    data_project_id: str,
    billing_project_id: Optional[str] = None,
) -> str:
    """Load all profiles and regenerate the catalog context .md file."""
    from verily_profiler.catalog_context import generate_catalog_context_md

    avail = scan_profile_availability(bucket_name, data_project_id, billing_project_id=billing_project_id)
    profiles: dict[str, dict] = {}

    for fq, info in avail.items():
        entry: dict = {"tech": None, "sem": None}
        if info.get("technical"):
            entry["tech"] = read_tech_profile(bucket_name, fq, project_id=billing_project_id)
        if info.get("semantic"):
            entry["sem"] = read_sem_profile(bucket_name, fq, project_id=billing_project_id)
        if entry["tech"] or entry["sem"]:
            profiles[fq] = entry

    md = generate_catalog_context_md(data_project_id, profiles)
    gcs_path = write_catalog_context(bucket_name, data_project_id, md, billing_project_id)
    print(f"  Catalog context regenerated: {len(profiles)} tables, {len(md)} chars -> {gcs_path}")
    return gcs_path
