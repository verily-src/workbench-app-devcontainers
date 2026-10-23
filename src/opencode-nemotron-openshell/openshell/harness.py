#!/usr/bin/env python3
"""Loads and validates a harness definition (openshell/harnesses/*.yaml).

usage: harness.py <harness.yaml>     prints the validated definition as JSON

A harness is the agent program that runs in the sandbox. Everything the
framework needs to know about it is in this one file; see README, "Harness".
"""
import json
import os
import re
import sys

import yaml

NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
IMAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]{0,255}$")
# Set by the framework for every harness; a harness can't redefine them.
RESERVED_ENV = {"OLLAMA_BASE_URL", "AGENT_MODEL"}


def fail(message):
    sys.exit(f"harness: {message}")


def absolute_paths(value, what):
    if not isinstance(value, list) or not value:
        fail(f"{what} must be a non-empty list")
    for path in value:
        if not isinstance(path, str) or not path.startswith("/") or ".." in path.split("/"):
            fail(f"{what} entries must be absolute paths, got {path!r}")
    return value


def load(path):
    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        fail(f"{path} is not a YAML mapping")
    unknown = set(data) - {"name", "image", "binaries", "workdir", "env", "command", "config", "selftest"}
    if unknown:
        fail(f"unknown fields in {path}: {sorted(unknown)}")

    name = data.get("name")
    if not isinstance(name, str) or not NAME.match(name):
        fail(f"name must be lowercase letters, digits and dashes, got {name!r}")
    image = data.get("image")
    if not isinstance(image, str) or not IMAGE.match(image):
        fail(f"invalid image: {image!r}")
    command = data.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(c, str) for c in command):
        fail("command must be a non-empty list of strings")
    workdir = data.get("workdir", "/sandbox/work")
    if not isinstance(workdir, str) or not workdir.startswith("/"):
        fail(f"workdir must be an absolute path, got {workdir!r}")
    env = data.get("env") or {}
    if not isinstance(env, dict):
        fail("env must be a mapping")
    for key, value in env.items():
        if not isinstance(key, str) or not ENV_NAME.match(key) or key in RESERVED_ENV:
            fail(f"invalid or reserved env name: {key!r}")
        if not isinstance(value, (str, int, bool)):
            fail(f"env {key} must be a plain value")

    config = data.get("config")
    if config is not None:
        if not isinstance(config, dict) or set(config) != {"hook", "env"}:
            fail("config needs exactly hook and env")
        hook = str(config["hook"])
        if ".." in hook.split("/"):
            fail("config.hook must not contain ..")
        if not ENV_NAME.match(str(config["env"])) or config["env"] in RESERVED_ENV:
            fail(f"invalid config.env: {config['env']!r}")

    selftest = data.get("selftest")
    if selftest is not None:
        if not isinstance(selftest, dict) or set(selftest) - {"args", "expect"}:
            fail("selftest takes args and expect")
        if not isinstance(selftest.get("expect"), str):
            fail("selftest.expect must be a string (a grep -E pattern)")
        selftest = {"args": [str(a) for a in selftest.get("args") or []], "expect": selftest["expect"]}

    return {
        "name": name,
        "image": image,
        "binaries": absolute_paths(data.get("binaries"), "binaries"),
        "workdir": workdir,
        "env": {key: str(value) for key, value in env.items()},
        "command": command,
        "config": config,
        "selftest": selftest,
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        fail(__doc__.split("\n")[2])
    json.dump(load(sys.argv[1]), sys.stdout)
    print()
