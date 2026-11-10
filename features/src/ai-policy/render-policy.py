#!/usr/bin/env python3
"""Writes the effective sandbox policy: the base policy, the harness's binaries, the workspace's
data and the Workbench tools, as ai-policy.yaml allows them. The feature's README describes the
rules it generates (data_bigquery, data_storage, workbench_tools).

usage: render-policy.py <policy.yaml> <ai-policy.yaml> --harness <harness.json>
           [--workspace <workspace-data.json>] [--tools <tool-groups.yaml>] [--mcp-url <url>]
           [--provider wb-gcp] [--data-binary /usr/bin/python3.11] [--summary <file>]
       (the policy goes to stdout; --summary writes what was decided and why as JSON)

Every endpoint of every rule gets enforcement: enforce. OpenShell's default is audit, which
logs a violating request and lets it through. If Workbench could not be read
(workspace-data.json says unavailable), no data rules are rendered and the summary says why.
"""
import argparse
import json
import os
import re
import sys
from urllib.parse import urlsplit

import yaml

import ai_policy

GENERATED_RULES = ("data_bigquery", "data_storage", "workbench_tools")
# The MCP revisions OpenShell may see: the Workbench server answers whichever a client asks for,
# and a request without the MCP-Protocol-Version header is read as the oldest.
MCP_VERSIONS = ["2025-03-26", "2025-06-18", "2025-11-25"]
# The handshake, the client's notifications and the tool listing; tools/call is allowed per
# tool name. A client cancels a call it gave up on with notifications/cancelled; denying it
# would only make a log entry (the server ignores the notification).
MCP_METHODS = ["initialize", "notifications/initialized", "notifications/cancelled", "ping", "tools/list"]
# curl stays on the model and tools endpoints so `selftest` can check the rules.
PROBE_BINARY = "/usr/bin/curl"
WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")

PROJECT = re.compile(r"^[a-z][a-z0-9.:-]{4,60}[a-z0-9]$")
DATASET = re.compile(r"^[A-Za-z0-9_]{1,1024}$")
BUCKET = re.compile(r"^[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]$")
PROVIDER = re.compile(r"^[A-Za-z0-9._-]{1,63}$")


def fail(message):
    sys.exit(f"render-policy: {message}")


def checked(pattern, value, what):
    if not isinstance(value, str) or not pattern.match(value):
        fail(f"invalid {what}: {value!r}")
    return value


def allow(method, path):
    return {"allow": {"method": method, "path": path}}


def endpoint(host, provider, rules):
    return {
        "host": host,
        "port": 443,
        "protocol": "rest",
        "enforcement": "enforce",
        "rules": rules,
        "credential_binding": {"provider": provider},
    }


def bigquery_rules(project, datasets, write):
    """datasets: (project, dataset, owned). Jobs only in the workspace's project; listing in the
    projects the datasets are in; lookups in every dataset; changes only in owned ones."""
    base = "/bigquery/v2/projects"
    rules = [
        allow("POST", f"{base}/{project}/jobs"),
        allow("POST", f"{base}/{project}/queries"),
        allow("GET", f"{base}/{project}/jobs/**"),
        allow("GET", f"{base}/{project}/queries/**"),
    ]
    for dataset_project in dict.fromkeys(p for p, _, _ in datasets):
        rules.append(allow("GET", f"{base}/{dataset_project}/datasets"))
    for dataset_project, dataset, owned in datasets:
        path = f"{base}/{dataset_project}/datasets/{dataset}"
        rules += [allow("GET", path), allow("GET", f"{path}/**")]
        if write and owned:
            rules += [allow(method, f"{path}/**") for method in WRITE_METHODS]
    return rules


def storage_rules(buckets, write):
    """buckets: (name, owned). Reads everywhere; uploads and deletes in owned buckets. Writes
    are the upload endpoint and the XML-style object URLs only: the JSON object paths also
    carry copyTo and rewriteTo, whose destination is a second bucket further along the path."""
    rules = []
    for bucket, owned in buckets:
        rules += [
            allow("GET", f"/storage/v1/b/{bucket}"),
            allow("GET", f"/storage/v1/b/{bucket}/o"),
            allow("GET", f"/storage/v1/b/{bucket}/o/**"),
            allow("GET", f"/download/storage/v1/b/{bucket}/o/**"),
            allow("GET", f"/{bucket}/**"),
        ]
        if write and owned:
            rules += [
                allow("POST", f"/upload/storage/v1/b/{bucket}/o"),
                allow("PUT", f"/upload/storage/v1/b/{bucket}/o"),
                allow("PUT", f"/{bucket}/**"),
                allow("DELETE", f"/{bucket}/**"),
            ]
    return rules


class Decisions:
    """What was decided and why, for the policy header and --summary."""

    def __init__(self):
        self.notes = []
        # What the data rules let the sandbox reach, for agent-sandbox to tell the agent.
        self.data = {"enabled": False, "write": False, "project": None, "python": None,
                     "datasets": [], "buckets": [], "unavailable": False}
        # What the tools rule lets the harness call, for the harness's configuration and the agent.
        self.tools = {"enabled": False, "url": None, "allowed": [], "denied": [], "groups": {}}

    def note(self, text):
        # One line each: the notes become comments at the top of the policy file.
        self.notes.append(" ".join(text.split()))

    def summary(self):
        return {"notes": self.notes, "data": self.data, "tools": self.tools}


