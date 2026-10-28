#!/usr/bin/env python3
"""Writes the effective sandbox policy: policy.yaml, the harness, data access, and the policies of
the data collections in the workspace.

usage: render-policy.py <policy.yaml> <data-access.yaml> <harness.yaml> [collections.json] [--summary <file>]
       (the policy goes to stdout; --summary writes what was decided and why as JSON)

The harness's binaries become the programs allowed to call Ollama's chat API (the local_models
rule). When data access is off, nothing else is added. When it is on, two network rules are
added, both limited to one Python interpreter and bound to the OpenShell credential provider so
the proxy supplies the token:

  data_bigquery   jobs and queries only in the execution project (SQL text is not visible to
                  OpenShell rules, see the README), lookups only in the listed datasets. No
                  DELETE, PATCH or PUT, no insertAll, no uploads: anything not listed is denied.
  data_storage    GET only, on the listed buckets.

collections.json, written by collection-policy.py, holds the openshell-* properties of every
data collection this workspace imported from, and the datasets and buckets imported from each.
They compose with the files above, strictest wins (README, "Data collection policies"):

  openshell-internet        none removes every network rule but the model and the data; a host
                            list keeps only rules whose hosts are all listed. Lists intersect.
  openshell-agent-access    read (the default) adds the collection's datasets and buckets to the
                            data rules; none adds nothing and removes them from data-access.yaml.
  openshell-rule-approvals  false stops agent-sandbox approving rules OpenShell drafts.

If collections.json says Workbench could not be read, or a collection uses an openshell-* key
this version does not know, the strictest posture applies: no internet, no approvals.
"""
import json
import re
import sys

import yaml

import harness as harness_definition

PROJECT = re.compile(r"^[a-z][a-z0-9.:-]{4,60}[a-z0-9]$")
DATASET = re.compile(r"^[A-Za-z0-9_]{1,1024}$")
BUCKET = re.compile(r"^[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]$")
PROVIDER = re.compile(r"^[A-Za-z0-9._-]{1,63}$")
HOST = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
GENERATED_RULES = ("data_bigquery", "data_storage")


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


def bigquery_rules(project, datasets):
    base = "/bigquery/v2/projects"
    rules = [
        allow("POST", f"{base}/{project}/jobs"),
        allow("POST", f"{base}/{project}/queries"),
        allow("GET", f"{base}/{project}/jobs/**"),
        allow("GET", f"{base}/{project}/queries/**"),
    ]
    for dataset_project, dataset in datasets:
        path = f"{base}/{dataset_project}/datasets/{dataset}"
        rules += [allow("GET", path), allow("GET", f"{path}/**")]
    return rules


def storage_rules(buckets):
    rules = []
    for bucket in buckets:
        rules += [
            allow("GET", f"/storage/v1/b/{bucket}"),
            allow("GET", f"/storage/v1/b/{bucket}/o"),
            allow("GET", f"/storage/v1/b/{bucket}/o/**"),
            allow("GET", f"/download/storage/v1/b/{bucket}/o/**"),
            allow("GET", f"/{bucket}/**"),
        ]
    return rules


class Decisions:
    """What the collections decided, for the policy header and --summary."""

    def __init__(self):
        self.internet = None  # None: unrestricted; set(): hosts allowed; empty set: none
        self.rule_approvals = True
        self.collections = []
        self.notes = []

    def note(self, text):
        self.notes.append(text)

    def restrict_internet(self, hosts, source):
        """hosts is None for "none". Lists intersect; none wins."""
        if hosts is None:
            if self.internet != set():
                self.note(f"internet: none ({source})")
            self.internet = set()
        elif self.internet is None:
            self.internet = set(hosts)
            self.note(f"internet: only {', '.join(sorted(hosts))} ({source})")
        elif self.internet:
            self.internet &= set(hosts)
            self.note(f"internet: intersected with {', '.join(sorted(hosts))} ({source})")

    def forbid_approvals(self, source):
        if self.rule_approvals:
            self.note(f"rule approvals: disabled ({source})")
        self.rule_approvals = False

    def summary(self):
        return {
            "internet": None if self.internet is None else sorted(self.internet),
            "rule_approvals": self.rule_approvals,
            "collections": self.collections,
            "notes": self.notes,
        }


