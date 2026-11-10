#!/usr/bin/env python3
"""Lists the workspace's BigQuery datasets and Cloud Storage buckets, and whether the workspace
owns each (CONTROLLED) or references it (REFERENCED, as a data collection's resources are).

usage: workspace-data.py [output.json]      (JSON to the file, or to stdout)

The output is written even when Workbench cannot be read or answers unexpectedly: "unavailable"
is then true, with the reason, and render-policy.py renders no data rules.

The workspace and the Workspace Manager URL come from the Workbench CLI's context file, which
the user can edit. The URL is accepted only on Workbench's host (WORKBENCH_HOST), so the list
is always Workbench's own answer and the user's token goes nowhere else.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

PAGE = 100
# Where the Workspace Manager lives.
WORKBENCH_HOST = "workbench.verily.com"


class Unavailable(Exception):
    """Workbench could not be read; the caller writes a fail-closed result."""


def workbench_url(base):
    """The Workspace Manager URL, if it is https on Workbench's host; Unavailable otherwise."""
    parts = urllib.parse.urlsplit(str(base))
    if parts.scheme != "https" or parts.hostname != WORKBENCH_HOST or parts.port:
        raise Unavailable(f"the Workspace Manager URL {base!r} is not on {WORKBENCH_HOST}")
    return str(base).rstrip("/")


class Workbench:
    """The Workspace Manager API, as the user the CLI is logged in as."""

    def __init__(self):
        context = {}
        try:
            with open(os.path.expanduser(os.environ.get("WB_CONTEXT", "~/.workbench/context.json")),
                      encoding="utf-8") as handle:
                context = json.load(handle)
        except (OSError, json.JSONDecodeError):
            pass
        workspace = context.get("workspace") or {}
        base = (context.get("server") or {}).get("workspaceManagerUri")
        if not (workspace.get("uuid") and workspace.get("userFacingId") and base):
            raise Unavailable("the Workbench CLI's context file names no workspace; log in with wb in the app")
        self.workspace_uuid = workspace["uuid"]
        self.workspace_id = workspace["userFacingId"]
        self.project = workspace.get("googleProjectId")
        self.base = workbench_url(base)
        self.token = self._google_token()

    @staticmethod
    def _google_token():
        """A Google access token for Workspace Manager: the app's Application Default
        Credentials (wb logs in with them), else the VM's metadata server."""
        path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or \
            os.path.expanduser("~/.config/gcloud/application_default_credentials.json")
        try:
            with open(path, encoding="utf-8") as handle:
                adc = json.load(handle)
        except (OSError, json.JSONDecodeError):
            adc = {}
        if adc.get("type") == "authorized_user":
            body = urllib.parse.urlencode({
                "grant_type": "refresh_token", "client_id": adc["client_id"],
                "client_secret": adc["client_secret"], "refresh_token": adc["refresh_token"],
            }).encode()
            try:
                with urllib.request.urlopen(urllib.request.Request(
                        adc.get("token_uri") or "https://oauth2.googleapis.com/token", data=body), timeout=30) as response:
                    return json.load(response)["access_token"]
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError) as exc:
                raise Unavailable(f"could not refresh the Google credentials in {path}: {exc}")
        try:
            request = urllib.request.Request(
                "http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token",
                headers={"Metadata-Flavor": "Google"})
            with urllib.request.urlopen(request, timeout=5) as response:
                return json.load(response)["access_token"]
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError) as exc:
            raise Unavailable(f"no Google access token: no Application Default Credentials file, and the "
                              f"metadata server did not answer ({exc})")

    def get(self, path, **query):
        url = f"{self.base}/api/workspaces/v1/{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise Unavailable(f"GET {path}: HTTP {exc.code}")
        except (urllib.error.URLError, TimeoutError) as exc:
            raise Unavailable(f"GET {path}: {exc}")
        except json.JSONDecodeError as exc:
            raise Unavailable(f"GET {path}: {exc}")

    def resources(self):
        offset = 0
        while True:
            page = self.get(f"{self.workspace_uuid}/resources", offset=offset, limit=PAGE).get("resources", [])
            yield from page
            if len(page) < PAGE:
                return
            offset += PAGE


def data_resource(resource):
    """What one Workspace Manager resource record is to the sandbox: a dataset or a bucket, with
    the workspace's stewardship of it; None for anything else (a git repository, a notebook)."""
    attrs = resource.get("resourceAttributes") or {}
    metadata = resource.get("metadata") or {}
    stewardship = "controlled" if metadata.get("stewardshipType") == "CONTROLLED" else "referenced"
    record = {"name": metadata.get("name"), "stewardship": stewardship}
    if "gcpBqDataset" in attrs:
        d = attrs["gcpBqDataset"]
        return {**record, "type": "bigquery", "project": d["projectId"], "dataset": d["datasetId"]}
    if "gcpGcsBucket" in attrs:
        return {**record, "type": "storage", "bucket": attrs["gcpGcsBucket"]["bucketName"]}
    if "gcpGcsObject" in attrs:
        # One object of a bucket the workspace does not hold: the bucket is readable, never written.
        return {**record, "stewardship": "referenced", "type": "storage", "bucket": attrs["gcpGcsObject"]["bucketName"]}
    return None


def collect(records):
    """The data resources among the records, one entry per dataset or bucket. A bucket both
    owned and referenced (an object reference into an owned bucket) is owned."""
    found = {}
    for record in records:
        data = data_resource(record)
        if not data:
            continue
        key = (data["type"], data.get("project"), data.get("dataset") or data.get("bucket"))
        if key in found and found[key]["stewardship"] == "controlled":
            continue
        found[key] = data
    return list(found.values())


def main():
    output = {"workspace": None, "project": None, "resources": [], "unavailable": False, "errors": []}
    try:
        wb = Workbench()
        output["workspace"] = wb.workspace_id
        output["project"] = wb.project
        output["resources"] = collect(wb.resources())
    except Exception as exc:  # Unavailable, or anything unexpected: fail closed either way.
        output.update(resources=[], unavailable=True)
        output["errors"].append(str(exc) if isinstance(exc, Unavailable) else f"{type(exc).__name__}: {exc}")
        print(f"workspace-data: {exc}; no data rules until Workbench can be read", file=sys.stderr)
    text = json.dumps(output, indent=2, sort_keys=True) + "\n"
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8") as handle:
            handle.write(text)
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
