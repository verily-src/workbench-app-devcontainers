#!/usr/bin/env python3
"""Reads the AI policy of every data collection this workspace imported from.

usage: collection-policy.py [output.json]      (JSON to the file, or to stdout)

A data collection is a Workbench workspace whose properties include terra-type=data-collection.
Its owners say how an AI agent may behave while the collection's data is in a workspace in one
file, ai-policy.yaml, kept in the collection as a Cloud Storage object resource named ai-policy
(README, "Data collection policies"). The file is what the Workbench UI shows when the collection
is browsed, and what this script reads, so there is one source.

Every resource imported from a collection carries the collection in its lineage, so collections
are found from the workspace's resources, not declared. This script fetches each collection's
file and parses it as YAML; render-policy.py owns the schema and composes the policies with
policy.yaml and data-access.yaml, strictest wins.

The output is written even when Workbench cannot be read: "unavailable" is then true. A
collection whose file exists but cannot be read or parsed gets "policy_error". In both cases
render-policy.py assumes the strictest constraints, so a collection's rule is never silently
dropped. A collection with no ai-policy resource has "policy": null and sets no constraint.
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

import yaml

POLICY_RESOURCE = "ai-policy"
PAGE = 100


class Unavailable(Exception):
    """Workbench could not be read; the caller writes a fail-closed result."""


def wb_json(*args):
    try:
        out = subprocess.run(["wb", *args, "--format=json"], check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise Unavailable(f"wb {' '.join(args)} failed: {getattr(exc, 'stderr', exc)}".strip()[:300])
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError as exc:
        raise Unavailable(f"wb {' '.join(args)} did not return JSON: {exc}")


class Workbench:
    """The Workspace Manager API and Cloud Storage, as the user the CLI is logged in as."""

    def __init__(self):
        # The CLI's context file names the workspace and the server; reading it saves two JVM
        # starts (about 12 seconds) on every run. The CLI itself is the fallback.
        context = {}
        try:
            with open(os.path.expanduser(os.environ.get("WB_CONTEXT", "~/.workbench/context.json")),
                      encoding="utf-8") as handle:
                context = json.load(handle)
        except (OSError, json.JSONDecodeError):
            pass
        workspace = context.get("workspace") or {}
        base = (context.get("server") or {}).get("workspaceManagerUri")
        if workspace.get("uuid") and workspace.get("userFacingId") and base:
            self.workspace_uuid = workspace["uuid"]
            self.workspace_id = workspace["userFacingId"]
        else:
            workspace = wb_json("workspace", "describe")
            self.workspace_uuid = workspace["uuid"]
            self.workspace_id = workspace["id"]
            server = next((s for s in wb_json("server", "list") if s["name"] == workspace["serverName"]), None)
            base = (server or {}).get("workspaceManagerUri")
            if not base:
                raise Unavailable(f"no Workspace Manager URL for server {workspace['serverName']!r}")
        self.base = base.rstrip("/")
        # Workspace Manager takes the Workbench token; Cloud Storage takes the user's Google
        # credentials, which the app's Application Default Credentials hold (wb logs in with them).
        self.token = self._token(["wb", "auth", "print-access-token"], "Workbench")
        self._google_token = None

    @staticmethod
    def _token(command, what):
        try:
            return subprocess.run(command, check=True, capture_output=True, text=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError) as exc:
            raise Unavailable(f"no {what} access token: {getattr(exc, 'stderr', exc)}".strip()[:300])

    def google_token(self):
        if self._google_token is None:
            self._google_token = self._token(["gcloud", "auth", "print-access-token"], "Google")
        return self._google_token

    def _fetch(self, url, what, token=None):
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token or self.token}"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            raise Unavailable(f"{what}: HTTP {exc.code}")
        except (urllib.error.URLError, TimeoutError) as exc:
            raise Unavailable(f"{what}: {exc}")

    def get(self, path, **query):
        url = f"{self.base}/api/workspaces/v1/{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        try:
            return json.loads(self._fetch(url, f"GET {path}"))
        except json.JSONDecodeError as exc:
            raise Unavailable(f"GET {path}: {exc}")

    def resources(self, workspace_uuid):
        offset = 0
        while True:
            page = self.get(f"{workspace_uuid}/resources", offset=offset, limit=PAGE).get("resources", [])
            yield from page
            if len(page) < PAGE:
                return
            offset += PAGE

    def storage_object(self, bucket, name):
        """The bytes of one Cloud Storage object, with the user's own access."""
        url = (f"https://storage.googleapis.com/storage/v1/b/{urllib.parse.quote(bucket, safe='')}"
               f"/o/{urllib.parse.quote(name, safe='')}?alt=media")
        return self._fetch(url, f"gs://{bucket}/{name}", token=self.google_token())