def data_rules(policy, ai, workspace, project, provider, python, decisions):
    """Adds the data rules: the workspace's datasets and buckets, as ai-policy.yaml allows."""
    if not ai.read:
        decisions.note("data: none (ai-policy.yaml data.read: none); the sandbox holds no cloud credential")
        return
    # agent-sandbox says whether the sandbox gets the credential provider. Without it a policy
    # that binds the provider is refused by OpenShell, so no data rules are rendered.
    if os.environ.get("AGENT_DATA_CREDENTIAL") == "missing":
        decisions.note("data: ai-policy.yaml allows it but the metadata server gave this app no Google "
                       "credential, so no data rules were rendered; when it answers again, run "
                       "agent-sandbox reset --yes")
        return
    if workspace is None:
        decisions.note("data: no workspace-data.json was given, so no data rules were rendered")
        return
    if workspace.get("unavailable"):
        decisions.data["unavailable"] = True
        decisions.note("data: Workbench could not be read, so no data rules were rendered "
                       f"({'; '.join(workspace.get('errors') or [])})")
        return
    project = checked(PROJECT, workspace.get("project") or project, "workspace project (GOOGLE_CLOUD_PROJECT)")
    datasets, buckets = [], []
    for resource in workspace.get("resources") or []:
        owned = resource.get("stewardship") == "controlled"
        if resource.get("type") == "bigquery":
            datasets.append((checked(PROJECT, resource.get("project"), "dataset project"),
                             checked(DATASET, resource.get("dataset"), "dataset"), owned))
        elif resource.get("type") == "storage":
            buckets.append((checked(BUCKET, resource.get("bucket"), "bucket"), owned))
    datasets = list(dict.fromkeys(datasets))
    buckets = list(dict.fromkeys(buckets))
    network = policy.setdefault("network_policies", {})
    network["data_bigquery"] = {
        "name": "data_bigquery",
        "endpoints": [endpoint("bigquery.googleapis.com", provider, bigquery_rules(project, datasets, ai.write))],
        "binaries": [{"path": python}],
    }
    if buckets:
        network["data_storage"] = {
            "name": "data_storage",
            "endpoints": [endpoint("storage.googleapis.com", provider, storage_rules(buckets, ai.write))],
            "binaries": [{"path": python}],
        }
    owned = sum(1 for *_, o in datasets if o) + sum(1 for _, o in buckets if o)
    decisions.note(f"data: read {len(datasets)} datasets and {len(buckets)} buckets of workspace "
                   f"{workspace.get('workspace') or project}; "
                   + (f"write to the {owned} it owns" if ai.write else "write nowhere (ai-policy.yaml data.write: none)"))
    decisions.data.update({
        "enabled": True, "write": ai.write, "project": project, "python": python,
        "datasets": [{"project": p, "dataset": d, "write": ai.write and o} for p, d, o in datasets],
        "buckets": [{"name": b, "write": ai.write and o} for b, o in buckets],
    })


def mcp_host_port(url):
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        fail(f"--mcp-url must be an http(s) URL with a host, got {url!r}")
    host = parts.hostname
    if not ai_policy.HOST.match(host):
        fail(f"--mcp-url host {host!r} is not a hostname OpenShell accepts")
    return host, parts.port or (443 if parts.scheme == "https" else 80)


def tools_rule(policy, ai, groups, url, binaries, decisions):
    """Adds the Workbench tools rule: the groups ai-policy.yaml allows, less what it denies."""
    if ai.tools is None:
        decisions.note("Workbench tools: none (ai-policy.yaml tools.allow: none)")
        return
    if not groups:
        decisions.note("Workbench tools: no tool-groups.yaml was given, so no tools rule was rendered")
        return
    if not url:
        decisions.note("Workbench tools: this app exposes no MCP server to the sandbox (AGENT_MCP_URL); "
                       "no tools rule was rendered")
        return
    known = list(dict.fromkeys(t for tools in groups.values() for t in tools))
    if ai.tools == "all":
        allowed = list(known)
    else:
        allowed = [t for t in known if any(t in groups[g] for g in ai.tools)]
    allowed = [t for t in allowed if t not in ai.deny]
    denied = [t for t in known if t not in allowed] + [t for t in ai.deny if t not in known]
    host, port = mcp_host_port(url)
    decisions.tools = {
        "enabled": bool(allowed), "url": url, "allowed": allowed, "denied": denied,
        "groups": {g: [t for t in tools if t in allowed] for g, tools in groups.items()},
    }
    if not allowed:
        decisions.note("Workbench tools: none allowed after tools.deny; no tools rule was rendered")
        return
    rules = [{"allow": {"method": method}} for method in MCP_METHODS]
    rules.append({"allow": {"method": "tools/call", "tool": {"any": allowed}}})
    deny_rules = [{"method": "tools/call", "tool": tool} for tool in denied]
    network = policy.setdefault("network_policies", {})
    network["workbench_tools"] = {
        "name": "workbench_tools",
        "endpoints": [{
            "host": host,
            "port": port,
            "protocol": "mcp",
            "enforcement": "enforce",
            "mcp": {"versions": MCP_VERSIONS},
            "rules": rules,
            **({"deny_rules": deny_rules} if deny_rules else {}),
        }],
        "binaries": [{"path": path} for path in binaries],
    }
    decisions.note(f"Workbench tools: {len(allowed)} of {len(known)} tools allowed at {host}:{port}"
                   + (f"; denied: {', '.join(denied)}" if denied else ""))


