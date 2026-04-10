"""
Google Cloud Storage utilities: bucket/folder listing and file upload.
"""

from __future__ import annotations

import json
from typing import Optional


def discover_gcs_buckets(project_id: str) -> list[str]:
    """List GCS buckets accessible in the given project."""
    from google.cloud import storage
    try:
        client = storage.Client(project=project_id)
        return sorted([b.name for b in client.list_buckets()])
    except Exception as e:
        print(f"Could not list buckets for {project_id}: {e}")
        return []


def discover_gcs_folders(bucket_name: str, prefix: str = "") -> list[str]:
    """List top-level 'folders' (common prefixes) in a GCS bucket."""
    from google.cloud import storage
    try:
        client = storage.Client()
        bucket = client.bucket(bucket_name.replace("gs://", ""))
        iterator = client.list_blobs(
            bucket,
            prefix=prefix if prefix else None,
            delimiter="/",
        )
        _ = list(iterator)
        return sorted(iterator.prefixes)
    except Exception as e:
        print(f"Could not list folders in {bucket_name}/{prefix}: {e}")
        return []


def upload_json_to_gcs(
    bucket_name: str,
    destination_path: str,
    data: dict,
    project_id: Optional[str] = None,
) -> str:
    """
    Upload a JSON dict to GCS.

    Returns the gs:// URI of the uploaded file.
    """
    from google.cloud import storage

    client = storage.Client(project=project_id) if project_id else storage.Client()
    bucket = client.bucket(bucket_name.replace("gs://", ""))
    blob = bucket.blob(destination_path)
    blob.upload_from_string(
        json.dumps(data, indent=2),
        content_type="application/json",
    )
    return f"gs://{bucket.name}/{destination_path}"


def upload_multiple_jsons(
    bucket_name: str,
    base_path: str,
    files: dict[str, dict],
    project_id: Optional[str] = None,
) -> list[str]:
    """
    Upload multiple JSON files to a GCS path.

    Args:
        bucket_name: Target bucket.
        base_path: Prefix path (e.g. "profiling/2026-04-10/").
        files: Mapping of filename -> JSON dict.
        project_id: Optional billing project.

    Returns:
        List of gs:// URIs for uploaded files.
    """
    uris = []
    for filename, data in files.items():
        dest = f"{base_path.rstrip('/')}/{filename}"
        uri = upload_json_to_gcs(bucket_name, dest, data, project_id)
        uris.append(uri)
    return uris
