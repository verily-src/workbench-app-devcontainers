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

Every endpoint of every rule gets enforcement: enforce. OpenShell's default is audit, which logs
a violating request and lets it through; a rule in policy.yaml without the field would not be a
rule at all.

collections.json, written by collection-policy.py, holds the ai-policy.yaml of every data
collection this workspace imported from, and the datasets and buckets imported from each. The
policies compose with the files above, strictest wins (README, "Data collection policies"):

  version: 1
  network:
    egress: none | any | [host, "*.domain", ...]
  data:
    access: read | none

  network.egress   none removes every network rule but the model and the data; a host list keeps
                   only policy.yaml rules whose hosts every collection's list allows (a "*.d"
                   entry allows d and its subdomains); any (the default) keeps them all.
  data.access      read (the default) adds the collection's datasets and buckets to the data
                   rules; none adds nothing and removes them from data-access.yaml as well.

If Workbench could not be read, a collection's file could not be read or parsed, or it uses a
key or version this app does not know, the strictest posture applies to that source: no network
beyond the model and the data, and no access to that collection's data.
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
# A host, or "*." and a host: OpenShell's own endpoint wildcard.
HOST = re.compile(r"^(\*\.)?[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
GENERATED_RULES = ("data_bigquery", "data_storage")
# ai-policy.yaml, the one file a data collection describes its AI policy in.
POLICY_VERSION = 1
POLICY_SECTIONS = {"version": None, "network": {"egress"}, "data": {"access"}}


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


def host_allowed(host, allowed):
    """Whether a rule's host is within one egress list. "*.d" allows d and its subdomains; a
    wildcard host in the rule needs a wildcard entry at least as wide."""
    for entry in allowed:
        if host == entry:
            return True
        if entry.startswith("*."):
            domain = entry[2:]
            if host == domain or host.endswith("." + domain):
                return True
            if host.startswith("*.") and (host[2:] == domain or host[2:].endswith("." + domain)):
                return True
    return False


class Decisions:
    """What the collections decided, for the policy header, --summary and `approve`."""

    def __init__(self):
        # Egress constraints, one per source: None for "none", else a host list. A host is
        # allowed only if every constraint allows it, which is the meet without computing the
        # intersection of wildcard patterns.
        self.egress = []
        self.collections = []
        self.notes = []

    def note(self, text):
        self.notes.append(text)

    def restrict_egress(self, hosts, source):
        self.egress.append({"source": source, "hosts": hosts})
        if hosts is None:
            self.note(f"network egress: none ({source})")
        else:
            self.note(f"network egress: only {', '.join(hosts)} ({source})")

    @property
    def egress_none(self):
        return any(c["hosts"] is None for c in self.egress)

    def egress_allows(self, host):
        if self.egress_none:
            return False
        return all(host_allowed(host, c["hosts"]) for c in self.egress)

    def summary(self):
        return {
            "egress": {
                "constrained": bool(self.egress),
                "none": self.egress_none,
                "constraints": self.egress,
            },
            "collections": self.collections,
            "notes": self.notes,
        }


class InvalidPolicy(Exception):
    """An ai-policy.yaml this app cannot follow as written; the strictest policy applies."""


def read_policy(policy, source):
    """Validates one collection's ai-policy.yaml and returns (egress, read): egress is None for
    "none", a host list, or "any" when unset; read says whether the agent may read its data."""
    unknown = sorted(set(policy) - set(POLICY_SECTIONS))
    if unknown:
        raise InvalidPolicy(f"uses {', '.join(unknown)}, which this app does not know")
    if policy.get("version") != POLICY_VERSION:
        raise InvalidPolicy(f"is version {policy.get('version')!r}; this app knows version {POLICY_VERSION}")
    for section, keys in POLICY_SECTIONS.items():
        if keys is None or section not in policy:
            continue
        if not isinstance(policy[section], dict):
            raise InvalidPolicy(f"{section} must be a mapping")
        unknown = sorted(set(policy[section]) - keys)
        if unknown:
            raise InvalidPolicy(f"{section} uses {', '.join(unknown)}, which this app does not know")

    egress = (policy.get("network") or {}).get("egress", "any")
    if egress == "none":
        egress = None
    elif egress != "any":
        if isinstance(egress, str):
            egress = [h.strip() for h in egress.split(",") if h.strip()]
        if not isinstance(egress, list) or not egress or \
                not all(isinstance(h, str) and HOST.match(h) for h in egress):
            raise InvalidPolicy("network.egress must be none, any or a list of hosts, got "
                                f"{(policy.get('network') or {}).get('egress')!r}")
    access = (policy.get("data") or {}).get("access", "read")
    if access not in ("read", "none"):
        raise InvalidPolicy(f"data.access must be read or none, got {access!r}")
    return egress, access == "read"


def apply_collections(sources, decisions):
    """Reads collections.json into decisions and returns the data each collection grants
    (reads) and denies (its own resources, when it refuses agent access)."""
    grants, denials = [], []
    if sources.get("unavailable"):
        decisions.note("Workbench could not be read; the strictest constraints apply "
                       f"({'; '.join(sources.get('errors') or [])})")
        decisions.restrict_egress(None, "Workbench unavailable")
        return grants, denials

    for collection in sources.get("collections") or []:
        name = collection.get("id") or collection.get("uuid")
        source = f"collection {name}"
        policy, error = collection.get("policy"), collection.get("policy_error")
        read = True
        if policy is not None and error is None:
            try:
                egress, read = read_policy(policy, source)
            except InvalidPolicy as exc:
                error = f"{collection.get('policy_source') or 'ai-policy.yaml'} {exc}"
        if error:
            # The collection asked for something; not understanding it must not loosen anything.
            decisions.note(f"{source}: {error}; the strictest constraints apply")
            decisions.restrict_egress(None, source)
            read = False
        elif policy is not None and egress != "any":
            decisions.restrict_egress(egress, source)
        resources = collection.get("resources") or []
        (grants if read else denials).extend({**r, "source": source} for r in resources)
        decisions.collections.append({
            "id": name,
            "policy": collection.get("policy_source") or ("none" if policy is None else "invalid"),
            "data_access": "read" if read else "none",
            "resources": [r.get("dataset") or r.get("bucket") for r in resources],
        })
        if not read and resources:
            decisions.note(f"{source}: data access none; its {len(resources)} resources are not readable")
    return grants, denials


def filter_egress(policy, decisions):
    """Removes the network rules the collections' egress constraints do not allow."""
    if not decisions.egress:
        return
    network = policy.get("network_policies") or {}
    removed = kept = 0
    for name in list(network):
        if name == "local_models" or name in GENERATED_RULES:
            continue
        hosts = sorted({e.get("host") for e in network[name].get("endpoints") or [] if e.get("host")})
        if hosts and all(decisions.egress_allows(h) for h in hosts):
            kept += 1
            continue
        del network[name]
        removed += 1
        decisions.note(f"removed network rule {name} ({', '.join(hosts) or 'no host'}): "
                       "not allowed by every collection")
    if len(decisions.egress) > 1 and removed and not kept and not decisions.egress_none:
        decisions.note("the collections' egress lists share no host: nothing beyond the model "
                       "and the data is reachable")


def enforce_everywhere(policy, decisions):
    """OpenShell's default enforcement is audit: log and allow. Every rule here enforces."""
    for name, rule in (policy.get("network_policies") or {}).items():
        for ep in rule.get("endpoints") or []:
            if ep.get("enforcement") != "enforce":
                decisions.note(f"set enforcement: enforce on rule {name} ({ep.get('host')}); "
                               f"it was {ep.get('enforcement') or 'unset, which audits only'}")
                ep["enforcement"] = "enforce"


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
    filter_egress(policy, decisions)

    # Data access: data-access.yaml's lists, then the collections' resources. A collection that
    # refuses agent access also removes its resources from data-access.yaml, and once any
    # collection is present, a dataset referenced directly from a collection's project (not
    # imported through the collection) is dropped: it would be the collection's data without its
    # policy.
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

    enforce_everywhere(policy, decisions)

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
