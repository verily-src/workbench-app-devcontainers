"""Read-only Workbench app listing for the cohort agent."""

import json
import re
import subprocess
from urllib.parse import urlsplit

APP_LIST_TIMEOUT = 20
MAX_STDOUT_CHARS = 1_000_000
MAX_APPS = 50


def _value(app: dict, *keys):
    for key in keys:
        value = app.get(key)
        if value is not None:
            return value
    return None


def _public_app(app: dict) -> dict:
    """Project only operational fields; never return arbitrary CLI JSON."""
    app_id = _value(app, "id", "appId", "resourceId")
    if not app_id:
        proxy_url = _value(app, "proxyUrl", "proxyURL")
        path = urlsplit(proxy_url).path if isinstance(proxy_url, str) else ""
        match = re.search(r"/app/([0-9a-fA-F-]{36})(?:/|$)", path)
        app_id = match.group(1) if match else None
    return {
        "id": app_id,
        "name": _value(app, "displayName", "name", "appName"),
        "status": _value(app, "status", "state"),
        "config": _value(app, "appConfigName", "configName", "config"),
        "owner": _value(app, "owner", "ownerEmail", "createdBy"),
        "workspace_id": _value(app, "workspaceId", "workspace_id"),
    }


def list_apps(limit: int = 20) -> dict:
    """List current workspace apps using a fixed, read-only wb command."""
    limit = max(1, min(int(limit), MAX_APPS))
    try:
        result = subprocess.run(
            ["wb", "app", "list", "--format", "JSON"],
            capture_output=True, text=True, check=True,
            timeout=APP_LIST_TIMEOUT)
        if len(result.stdout) > MAX_STDOUT_CHARS:
            return {"available": False, "apps": [],
                    "error": "Workbench app list output exceeded the size limit."}
        raw = json.loads(result.stdout or "[]")
        if not isinstance(raw, list):
            raise ValueError("Expected a JSON list.")
        return {"available": True,
                "apps": [_public_app(a) for a in raw[:limit]
                         if isinstance(a, dict)],
                "truncated": len(raw) > limit}
    except Exception:
        # Do not return CLI stdout/stderr: errors may include credentials or
        # other workspace details. The operation is read-only and retryable.
        return {"available": False, "apps": [],
                "error": "Workbench app listing is unavailable."}
