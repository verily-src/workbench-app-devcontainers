#!/usr/bin/env python3
"""Who may use the app, and which of its features (the ai-policy README, "Access and features").

Two files in the image, beside ai-policy.yaml, decide it:

- access.yaml: the Workbench groups that admit a person, one per tier (alpha, beta). Either group
  admits; alpha also turns on the alpha features.
- features.yaml: each feature's minimum tier and what it controls (MCP servers, Workbench tool
  groups).

`resolve` reads the person's groups with `wb group list`, and whether the workspace is in a data
perimeter (no Gemini there), and writes the outcome to a state file
that start-services.sh, the policy compiler and the assistant UI read. `model` adds the model the
app serves there, `model-failed` records that it did not start, and `model-name` prints it.
`check` validates the two files.

Anything this app does not know (an unknown key, another version, an unknown tier) is refused, as
in ai_policy.py.
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

import yaml

from ai_policy import GROUP as TOOL_GROUP
from ai_policy import SERVER, StrictLoader

ACCESS_VERSION = 1
FEATURES_VERSION = 1
TIERS = ("beta", "alpha")  # Lowest first: alpha has every beta feature.
ACCESS_KEYS = {"version", "org", "tiers"}
FEATURE_KEYS = {"tier", "servers", "tool_groups", "description"}
FEATURE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
# A Workbench group or organization name, as the CLI shows them.
WB_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")
# The roles on a group that count as being in it.
MEMBER_ROLES = {"MEMBER", "ADMIN"}
# Where the agent-sandbox feature installs them: the image's files, never the environment's.
DEFAULT_CONFIG = "/opt/agent-sandbox/config"

DENIED_MESSAGE = ("The AI Research Assistant is in beta. It's open to a set list of users while we "
                  "test it, and general availability is coming soon.")
ERROR_MESSAGE = "We couldn't verify your access to the AI Research Assistant. Retrying."
CONFIG_ERROR_MESSAGE = ("The AI Research Assistant's access configuration is invalid, so it is off for everyone. "
                        "Ask the app's maintainers to fix it.")
NO_GPU_MESSAGE = ("This app configuration can't run the assistant's model: it needs the GPU setup "
                  "(two NVIDIA H100 80 GB GPUs), or a Nemotron endpoint on Vertex AI in the workspace's "
                  "project (the vertex-model README). Create the app with that machine type, or ask "
                  "the workspace's owner for the endpoint.")


class InvalidConfig(Exception):
    """An access.yaml or features.yaml this app cannot follow as written."""


def _unknown(mapping, known, what):
    unknown = sorted(set(map(str, mapping)) - set(known))
    if unknown:
        raise InvalidConfig(f"{what} uses {', '.join(unknown)}, which this app does not know")


def read_access(config):
    """Validates an access.yaml (already parsed) and returns {"org": ..., "groups": {tier: name}}.
    The groups are the image's alone: nothing in the environment replaces them. A tier with no
    group admits nobody."""
    if not isinstance(config, dict):
        raise InvalidConfig("access.yaml must be a YAML mapping")
    _unknown(config, ACCESS_KEYS, "access.yaml")
    if config.get("version") != ACCESS_VERSION:
        raise InvalidConfig(f"access.yaml is version {config.get('version')!r}; this app knows version {ACCESS_VERSION}")
    org = config.get("org")
    if not isinstance(org, str) or not WB_NAME.match(org):
        raise InvalidConfig(f"access.yaml: org must be a Workbench organization ID, got {org!r}")
    tiers = config.get("tiers") or {}
    if not isinstance(tiers, dict):
        raise InvalidConfig("access.yaml: tiers must be a mapping")
    _unknown(tiers, TIERS, "access.yaml tiers")
    groups = {}
    for tier in TIERS:
        entry = tiers.get(tier) or {}
        if not isinstance(entry, dict):
            raise InvalidConfig(f"access.yaml: tiers.{tier} must be a mapping")
        _unknown(entry, {"group"}, f"access.yaml tiers.{tier}")
        group = entry.get("group")
        if group is not None and (not isinstance(group, str) or not WB_NAME.match(group)):
            raise InvalidConfig(f"tiers.{tier}.group must be a Workbench group name, got {group!r}")
        if group:
            groups[tier] = group
    if not groups:
        raise InvalidConfig("access.yaml names no group: nobody could use the app")
    return {"org": org, "groups": groups}


def read_features(config, known_servers=None, known_tool_groups=None):
    """Validates a features.yaml (already parsed) and returns {name: {"tier", "servers",
    "tool_groups"}}. known_servers and known_tool_groups, when given, are what the app has; a
    feature that names something else is refused."""
    if not isinstance(config, dict):
        raise InvalidConfig("features.yaml must be a YAML mapping")
    _unknown(config, {"version", "features"}, "features.yaml")
    if config.get("version") != FEATURES_VERSION:
        raise InvalidConfig(f"features.yaml is version {config.get('version')!r}; this app knows version {FEATURES_VERSION}")
    entries = config.get("features") or {}
    if not isinstance(entries, dict):
        raise InvalidConfig("features.yaml: features must be a mapping")
    features = {}
    for name, entry in entries.items():
        if not isinstance(name, str) or not FEATURE_NAME.match(name):
            raise InvalidConfig(f"features.yaml: invalid feature name {name!r}")
        if not isinstance(entry, dict):
            raise InvalidConfig(f"features.yaml: {name} must be a mapping")
        _unknown(entry, FEATURE_KEYS, f"features.yaml {name}")
        tier = entry.get("tier")
        if tier not in TIERS:
            raise InvalidConfig(f"features.yaml: {name}.tier must be one of {', '.join(TIERS)}, got {tier!r}")
        resolved = {"tier": tier}
        for key, pattern, known in (("servers", SERVER, known_servers), ("tool_groups", TOOL_GROUP, known_tool_groups)):
            values = entry.get(key) or []
            if not isinstance(values, list) or not all(isinstance(v, str) and pattern.match(v) for v in values):
                raise InvalidConfig(f"features.yaml: {name}.{key} must be a list of names")
            if known is not None:
                unknown = sorted(set(values) - set(known))
                if unknown:
                    raise InvalidConfig(f"features.yaml: {name}.{key} names {', '.join(unknown)}, "
                                        "which this app does not have")
            resolved[key] = list(dict.fromkeys(values))
        features[name] = resolved
    return features


def tier_of(groups_json, access):
    """The person's tier from `wb group list --format=json` output (already parsed): alpha if
    they are in the alpha group, beta if in the beta group, otherwise None."""
    if not isinstance(groups_json, list):
        raise ValueError("wb group list did not answer a JSON list")
    mine = set()
    for item in groups_json:
        if not isinstance(item, dict):
            continue
        # Only the configured org's group: a group of the same name in another org admits nobody.
        if item.get("orgId") != access["org"]:
            continue
        if MEMBER_ROLES & set(item.get("currentUserRoles") or []):
            mine.add(item.get("name"))
    for tier in reversed(TIERS):
        if access["groups"].get(tier) in mine:
            return tier
    return None


def flags(features, tier):
    """{feature: on} for a tier; no tier turns everything off."""
    rank = TIERS.index(tier) if tier in TIERS else -1
    return {name: rank >= TIERS.index(f["tier"]) for name, f in features.items()}


def off_parts(features, on):
    """The servers and tool groups the features that are off control, less any a feature that is
    on also controls."""
    result = {}
    for key in ("servers", "tool_groups"):
        wanted = {v for n, f in features.items() if on[n] for v in f[key]}
        result[key] = sorted({v for n, f in features.items() if not on[n] for v in f[key]} - wanted)
    return result


def load_yaml(path):
    with open(path, encoding="utf-8") as handle:
        return yaml.load(handle, Loader=StrictLoader)


def load_config(config_dir):
    access = read_access(load_yaml(os.path.join(config_dir, "access.yaml")))
    features = read_features(load_yaml(os.path.join(config_dir, "features.yaml")))
    return access, features


def now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def write_state(path, state):
    """Writes the state file whole (a reader never sees half of it), readable by every container
    that mounts it."""
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    handle, temp = tempfile.mkstemp(dir=folder, prefix=".access.")
    with os.fdopen(handle, "w", encoding="utf-8") as out:
        json.dump(state, out, indent=2)
        out.write("\n")
    os.chmod(temp, 0o644)
    os.replace(temp, path)


def read_state(path):
    try:
        with open(path, encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, ValueError):
        return None
    return state if isinstance(state, dict) else None


def run_wb(wb, org, timeout):
    """`wb group list` as JSON. Raises RuntimeError with a short reason when it cannot answer."""
    try:
        result = subprocess.run([wb, "group", "list", "--format=json", f"--org={org}"],
                                capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"wb group list did not answer within {timeout} s") from None
    except OSError as exc:
        raise RuntimeError(f"could not run wb: {exc}") from None
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        raise RuntimeError(f"wb group list failed: {detail[-1][:200] if detail else result.returncode}")
    try:
        return json.loads(result.stdout or "[]")
    except ValueError:
        raise RuntimeError("wb group list did not answer JSON") from None


# The workspace policy that puts it in a data perimeter (VPC Service Controls), such as All of Us.
PERIMETER_POLICY = ("terra", "exfil-perimeter-constraint")
# Off inside a perimeter, and whenever the app cannot tell: these send the workspace's data to a
# model service outside the VM.
OFF_IN_PERIMETER = ("vertex_model",)


# Where the Workspace Manager lives, and where the VM says which workspace this app belongs to.
WORKBENCH_HOST = "workbench.verily.com"
APP_WORKSPACE_URL = "http://metadata.google.internal/computeMetadata/v1/instance/attributes/terra-workspace-id"


def app_workspace():
    """The ID of the workspace this app runs in, from the VM's metadata. wb's current workspace is
    not used: `wb workspace set` changes it. Raises RuntimeError when the VM does not say."""
    request = urllib.request.Request(APP_WORKSPACE_URL, headers={"Metadata-Flavor": "Google"})
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=10) as response:
            workspace = response.read().decode("utf-8").strip()
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"the VM did not name the app's workspace ({type(exc).__name__})") from None
    return workspace


def perimeter_of(wb, timeout, home=None, api=None, workspace=None):
    """The perimeter id of the app's workspace, or "" when its policies name none. Asks Workbench's
    workspace API as the person, for the workspace the VM's metadata names, at the address in wb's
    context, which must be Workbench's. `api` and `workspace` replace those two lookups, for tests.
    Raises RuntimeError when it cannot tell."""
    if api is None:
        path = os.path.join(home or os.path.expanduser("~"), ".workbench", "context.json")
        try:
            with open(path, encoding="utf-8") as handle:
                api = str(json.load(handle)["server"]["workspaceManagerUri"])
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise RuntimeError(f"no workspace API in wb's context ({type(exc).__name__})") from None
        parts = urllib.parse.urlsplit(api)
        if parts.scheme != "https" or parts.hostname != WORKBENCH_HOST or parts.port:
            raise RuntimeError(f"wb's context names a workspace API that is not on {WORKBENCH_HOST}")
    if workspace is None:
        workspace = app_workspace()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,99}", str(workspace)):
        raise RuntimeError("the VM names no workspace for this app")
    try:
        token = subprocess.run([wb, "auth", "print-access-token"], capture_output=True, text=True,
                               timeout=timeout, check=True).stdout.strip()
        request = urllib.request.Request(
            f"{api.rstrip('/')}/api/workspaces/v1/workspaceByUserFacingId/{workspace}",
            headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(request, timeout=min(timeout, 60)) as response:
            body = json.load(response)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"could not read the workspace's policies ({type(exc).__name__})") from None
    # Anything but this workspace with a list of policies is "cannot tell", never "no perimeter".
    if not isinstance(body, dict) or body.get("userFacingId") != workspace or not isinstance(body.get("policies"), list):
        raise RuntimeError("could not read the workspace's policies (unexpected answer)")
    for policy in body["policies"]:
        if isinstance(policy, dict) and (policy.get("namespace"), policy.get("name")) == PERIMETER_POLICY:
            ids = [d.get("value") for d in policy.get("additionalData") or []
                   if isinstance(d, dict) and d.get("key") == "perimeter-id"]
            return str(ids[0] if ids and ids[0] else "unnamed")
    return ""


def resolve(config_dir, wb="wb", timeout=180, perimeter=None):
    """The state for the person running this: status ok (with a tier, which may be None) or error
    (the check could not be made; everything is off, as for no tier)."""
    access, features = load_config(config_dir)
    state = {"version": 1, "checked_at": now(), "org": access["org"], "groups": access["groups"]}
    try:
        tier = tier_of(run_wb(wb, access["org"], timeout), access)
    except (RuntimeError, ValueError) as exc:
        state.update(status="error", tier=None, error=str(exc), message=ERROR_MESSAGE)
        tier = None
    else:
        state.update(status="ok", tier=tier, message="" if tier else DENIED_MESSAGE)
    on = flags(features, tier)
    try:
        state["perimeter"] = (perimeter or perimeter_of)(wb, timeout)
    except RuntimeError as exc:
        state.update(perimeter=None, perimeter_error=str(exc))
    if state["perimeter"] != "":
        for name in OFF_IN_PERIMETER:
            if name in on:
                on[name] = False
    state.update(features=on, off=off_parts(features, on))
    return state


def gpus_from_csv(text):
    """[(name, memory MiB)] from `nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits`."""
    gpus = []
    for line in (text or "").splitlines():
        name, _, memory = line.rpartition(",")
        try:
            gpus.append((name.strip(), int(float(memory.strip()))))
        except ValueError:
            continue
    return gpus


# What the local model (the vllm-model feature) needs: this many GPUs of at least this many MiB.
LOCAL_GPUS = 2
LOCAL_GPU_MIB = 79000


def choose_model(state, gpus, vllm_up, vertex_model="", vllm_model="", endpoint_model=""):
    """Which model the app serves: {"backend": "vllm" | "endpoint" | "vertex" | None, "name",
    "reason", "message"}.
    The local Nemotron model when this machine runs it (or vLLM already answers for it; the Vertex AI
    proxy on the same port does not count, vllm_up is for vLLM alone). Otherwise, only for
    a person with the vertex_model feature (alpha, and never inside a data perimeter): the Nemotron
    model a Vertex AI endpoint in the workspace's project serves (endpoint_model, found by the
    vertex-model feature), else Gemini on Vertex AI. Otherwise none."""
    fitting = [g for g in gpus if g[1] >= LOCAL_GPU_MIB]
    if vllm_up:
        return {"backend": "vllm", "name": vllm_model, "reason": "a local model already answers", "message": ""}
    if len(fitting) >= LOCAL_GPUS:
        return {"backend": "vllm", "name": vllm_model,
                "reason": f"{len(fitting)} GPUs fit the local model", "message": ""}
    have = f"{len(gpus)} GPU{'s' if len(gpus) != 1 else ''}"
    if (state.get("features") or {}).get("vertex_model"):
        if endpoint_model:
            return {"backend": "endpoint", "name": endpoint_model,
                    "reason": f"{have}; the workspace's Vertex AI endpoint serves it", "message": ""}
        if vertex_model:
            return {"backend": "vertex", "name": vertex_model, "reason": f"{have}; Gemini on Vertex AI",
                    "message": ""}
        return {"backend": None, "name": "", "reason": f"{have} and no Vertex AI model set (VERTEX_MODEL)",
                "message": NO_GPU_MESSAGE}
    return {"backend": None, "name": "", "reason": f"{have}; Vertex AI models are an alpha feature",
            "message": NO_GPU_MESSAGE}


def kept_model(previous, state):
    """The model a recheck keeps from the last state: the app started it at start, and a recheck
    (`agent-sandbox policy`) does not restart anything. A Vertex AI model (the endpoint's or
    Gemini) stays only while the person still has the vertex_model feature; otherwise there is no
    model, and the page says so."""
    if not isinstance(previous, dict) or not previous.get("backend"):
        return previous if isinstance(previous, dict) else None
    if previous["backend"] in ("vertex", "endpoint") and not (state.get("features") or {}).get("vertex_model"):
        return {"backend": None, "name": "", "reason": "Vertex AI models are an alpha feature",
                "message": NO_GPU_MESSAGE}
    return previous


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], prog="access.py")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="validate access.yaml and features.yaml")
    check.add_argument("--config-dir", default=DEFAULT_CONFIG)
    res = sub.add_parser("resolve", help="check the person's groups and write the state file")
    res.add_argument("--config-dir", default=DEFAULT_CONFIG)
    res.add_argument("--state", required=True, help="the state file to write")
    res.add_argument("--wb", default="wb", help="the Workbench CLI")
    res.add_argument("--timeout", type=int, default=180, help="seconds to wait for wb")
    mod = sub.add_parser("model", help="choose the model and add it to the state file; prints the backend")
    mod.add_argument("--state", required=True)
    mod.add_argument("--gpus", default="", help="nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits")
    mod.add_argument("--vllm-up", action="store_true", help="a local vLLM model already answers (not the Vertex AI proxy on its port)")
    mod.add_argument("--vertex-model", default="", help="the Gemini model to serve on Vertex AI")
    mod.add_argument("--vllm-model", default="", help="the model vLLM serves")
    mod.add_argument("--endpoint-model", default="",
                     help="the model a Vertex AI endpoint in the workspace's project serves, if one was found")
    failed = sub.add_parser("model-failed", help="record that the model did not start: no model, with a message for the page")
    failed.add_argument("--state", required=True)
    failed.add_argument("--message", required=True)
    name = sub.add_parser("model-name", help="print the model the app chose (for AGENT_MODEL_COMMAND)")
    name.add_argument("--state", required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "check":
            access, features = load_config(args.config_dir)
            print(f"access: org {access['org']}; groups {access['groups']}")
            for name, feature in features.items():
                print(f"feature {name}: {feature['tier']}")
            return 0
        if args.command == "resolve":
            try:
                state = resolve(args.config_dir, args.wb, args.timeout)
            except (OSError, yaml.YAMLError, InvalidConfig) as exc:
                # Fail closed where every reader looks, not only in this command's output.
                write_state(args.state, {"version": 1, "checked_at": now(), "status": "error", "tier": None,
                                         "error": f"invalid access configuration: {str(exc)[:300]}",
                                         "message": CONFIG_ERROR_MESSAGE, "features": {},
                                         "off": {"servers": [], "tool_groups": []}})
                raise
            except Exception as exc:  # noqa: BLE001 - anything else is retried (exit 2), closed
                write_state(args.state, {"version": 1, "checked_at": now(), "status": "error", "tier": None,
                                         "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                                         "message": ERROR_MESSAGE, "features": {},
                                         "off": {"servers": [], "tool_groups": []}})
                print(f"access.py: {type(exc).__name__}: {str(exc)[:300]}", file=sys.stderr)
                return 2
            model = kept_model((read_state(args.state) or {}).get("model"), state)
            if model:
                state["model"] = model
            write_state(args.state, state)
            print(f"access: {state['status']}; tier {state['tier'] or 'none'}"
                  + (f" ({state['error']})" if state.get("error") else ""))
            return 0 if state["status"] == "ok" else 2
    except (OSError, yaml.YAMLError, InvalidConfig) as exc:
        print(f"access.py: {str(exc)[:300]}", file=sys.stderr)
        return 1
    state = read_state(args.state)
    if state is None:
        print(f"access.py: no state in {args.state}; run resolve first", file=sys.stderr)
        return 1
    if args.command == "model-name":
        model = (state.get("model") or {}).get("name")
        if not model:
            reason = (state.get("model") or {}).get("message") or state.get("message")
            print(f"access.py: {reason or 'the app has not chosen a model yet; see its start log'}", file=sys.stderr)
            return 1
        print(model)
        return 0
    if args.command == "model-failed":
        state["model"] = {"backend": None, "name": "", "reason": "the model did not start", "message": args.message}
        write_state(args.state, state)
        return 0
    state["model"] = choose_model(state, gpus_from_csv(args.gpus), args.vllm_up,
                                  args.vertex_model, args.vllm_model, args.endpoint_model)
    write_state(args.state, state)
    print(state["model"]["backend"] or "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
