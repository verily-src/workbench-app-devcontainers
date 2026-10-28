#!/usr/bin/env python3
"""Reads the OpenShell policy attributes of the data collections this workspace imported.

usage: collection-policy.py [output.json]      (JSON to the file, or to stdout)

A data collection is a Workbench workspace whose properties include terra-type=data-collection.
Its owners say how an agent may behave while the collection's data is in a workspace by setting
openshell-* properties on the collection workspace and, for one version, on the version folder
(README, "Data collection policies"):

  openshell-internet         none | host[,host...]   hosts the agent may reach besides the model and the data
  openshell-agent-access     read | none             whether the agent may read the collection's data at all
  openshell-rule-approvals   true | false            whether a user may approve rules OpenShell drafts

Every resource imported from a collection carries the collection in its lineage, so collections
are found from the workspace's resources, not declared. render-policy.py composes them with
policy.yaml and data-access.yaml, strictest wins.

The output is written even when Workbench cannot be read: "unavailable" is then true and
render-policy.py assumes the strictest constraints. An openshell-* key this version does not know
is reported in "unknown_keys" and has the same effect, so a collection's newer rule is never
silently ignored by an older app.
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

KNOWN_KEYS = {"openshell-internet", "openshell-agent-access", "openshell-rule-approvals"}
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


class Wsm:
    """The Workspace Manager API, as the user the CLI is logged in as."""

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
        try:
            self.token = subprocess.run(["wb", "auth", "print-access-token"], check=True,
                                        capture_output=True, text=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError) as exc:
            raise Unavailable(f"no Workbench access token: {getattr(exc, 'stderr', exc)}".strip()[:300])

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
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise Unavailable(f"GET {path}: {exc}")

    def resources(self, workspace_uuid):
        offset = 0
        while True:
            page = self.get(f"{workspace_uuid}/resources", offset=offset, limit=PAGE).get("resources", [])
            yield from page
            if len(page) < PAGE:
                return
            offset += PAGE


def properties(record):
    """A record's properties as a dict; WSM returns a list of {key, value}."""
    return {p["key"]: p["value"] for p in record.get("properties") or []}


def openshell_properties(props):
    return {k: v for k, v in props.items() if k.startswith("openshell-")}


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


def collect(wsm):
    """The collections this workspace imported from, with their constraints and data."""
    collections = {}
    workspaces = {}  # source workspace uuid -> record, or None when it is not a collection

    for resource in wsm.resources(wsm.workspace_uuid):
        metadata = resource["metadata"]
        for link in metadata.get("resourceLineage") or []:
            source_uuid = link["sourceWorkspaceId"]
            if source_uuid not in workspaces:
                try:
                    record = wsm.get(source_uuid)
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
                # One listing of the collection's resources and folders serves every resource
                # imported from it; a lookup per resource took most of the run.
                collections[source_uuid] = {
                    "uuid": source_uuid,
                    "id": record.get("userFacingId"),
                    "name": record.get("displayName"),
                    "properties": openshell_properties(properties(record)),
                    "versions": {},
                    "resources": [],
                    "_folder_of": {r["metadata"]["resourceId"]: r["metadata"].get("folderId")
                                   for r in wsm.resources(source_uuid)},
                    "_folders": {f["id"]: f for f in wsm.get(f"{source_uuid}/folders").get("folders", [])},
                }
            collection = collections[source_uuid]
            # The collection version is the folder the source resource sits in.
            folder_id = collection["_folder_of"].get(link["sourceResourceId"])
            if folder_id and folder_id not in collection["versions"]:
                folder = collection["_folders"].get(folder_id, {})
                collection["versions"][folder_id] = {
                    "name": folder.get("displayName"),
                    "properties": openshell_properties(properties(folder)),
                }
            data = data_resource(resource)
            if data:
                data["version"] = folder_id
                collection["resources"].append(data)
            break  # one collection per resource: the first readable collection in its lineage

    result = []
    for collection in collections.values():
        # Constraints: the collection's, then each imported version's on top. Two versions with
        # different values both apply; render-policy.py takes the strictest.
        constraints = [dict(collection["properties"])]
        for version in collection["versions"].values():
            if version["properties"]:
                constraints.append({**collection["properties"], **version["properties"]})
        unknown = sorted({k for c in constraints for k in c} - KNOWN_KEYS)
        public = {k: v for k, v in collection.items() if not k.startswith("_")}
        result.append({**public, "constraints": constraints, "unknown_keys": unknown})
    return result


def main():
    output = {"workspace": None, "collections": [], "unavailable": False, "errors": []}
    try:
        wsm = Wsm()
        output["workspace"] = wsm.workspace_id
        output["collections"] = collect(wsm)
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