def parse_internet(value, source):
    value = value.strip()
    if value == "none":
        return None
    hosts = [h.strip() for h in value.split(",") if h.strip()]
    for host in hosts:
        if not HOST.match(host):
            fail(f"{source}: openshell-internet has an invalid host {host!r}")
    return hosts


def parse_flag(value, key, source, true, false):
    value = value.strip()
    if value == true:
        return True
    if value == false:
        return False
    fail(f"{source}: {key} must be {true} or {false}, got {value!r}")


def apply_collections(sources, decisions):
    """Reads collections.json into decisions and returns the data each collection grants
    (reads) and denies (its own resources, when it refuses agent access)."""
    grants, denials = [], []
    if sources.get("unavailable"):
        decisions.note("Workbench could not be read; the strictest constraints apply "
                       f"({'; '.join(sources.get('errors') or [])})")
        decisions.restrict_internet(None, "Workbench unavailable")
        decisions.forbid_approvals("Workbench unavailable")
        return grants, denials

    for collection in sources.get("collections") or []:
        name = collection.get("id") or collection.get("uuid")
        versions = sorted(v.get("name") or "?" for v in (collection.get("versions") or {}).values())
        source = f"collection {name} {'/'.join(versions)}".strip()
        access = True
        if collection.get("unknown_keys"):
            decisions.note(f"{source} uses {', '.join(collection['unknown_keys'])}, which this app "
                           "does not know; the strictest constraints apply")
            decisions.restrict_internet(None, source)
            decisions.forbid_approvals(source)
            access = False
        for constraint in collection.get("constraints") or [{}]:
            if "openshell-internet" in constraint:
                decisions.restrict_internet(parse_internet(constraint["openshell-internet"], source), source)
            if "openshell-rule-approvals" in constraint and not parse_flag(
                    constraint["openshell-rule-approvals"], "openshell-rule-approvals", source, "true", "false"):
                decisions.forbid_approvals(source)
            if "openshell-agent-access" in constraint and not parse_flag(
                    constraint["openshell-agent-access"], "openshell-agent-access", source, "read", "none"):
                access = False
        resources = collection.get("resources") or []
        (grants if access else denials).extend({**r, "source": source} for r in resources)
        decisions.collections.append({
            "id": name, "versions": versions, "agent_access": "read" if access else "none",
            "resources": [r.get("dataset") or r.get("bucket") for r in resources],
        })
        if not access and resources:
            decisions.note(f"{source}: agent access none; its {len(resources)} resources are not readable")
    return grants, denials


def filter_internet(policy, decisions):
    """Removes the network rules the collections' internet constraint does not allow."""
    if decisions.internet is None:
        return
    network = policy.get("network_policies") or {}
    for name in list(network):
        if name == "local_models" or name in GENERATED_RULES:
            continue
        hosts = {e.get("host") for e in network[name].get("endpoints") or []}
        if hosts and hosts <= decisions.internet:
            continue
        del network[name]
        decisions.note(f"removed network rule {name} ({', '.join(sorted(h for h in hosts if h))}): "
                       "not allowed by the collections")