def enforce_everywhere(policy, decisions):
    """OpenShell's default enforcement is audit: log and allow. Every rule here enforces."""
    for name, rule in (policy.get("network_policies") or {}).items():
        for ep in rule.get("endpoints") or []:
            if ep.get("enforcement") != "enforce":
                decisions.note(f"set enforcement: enforce on rule {name} ({ep.get('host')}); "
                               f"it was {ep.get('enforcement') or 'unset, which audits only'}")
                ep["enforcement"] = "enforce"


def load_yaml(path):
    with open(path, encoding="utf-8") as handle:
        return yaml.load(handle, Loader=ai_policy.StrictLoader)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], prog="render-policy.py")
    parser.add_argument("policy", help="the base policy (policy.yaml)")
    parser.add_argument("ai_policy", help="ai-policy.yaml")
    parser.add_argument("--harness", required=True, help="the harness definition as harness.py prints it (JSON)")
    parser.add_argument("--workspace", help="workspace-data.json from workspace-data.py")
    parser.add_argument("--tools", help="tool-groups.yaml: the groups the Workbench MCP server's tools fall in")
    parser.add_argument("--mcp-url", help="where the sandbox reaches the Workbench MCP server")
    parser.add_argument("--provider", default="wb-gcp", help="the OpenShell credential provider the data rules bind")
    parser.add_argument("--data-binary", default="/usr/bin/python3.11",
                        help="the one interpreter the data rules allow (venvs resolve to it)")
    parser.add_argument("--summary", help="write what was decided and why as JSON to this file")
    args = parser.parse_args()

    try:
        policy = load_yaml(args.policy)
        ai_config = load_yaml(args.ai_policy)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        fail(f"cannot read as YAML: {str(exc)[:200]}")
    if not isinstance(policy, dict):
        fail(f"{args.policy} is not a YAML mapping")
    with open(args.harness, encoding="utf-8") as handle:
        harness = json.load(handle)
    binaries = harness.get("binaries") or []
    if not isinstance(binaries, list) or not all(isinstance(b, str) and b.startswith("/") for b in binaries):
        fail(f"{args.harness}: binaries must be a list of absolute paths")
    groups = {}
    if args.tools:
        try:
            groups = ai_policy.load_tool_groups(load_yaml(args.tools))
        except (ValueError, yaml.YAMLError) as exc:
            fail(str(exc))
    try:
        ai = ai_policy.read_policy(ai_config, groups if args.tools else None)
    except ai_policy.InvalidPolicy as exc:
        fail(f"{args.ai_policy} {exc}")
    workspace = None
    if args.workspace:
        with open(args.workspace, encoding="utf-8") as handle:
            workspace = json.load(handle)
    provider = checked(PROVIDER, args.provider, "provider name")
    if not args.data_binary.startswith("/"):
        fail(f"--data-binary must be an absolute path: {args.data_binary!r}")

    local_models = (policy.get("network_policies") or {}).get("local_models")
    if not local_models:
        fail("policy.yaml has no local_models rule: it is where the harness reaches the local models")
    for name in GENERATED_RULES:
        if name in policy["network_policies"]:
            fail(f"policy.yaml already defines {name}; remove it, it is generated")
    local_models["binaries"] = [{"path": path} for path in binaries + [PROBE_BINARY]]

    decisions = Decisions()
    data_rules(policy, ai, workspace, os.environ.get("GOOGLE_CLOUD_PROJECT"), provider, args.data_binary, decisions)
    tools_rule(policy, ai, groups, args.mcp_url, binaries + [PROBE_BINARY], decisions)
    enforce_everywhere(policy, decisions)

    inputs = [os.path.basename(args.policy), os.path.basename(args.ai_policy), "the harness"]
    if args.workspace:
        inputs.append("workspace-data.json")
    if args.tools:
        inputs.append(os.path.basename(args.tools))
    sys.stdout.write(f"# Generated by render-policy.py from {', '.join(inputs)}. Do not edit.\n")
    sys.stdout.write(f"# ai-policy.yaml: {ai_policy.describe(ai)}\n")
    for note in decisions.notes:
        sys.stdout.write(f"# {note}\n")
    yaml.safe_dump(policy, sys.stdout, sort_keys=False, default_flow_style=False)
    if args.summary:
        with open(args.summary, "w", encoding="utf-8") as handle:
            json.dump(decisions.summary(), handle, indent=2)
            handle.write("\n")


main()