def properties(record):
    """A record's properties as a dict; WSM returns a list of {key, value}."""
    return {p["key"]: p["value"] for p in record.get("properties") or []}


def data_resource(resource):
    """What a resource grants, if it is data the sandbox could read: a dataset or a bucket."""
    attrs = resource.get("resourceAttributes") or {}
    name = resource["metadata"]["name"]
    if "gcpBqDataset" in attrs:
        d = attrs["gcpBqDataset"]
        return {"name": name, "type": "bigquery", "project": d["projectId"], "dataset": d["datasetId"]}
    if "gcpGcsBucket" in attrs:
        return {"name": name, "type": "storage", "bucket": attrs["gcpGcsBucket"]["bucketName"]}
    if "gcpGcsObject" in attrs:
        return {"name": name, "type": "storage", "bucket": attrs["gcpGcsObject"]["bucketName"]}
    return None


def read_policy(wb, collection_uuid, collection_resources):
    """The collection's ai-policy.yaml, parsed: (policy, source, error). policy is None when the
    collection has no ai-policy resource; error is set when the file exists but cannot be read
    or parsed, and the caller treats that as the strictest policy."""
    candidates = [r for r in collection_resources if r["metadata"]["name"] == POLICY_RESOURCE]
    if not candidates:
        return None, None, None
    if len(candidates) > 1:
        return None, None, f"{len(candidates)} resources named {POLICY_RESOURCE}; expected one"
    attrs = (candidates[0].get("resourceAttributes") or {}).get("gcpGcsObject")
    if not attrs:
        return None, None, f"resource {POLICY_RESOURCE} is not a Cloud Storage object"
    source = f"gs://{attrs['bucketName']}/{attrs['fileName']}"
    try:
        text = wb.storage_object(attrs["bucketName"], attrs["fileName"]).decode("utf-8")
        policy = yaml.safe_load(text)
    except Unavailable as exc:
        return None, source, str(exc)
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        return None, source, f"{source} is not valid YAML: {str(exc)[:200]}"
    if not isinstance(policy, dict):
        return None, source, f"{source} must be a YAML mapping"
    return policy, source, None


def collect(wb):
    """The collections this workspace imported from, with their policy and their data here."""
    collections = {}
    workspaces = {}  # source workspace uuid -> record, or None when it is not a collection

    for resource in wb.resources(wb.workspace_uuid):
        metadata = resource["metadata"]
        for link in metadata.get("resourceLineage") or []:
            source_uuid = link["sourceWorkspaceId"]
            if source_uuid not in workspaces:
                try:
                    record = wb.get(source_uuid)
                except Unavailable as exc:
                    # Lineage to a workspace this user cannot read: not a collection they
                    # imported from, or one they lost access to. Either way no data comes from it.
                    workspaces[source_uuid] = None
                    print(f"collection-policy: skipping lineage workspace {source_uuid}: {exc}", file=sys.stderr)
                    continue
                workspaces[source_uuid] = record if properties(record).get("terra-type") == "data-collection" else None
            record = workspaces[source_uuid]
            if record is None:
                continue
            if source_uuid not in collections:
                policy, source, error = read_policy(wb, source_uuid, list(wb.resources(source_uuid)))
                collections[source_uuid] = {
                    "uuid": source_uuid,
                    "id": record.get("userFacingId"),
                    "name": record.get("displayName"),
                    "policy": policy,
                    "policy_source": source,
                    "policy_error": error,
                    "resources": [],
                }
                if error:
                    print(f"collection-policy: {record.get('userFacingId')}: {error}; "
                          "the strictest constraints apply", file=sys.stderr)
            data = data_resource(resource)
            if data:
                collections[source_uuid]["resources"].append(data)
            break  # one collection per resource: the first readable collection in its lineage
    return list(collections.values())


def main():
    output = {"workspace": None, "collections": [], "unavailable": False, "errors": []}
    try:
        wb = Workbench()
        output["workspace"] = wb.workspace_id
        output["collections"] = collect(wb)
    except Unavailable as exc:
        output["unavailable"] = True
        output["errors"].append(str(exc))
        print(f"collection-policy: {exc}; the strictest constraints apply until Workbench can be read",
              file=sys.stderr)
    text = json.dumps(output, indent=2, sort_keys=True) + "\n"
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8") as handle:
            handle.write(text)
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
