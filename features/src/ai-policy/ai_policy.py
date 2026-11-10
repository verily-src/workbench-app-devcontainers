#!/usr/bin/env python3
"""The ai-policy.yaml schema; the feature's README describes each key. render-policy.py turns
the file into OpenShell rules.

Anything this app does not know (an unknown key, another version, an unknown group) is refused,
so a newer file is never silently misread by an older app.
"""
import re
from collections import namedtuple

import yaml

POLICY_VERSION = 1
SECTIONS = {"version": None, "data": {"read", "write"}, "tools": {"allow", "deny"}}
# A hostname, as OpenShell accepts it in an endpoint.
HOST = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
GROUP = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
TOOL = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")

# read: whether the agent may read the workspace's data. write: whether it may write to the
# resources the workspace owns. tools: "all", None for "none", or a list of group names.
# deny: tool names never callable.
Policy = namedtuple("Policy", "read write tools deny")


class StrictLoader(yaml.SafeLoader):
    """SafeLoader that refuses a mapping with a repeated key. PyYAML keeps the last value, so
    a file with `read: none` and later `read: workspace` would read as workspace; OpenShell's
    own policy parser rejects duplicate keys, and so does this one."""

    def construct_mapping(self, node, deep=False):
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.YAMLError(f"duplicate key {key!r} at line {key_node.start_mark.line + 1}")
            seen.add(key)
        return super().construct_mapping(node, deep)


class InvalidPolicy(Exception):
    """An ai-policy.yaml this app cannot follow as written."""


def _names(value, what, pattern):
    if not isinstance(value, list) or not all(isinstance(v, str) and pattern.match(v) for v in value):
        raise InvalidPolicy(f"{what} must be a list of names, got {value!r}")
    return list(dict.fromkeys(value))


def read_policy(policy, groups=None):
    """Validates an ai-policy.yaml (already parsed) and returns a Policy. groups, when given,
    are the tool groups the app knows (tool-groups.yaml); a group the file names and the app
    lacks is refused."""
    if not isinstance(policy, dict):
        raise InvalidPolicy("must be a YAML mapping")
    unknown = sorted(set(policy) - set(SECTIONS))
    if unknown:
        raise InvalidPolicy(f"uses {', '.join(map(str, unknown))}, which this app does not know")
    if policy.get("version") != POLICY_VERSION:
        raise InvalidPolicy(f"is version {policy.get('version')!r}; this app knows version {POLICY_VERSION}")
    for section, keys in SECTIONS.items():
        if keys is None or section not in policy:
            continue
        if not isinstance(policy[section], dict):
            raise InvalidPolicy(f"{section} must be a mapping")
        unknown = sorted(set(policy[section]) - keys)
        if unknown:
            raise InvalidPolicy(f"{section} uses {', '.join(map(str, unknown))}, which this app does not know")

    data = policy.get("data") or {}
    read = data.get("read", "workspace")
    if read not in ("workspace", "none"):
        raise InvalidPolicy(f"data.read must be workspace or none, got {read!r}")
    write = data.get("write", "controlled")
    if write not in ("controlled", "none"):
        raise InvalidPolicy(f"data.write must be controlled or none, got {write!r}")
    if read == "none" and write == "controlled":
        raise InvalidPolicy("data.write: controlled needs data.read: workspace (no credential is "
                            "given to a sandbox that reads nothing)")

    tools_section = policy.get("tools") or {}
    tools = tools_section.get("allow", "all")
    if tools == "none":
        tools = None
    elif tools != "all":
        tools = _names(tools, "tools.allow", GROUP)
        if not tools:
            raise InvalidPolicy("tools.allow must be all, none or a list of tool groups")
        if groups is not None:
            unknown = sorted(set(tools) - set(groups))
            if unknown:
                raise InvalidPolicy(f"tools.allow names {', '.join(unknown)}, which this app does not know "
                                    f"(known groups: {', '.join(groups) or 'none'})")
    deny = _names(tools_section.get("deny") or [], "tools.deny", TOOL)
    return Policy(read == "workspace", write == "controlled", tools, deny)


def load_tool_groups(config):
    """The tool groups of a tool-groups.yaml (already parsed): an ordered mapping of group name
    to tool names, checked. A tool may be in several groups."""
    groups = (config or {}).get("groups") or {}
    if not isinstance(groups, dict):
        raise ValueError("tool-groups.yaml: groups must be a mapping of group name to tool names")
    result = {}
    for name, tools in groups.items():
        if not isinstance(name, str) or not GROUP.match(name):
            raise ValueError(f"tool-groups.yaml: invalid group name {name!r}")
        if not isinstance(tools, list) or not all(isinstance(t, str) and TOOL.match(t) for t in tools):
            raise ValueError(f"tool-groups.yaml: group {name} must be a list of tool names")
        result[name] = list(dict.fromkeys(tools))
    return result


def load_file(path):
    with open(path, encoding="utf-8") as handle:
        return yaml.load(handle, Loader=StrictLoader)


def describe(policy):
    tools = "none" if policy.tools is None else ("all" if policy.tools == "all" else ", ".join(policy.tools))
    deny = f"; denied: {', '.join(policy.deny)}" if policy.deny else ""
    return (f"data read: {'workspace' if policy.read else 'none'}; data write: "
            f"{'controlled' if policy.write else 'none'}; tools: {tools}{deny}")

