#!/usr/bin/env python3
"""Exercise the local OpenAI endpoint with the complete Workbench tool inventory.

Only wb_status may be executed, regardless of what the model requests. This
checks the backend used by /model; the interactive picker still needs a spot check.
"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request


APP = Path(__file__).resolve().parent
URL = "http://127.0.0.1:11434"
SAFE_TOOL = "wb_wb_status"


def api(path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(URL + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=600) as response:
        result = json.load(response)
    if result.get("error"):
        raise RuntimeError(str(result["error"]))
    return result


def mcp(command, method, params=None):
    # The shared server supports independent stdio sessions; no HTTP daemon or
    # external MCP client package is needed for discovery or a read-only call.
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "opencode-gpu-check", "version": "1"},
        }},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": method, "params": params or {}},
    ]
    proc = subprocess.run(command, input="".join(json.dumps(r) + "\n" for r in requests),
                          text=True, capture_output=True, timeout=60, check=True)
    replies = {r["id"]: r for r in map(json.loads, proc.stdout.splitlines()) if "id" in r}
    for request_id in (1, 2):
        if request_id not in replies or "error" in replies[request_id]:
            raise RuntimeError(f"MCP {method} failed: {replies.get(request_id)}")
    result = replies[2]["result"]
    if result.get("isError"):
        raise RuntimeError("MCP wb_status failed; check wb authentication and workspace selection.")
    if result.get("nextCursor"):
        raise RuntimeError("Paginated tool discovery is not supported by this check; refusing a partial inventory.")
    return result


def residency(model, context):
    loaded = api("/api/ps").get("models", [])
    if len(loaded) != 1:
        raise RuntimeError(f"Expected one loaded model, found {len(loaded)}")
    state = loaded[0]
    if model not in (state.get("name"), state.get("model")):
        raise RuntimeError(f"Selected {model}, but Ollama reports {state.get('name')}")
    if not state.get("size") or state.get("size_vram") != state["size"]:
        raise RuntimeError(f"{model} is not 100% GPU-resident")
    if state.get("context_length") != context:
        raise RuntimeError(f"{model} context is {state.get('context_length')}, expected {context}")
    return {key: state.get(key) for key in ("digest", "size", "size_vram", "context_length")}


def trial(model, tools, instructions, command, context):
    messages = [
        {"role": "system", "content": instructions},
        {"role": "user", "content":
         "Check my Workbench workspace status by calling wb_wb_status exactly once with no arguments. "
         "After receiving its result, briefly summarize it. Do not call any other tool."},
    ]
    start = time.monotonic()
    request = {"model": model, "messages": messages, "tools": tools, "stream": False, "max_tokens": 8192}
    first = api("/v1/chat/completions", request)
    choice = first["choices"][0]
    message = choice["message"]
    calls = message.get("tool_calls") or []
    if len(calls) != 1 or calls[0].get("function", {}).get("name") != SAFE_TOOL:
        raise RuntimeError("Expected exactly one wb_wb_status call; no requested tools were executed.")
    if choice.get("finish_reason") not in ("stop", "tool_calls"):
        raise RuntimeError(f"Tool-call generation ended with {choice.get('finish_reason')}")
    if json.loads(calls[0]["function"]["arguments"]) != {}:
        raise RuntimeError("wb_wb_status arguments must be empty; tool was not executed.")
    status = residency(model, context)
    result = mcp(command, "tools/call", {"name": "wb_status", "arguments": {}})
    messages.extend([message, {"role": "tool", "tool_call_id": calls[0]["id"], "content": json.dumps(result)}])
    last = api("/v1/chat/completions", request)["choices"][0]
    if last.get("finish_reason") != "stop" or last["message"].get("tool_calls") or not last["message"].get("content", "").strip():
        raise RuntimeError("Model did not return a completed text summary after the tool result.")
    residency(model, context)
    return {"seconds": round(time.monotonic() - start, 2), "tool": SAFE_TOOL, **status}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=5, help="Trials per model (default: 5; models alternate)")
    parser.add_argument("--report", type=Path, help="New JSON report path; existing files are never overwritten")
    args = parser.parse_args()
    if args.repeats < 2:
        parser.error("--repeats must be at least 2 to exercise switching in both directions")
    home = Path(os.environ.get("OPENCODE_HOME", "/config"))
    config = json.loads((home / ".config/opencode/opencode.json").read_text())
    models = list(config["provider"]["ollama"]["models"])
    if not models or config.get("enabled_providers") != ["ollama"]:
        raise RuntimeError("Run the updated startup scripts first: expected local-only, populated model configuration.")
    expected = json.loads(subprocess.check_output([str(APP / "available-models.sh")], text=True))
    if not {entry["tag"] for entry in expected}.issubset(models):
        raise RuntimeError("OpenCode configuration omits GPU-compatible catalog models; rerun startup.")
    listing = subprocess.check_output(["opencode", "models", "ollama"], text=True, timeout=60)
    if any("ollama/" + model not in listing.splitlines() for model in models):
        raise RuntimeError("The installed OpenCode does not list all configured models.")
    command = config["mcp"]["wb"]["command"]
    inventory = mcp(command, "tools/list")["tools"]
    tools = [{"type": "function", "function": {
        "name": "wb_" + tool["name"], "description": tool.get("description", ""),
        "parameters": tool["inputSchema"],
    }} for tool in inventory]
    if not any(tool["function"]["name"] == SAFE_TOOL for tool in tools):
        raise RuntimeError("Workbench MCP did not expose wb_status")
    instructions = "\n\n".join(Path(path).read_text() for path in config["instructions"])
    release = json.loads((APP / "ollama-release.json").read_text())["version"]
    version = api("/api/version")["version"]
    if version != release:
        raise RuntimeError(f"Expected Ollama {release}, found {version}")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    report_path = args.report or home / f"opencode-gpu-check-{stamp}.json"
    report = {"ollama_version": version, "tool_count": len(tools), "models": models,
              "tool_schema_sha256": hashlib.sha256(json.dumps(tools, sort_keys=True).encode()).hexdigest(),
              "instructions_sha256": hashlib.sha256(instructions.encode()).hexdigest(),
              "results": [], "passed": False}
    # Reserve the output path before running requests. Results omit prompts,
    # workspace data, and generated content, but retain timings and model digests.
    with report_path.open("x") as output:
        try:
            print(f"Testing {len(models)} model(s), {len(tools)} MCP tools, {args.repeats} trials each.", flush=True)
            for repeat in range(args.repeats):
                for model in models:
                    entry = {"model": model, "trial": repeat + 1}
                    try:
                        context = config["provider"]["ollama"]["models"][model]["limit"]["context"]
                        entry.update(trial(model, tools, instructions, command, context), passed=True)
                    except Exception as exc:
                        entry.update(passed=False, error=str(exc))
                    report["results"].append(entry)
                    print(f"{model} trial {repeat + 1}: {'PASS' if entry['passed'] else 'FAIL: ' + entry['error']}", flush=True)
            report["passed"] = all(result["passed"] for result in report["results"])
        finally:
            # Restore the configured default without rewriting user selection.
            default = config["model"].removeprefix("ollama/")
            env = {**os.environ, "OLLAMA_CONTEXT_LENGTH": str(config["provider"]["ollama"]["models"][default]["limit"]["context"])}
            try:
                subprocess.run([str(APP / "validate-model.sh"), default], env=env, timeout=630, check=True)
            except (OSError, subprocess.SubprocessError) as exc:
                report["passed"] = False
                report["restore_error"] = f"Default model failed GPU preflight: {exc}"
            json.dump(report, output, indent=2)
            output.write("\n")
    print(f"Report: {report_path}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (Exception, KeyboardInterrupt) as error:
        print(f"GPU acceptance check failed: {error}", file=sys.stderr)
        sys.exit(1)
