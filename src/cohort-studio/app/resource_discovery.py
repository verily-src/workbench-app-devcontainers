"""Durable snapshot and freshness state for Workbench resource discovery.

`wb resource list` is slow (up to a minute) and fails in ways that have
nothing to do with the resources a user wants: the CLI loses its workspace
context, its login expires, or one broken resource (a BigQuery reference in
an AWS-only workspace) fails the whole listing. db.py fetches; this module
remembers the last good result on disk so a restart shows sources at once,
turns CLI failures into short actionable messages, and decides when the
next background attempt may run.

The snapshot holds resource ids, kinds, labels, regions and S3 URIs only:
every field is copied through an allowlist, so connection strings and
passwords (which `wb resource resolve --include-password` returns, never
`wb resource list`) cannot reach the file even if the CLI adds fields.
"""

import json
import logging
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_VERSION = 1

# Fields db.py's consumers read from a `wb resource list` entry.
_RESOURCE_FIELDS = ("id", "uuid", "resourceType", "databaseName", "region",
                    "bucketName", "prefix", "projectId", "datasetId",
                    "dataTableId", "tableId")
_MAX_STR = 1024

# `wb resource list --type=...` values, per Studio source kind. Used when the
# full listing fails so one broken kind does not hide the others.
KIND_TYPES = {
    "aurora": ("AWS_AURORA_DATABASE", "AWS_AURORA_DATABASE_REFERENCE"),
    "s3": ("AWS_S3_STORAGE_FOLDER", "AWS_S3_EXTERNAL_BUCKET",
           "AWS_S3_EXTERNAL_BUCKET_REFERENCE"),
    "bq": ("BQ_DATASET", "BQ_TABLE"),
}
KIND_LABELS = {"aurora": "Aurora", "s3": "S3", "bq": "BigQuery"}

# Background retry after a failed refresh: 10 s, 20 s, 40 s ... capped.
RETRY_BASE_S = 10.0
RETRY_MAX_S = 300.0
# After a good refresh, list again at most this often (on access).
REFRESH_INTERVAL_S = 300.0
# A good-but-empty listing (CLI not logged in yet) is retried sooner.
EMPTY_REFRESH_S = 20.0
# Manual "Retry" clicks are debounced, never queued.
MANUAL_DEBOUNCE_S = 5.0

_WORKSPACE_ENV = ("STUDIO_WORKSPACE_ID", "WORKBENCH_WORKSPACE_ID", "WORKSPACE_ID")


def workspace_id() -> str:
    for name in _WORKSPACE_ENV:
        value = os.environ.get(name, "").strip()
        if value and all(c.isalnum() or c in "-_." for c in value) and len(value) <= 128:
            return value
    return ""


def cache_path() -> Path:
    explicit = os.environ.get("STUDIO_DISCOVERY_CACHE_PATH", "").strip()
    if explicit:
        return Path(explicit)
    config_file = Path(os.environ.get(
        "STUDIO_CONFIG", str(Path(__file__).parent / "studio_config.json")))
    return config_file.with_name(".studio-discovery-cache.json")


# ----- errors -------------------------------------------------------------