def main():
    args = sys.argv[1:]
    summary_path = None
    if "--summary" in args:
        index = args.index("--summary")
        try:
            summary_path = args[index + 1]
        except IndexError:
            fail("--summary needs a file")
        del args[index:index + 2]
    if len(args) not in (3, 4):
        fail(__doc__.split("\n")[3].strip())

    with open(args[0], encoding="utf-8") as handle:
        policy = yaml.safe_load(handle)
    with open(args[1], encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    harness = harness_definition.load(args[2])
    sources = {}
    if len(args) == 4:
        with open(args[3], encoding="utf-8") as handle:
            sources = json.load(handle)

    local_models = (policy.get("network_policies") or {}).get("local_models")
    if not local_models:
        fail("policy.yaml has no local_models rule: it is where the harness reaches the local models")
    # curl stays so `selftest` can check the path rules.
    local_models["binaries"] = [{"path": path} for path in harness["binaries"] + ["/usr/bin/curl"]]

    decisions = Decisions()
    grants, denials = apply_collections(sources, decisions)
    filter_internet(policy, decisions)

    # Data access: data-access.yaml's lists, then the collections' resources. A collection that
    # refuses agent access also removes its resources from data-access.yaml, and once any
    # collection is present, a dataset referenced directly from a collection's project (not
    # imported through the collection) is dropped: it would be the collection's data without its
    # constraints.
    datasets, buckets = [], []
    for entry in (config.get("bigquery") or {}).get("datasets") or []:
        datasets.append((checked(PROJECT, entry.get("project"), "BigQuery dataset project"),
                         checked(DATASET, entry.get("dataset"), "BigQuery dataset")))
    for bucket in (config.get("storage") or {}).get("buckets") or []:
        buckets.append(checked(BUCKET, bucket, "bucket name"))
    denied_datasets = {(r["project"], r["dataset"]) for r in denials if r["type"] == "bigquery"}
    denied_buckets = {r["bucket"] for r in denials if r["type"] == "storage"}
    collection_datasets = {(r["project"], r["dataset"]) for r in grants + denials if r["type"] == "bigquery"}
    collection_projects = {project for project, _ in collection_datasets}
    kept = []
    for project, dataset in datasets:
        if (project, dataset) in denied_datasets:
            decisions.note(f"removed dataset {project}.{dataset} from data-access.yaml: its collection refuses agent access")
        elif project in collection_projects and (project, dataset) not in collection_datasets:
            decisions.note(f"removed dataset {project}.{dataset} from data-access.yaml: it is in a data "
                           "collection's project but was not imported from the collection")
        else:
            kept.append((project, dataset))
    datasets = kept
    for bucket in denied_buckets & set(buckets):
        decisions.note(f"removed bucket {bucket} from data-access.yaml: its collection refuses agent access")
    buckets = [b for b in buckets if b not in denied_buckets]
    for grant in grants:
        if grant["type"] == "bigquery":
            pair = (checked(PROJECT, grant["project"], "collection dataset project"),
                    checked(DATASET, grant["dataset"], "collection dataset"))
            if pair not in datasets:
                datasets.append(pair)
        else:
            bucket = checked(BUCKET, grant["bucket"], "collection bucket")
            if bucket not in buckets:
                buckets.append(bucket)

    if config.get("enabled") is True:
        provider = checked(PROVIDER, config.get("provider") or "wb-gcp", "provider name")
        project = checked(PROJECT, config.get("project_id"), "project_id (set it in data-access.yaml)")
        python = config.get("python") or "/usr/bin/python3.11"
        if not isinstance(python, str) or not python.startswith("/"):
            fail(f"python must be an absolute path: {python!r}")
        network = policy.setdefault("network_policies", {})
        for name in GENERATED_RULES:
            if name in network:
                fail(f"policy.yaml already defines {name}; remove it, data-access.yaml generates it")
        network["data_bigquery"] = {
            "name": "data_bigquery",
            "endpoints": [endpoint("bigquery.googleapis.com", provider, bigquery_rules(project, datasets))],
            "binaries": [{"path": python}],
        }
        if buckets:
            network["data_storage"] = {
                "name": "data_storage",
                "endpoints": [endpoint("storage.googleapis.com", provider, storage_rules(buckets))],
                "binaries": [{"path": python}],
            }
        if grants:
            decisions.note(f"data access: {len(datasets)} datasets, {len(buckets)} buckets "
                           f"({len(grants)} from collections)")
    elif grants:
        decisions.note("data access is off in data-access.yaml, so the collections' data is not "
                       "reachable; set enabled: true to let the agent read it")

    sys.stdout.write("# Generated by render-policy.py from policy.yaml, data-access.yaml, harness.yaml"
                     + (" and collections.json" if sources else "") + ". Do not edit.\n")
    for note in decisions.notes:
        sys.stdout.write(f"# {note}\n")
    yaml.safe_dump(policy, sys.stdout, sort_keys=False, default_flow_style=False)
    if summary_path:
        with open(summary_path, "w", encoding="utf-8") as handle:
            json.dump(decisions.summary(), handle, indent=2)
            handle.write("\n")


main()
