"""Where select_highest_risk may write: a file in a controlled bucket resource of the workspace.
Standard library only.

A controlled bucket is one the workspace owns (``stewardshipType: CONTROLLED`` in ``wb resource
list``); a referenced bucket belongs to someone else and is never written. The copy runs
``gcloud storage cp`` as the server's user, which is why the check comes first.
"""
from __future__ import annotations

import json
import subprocess


def controlled_buckets(resources: list[dict]) -> dict[str, str]:
    """``{bucket name: resource id}`` of the workspace's controlled GCS bucket resources, from the
    JSON of ``wb resource list --format=json``."""
    return {r["bucketName"]: r.get("id", "") for r in resources
            if isinstance(r, dict) and r.get("resourceType") == "GCS_BUCKET"
            and r.get("stewardshipType") == "CONTROLLED" and r.get("bucketName")}


def check_destination(destination: str, resources: list[dict]) -> tuple[str, str]:
    """``(bucket, object)`` of a ``gs://bucket/path/file`` destination in a controlled bucket
    resource of the workspace. Refuses anything else, naming the controlled buckets."""
    controlled = controlled_buckets(resources)
    listing = ", ".join(f"gs://{b}" for b in sorted(controlled)) or "none"
    if not isinstance(destination, str) or not destination.startswith("gs://"):
        raise ValueError(f"destination is a gs:// URL of a file in a controlled bucket of the workspace "
                         f"(controlled buckets: {listing})")
    bucket, _, obj = destination[len("gs://"):].partition("/")
    if not obj or obj.endswith("/") or ".." in obj.split("/"):
        raise ValueError(f"destination must name a file in the bucket, such as gs://{bucket or 'bucket'}/folder/risk.csv")
    if bucket not in controlled:
        raise ValueError(f"{destination} is not in a controlled bucket of this workspace; the server writes only "
                         f"to those (controlled buckets: {listing})")
    return bucket, obj


def workspace_resources() -> list[dict]:
    """The workspace's resources, from ``wb``. An empty answer is a failure, not an empty workspace."""
    done = subprocess.run(["wb", "resource", "list", "--format=json"], capture_output=True, text=True, timeout=120)
    if done.returncode != 0 or not done.stdout.strip():
        raise ValueError(f"cannot list the workspace's resources with wb: {(done.stderr or 'no output').strip()[:300]}")
    try:
        data = json.loads(done.stdout)
    except json.JSONDecodeError as err:
        raise ValueError(f"wb resource list did not return JSON: {err}") from err
    if not isinstance(data, list):
        raise ValueError("wb resource list did not return a list")
    return data


def copy_to_bucket(path: str, destination: str) -> None:
    """Copies the local file ``path`` (which the caller keeps owner-only) to ``destination`` with gcloud."""
    done = subprocess.run(["gcloud", "storage", "cp", path, destination], capture_output=True, text=True, timeout=300)
    if done.returncode != 0:
        raise ValueError(f"gcloud storage cp failed: {(done.stderr or 'no output').strip()[:300]}")