class DiscoveryError(Exception):
    """A listing failed. `message` is safe to show: it never echoes CLI output."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class PartialDiscovery(Exception):
    """Some kinds listed, others failed (`failed` maps kind -> DiscoveryError)."""

    def __init__(self, resources: list[dict], failed: dict[str, DiscoveryError]):
        super().__init__(", ".join(sorted(failed)))
        self.resources = resources
        self.failed = failed


def classify(exc: BaseException) -> DiscoveryError:
    """Map a CLI failure to a short, actionable, secret-free message."""
    if isinstance(exc, DiscoveryError):
        return exc
    if isinstance(exc, FileNotFoundError):
        return DiscoveryError("cli_missing", "The Workbench CLI (wb) is not installed in this app.")
    if isinstance(exc, subprocess.TimeoutExpired):
        return DiscoveryError("timeout", "The Workbench CLI timed out listing resources; "
                                         "retrying in the background.")
    if isinstance(exc, (json.JSONDecodeError, ValueError, TypeError)):
        return DiscoveryError("parse", "The Workbench CLI returned a resource list that "
                                       "could not be read; retrying in the background.")
    if isinstance(exc, subprocess.CalledProcessError):
        text = f"{exc.stderr or ''}\n{exc.stdout or ''}".lower()
        if ("no workspace" in text or "workspace not set" in text
                or "workspace is not set" in text or "set a workspace" in text):
            wid = workspace_id() or "<workspace>"
            return DiscoveryError(
                "no_workspace", "The Workbench CLI has no workspace set on the app VM; "
                                f"run `wb workspace set --id={wid}`.")
        if any(token in text for token in (
                "not logged in", "log in", "login", "unauthenticated", "unauthorized",
                "refresh token", "invalid_grant")):
            return DiscoveryError(
                "auth", "The Workbench CLI login on the app VM has expired; "
                        "run `wb auth login` there, then retry.")
        return DiscoveryError("cli_error", f"`wb resource list` failed (exit {exc.returncode}); "
                                           "retrying in the background.")
    return DiscoveryError("error", "Resource discovery failed; retrying in the background.")


# Global failures: listing again by type would fail the same way.
GLOBAL_CODES = frozenset({"cli_missing", "timeout", "no_workspace", "auth"})


# ----- kinds and sanitizing -----------------------------------------------

def kind_of(resource: dict) -> str | None:
    rtype = str(resource.get("resourceType") or "")
    if "AURORA_DATABASE" in rtype:
        return "aurora"
    if "S3" in rtype:
        return "s3"
    if rtype in ("BQ_DATASET", "BQ_DATA_TABLE", "BQ_TABLE"):
        return "bq"
    return None


def _clean(entry: dict, depth: int = 0) -> dict:
    out = {}
    for key in _RESOURCE_FIELDS:
        value = entry.get(key)
        if isinstance(value, str) and len(value) <= _MAX_STR:
            out[key] = value
    ref = entry.get("referencedResource")
    if depth == 0 and isinstance(ref, dict):
        out["referencedResource"] = _clean(ref, 1)
    return out


def sanitize(resources: list) -> list[dict]:
    """Allowlisted copy of the entries Studio uses (raises on a non-list)."""
    if not isinstance(resources, list):
        raise ValueError("resource list is not a JSON array")
    return [_clean(r) for r in resources
            if isinstance(r, dict) and isinstance(r.get("id"), str) and kind_of(r)]


# ----- the snapshot file --------------------------------------------------

def save(resources: list[dict], s3_uris: dict[str, str]) -> None:
    clean = sanitize(resources)
    ids = {r["id"] for r in clean}
    uris = {k: v for k, v in s3_uris.items()
            if k in ids and isinstance(v, str) and v.startswith("s3://") and len(v) <= _MAX_STR}
    payload = {"version": CACHE_VERSION, "updated_at": time.time(),
               "workspace_id": workspace_id(), "resources": clean, "s3_uris": uris}
    path = cache_path()
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(payload, handle)
        os.replace(tmp, path)
    except OSError as exc:
        logger.warning("Could not save the discovery snapshot to %s: %s", path, exc)
        try:
            tmp.unlink()
        except OSError:
            pass


def load() -> dict | None:
    """The saved snapshot, or None when missing, unreadable or from another workspace."""
    path = cache_path()
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        logger.warning("Ignoring unreadable discovery snapshot %s: %s", path, exc)
        return None
    try:
        if raw.get("version") != CACHE_VERSION:
            return None
        current = workspace_id()
        if current and raw.get("workspace_id") and raw["workspace_id"] != current:
            return None
        resources = sanitize(raw.get("resources"))
        updated = float(raw.get("updated_at"))
        uris = raw.get("s3_uris") or {}
        uris = {k: v for k, v in uris.items() if isinstance(k, str) and isinstance(v, str)
                and v.startswith("s3://")} if isinstance(uris, dict) else {}
    except (AttributeError, TypeError, ValueError):
        logger.warning("Ignoring malformed discovery snapshot %s", path)
        return None
    if not resources:
        return None
    return {"resources": resources, "updated_at": updated, "s3_uris": uris}


# ----- freshness state ----------------------------------------------------

def retry_delay(failures: int) -> float:
    """Seconds before background attempt number `failures` + 1 (capped)."""
    if failures <= 0:
        return 0.0
    return min(RETRY_MAX_S, RETRY_BASE_S * (2 ** min(failures - 1, 16)))


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.in_flight = False
        self.attempted = False
        self.ok = False
        self.from_cache = False
        self.updated_at: float | None = None
        self.error: DiscoveryError | None = None
        self.failed_kinds: dict[str, str] = {}
        self.failures = 0
        self.next_allowed = 0.0          # monotonic
        self.retry_at: float | None = None  # wall clock, for display
        self.last_manual = -MANUAL_DEBOUNCE_S
        self.timer_pending = False

    def snapshot(self, have_data: bool) -> dict:
        with self.lock:
            if self.in_flight or not self.attempted:
                status = "refreshing"
            elif self.error and self.error.code == "cli_missing":
                status = "unavailable"
            elif self.ok and not self.failed_kinds and not self.error:
                status = "fresh"
            elif have_data:
                status = "stale"
            else:
                status = "failed"
            out = {"status": status, "from_cache": self.from_cache,
                   "updated_at": _iso(self.updated_at)}
            if self.error:
                out["error"] = self.error.message
                out["error_code"] = self.error.code
            if self.failed_kinds:
                out["failed_kinds"] = sorted(self.failed_kinds)
                if not self.error:
                    out["error"] = "; ".join(self.failed_kinds[k] for k in sorted(self.failed_kinds))
                    out["error_code"] = "partial"
            if self.retry_at and status != "fresh":
                out["retry_at"] = _iso(self.retry_at)
            return out


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


def kind_failure_message(kind: str, err: DiscoveryError) -> str:
    label = KIND_LABELS.get(kind, kind)
    reason = "unreadable CLI output" if err.code == "parse" else "the CLI listing failed"
    return f"{label} resources could not be listed ({reason}); showing the other sources."
