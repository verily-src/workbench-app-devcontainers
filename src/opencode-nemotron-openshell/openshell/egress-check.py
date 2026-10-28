#!/usr/bin/env python3
"""Says whether hosts are within the egress the data collections allow.

usage: egress-check.py <policy.summary.json> <host> [<host>...]     exit 0: all allowed; 1: not

agent-sandbox runs it before approving a rule OpenShell drafted: an approved rule adds a host to
the sandbox's policy outside render-policy.py, so the host must be one every collection's
ai-policy.yaml egress list allows. With no egress constraint anything passes; with egress none
nothing does. Hosts match as in render-policy.py: "*.d" allows d and its subdomains.
"""
import json
import sys


def allowed(host, hosts):
    for entry in hosts:
        if host == entry:
            return True
        if entry.startswith("*."):
            domain = entry[2:]
            if host == domain or host.endswith("." + domain):
                return True
            if host.startswith("*.") and (host[2:] == domain or host[2:].endswith("." + domain)):
                return True
    return False


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__.split("\n")[2].strip())
    with open(sys.argv[1], encoding="utf-8") as handle:
        egress = json.load(handle).get("egress") or {}
    if not egress.get("constrained"):
        return
    refused = []
    for host in sys.argv[2:]:
        if egress.get("none"):
            refused.append(f"{host}: a collection allows no network egress "
                           f"({', '.join(c['source'] for c in egress['constraints'] if c['hosts'] is None)})")
            continue
        for constraint in egress["constraints"]:
            if not allowed(host, constraint["hosts"]):
                refused.append(f"{host}: not in the egress list of {constraint['source']} "
                               f"({', '.join(constraint['hosts'])})")
    if refused:
        print("\n".join(refused))
        sys.exit(1)


main()
