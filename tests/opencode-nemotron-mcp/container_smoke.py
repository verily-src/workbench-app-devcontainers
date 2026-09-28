"""Installed OpenCode + MCP integration; only model inference and wb are fake."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


APP = Path("/opt/opencode-workbench")
SMALL = "nemotron-3-nano:4b"
LARGE = "nemotron-3.5-lightning:30b"
REQUESTS = []


class ModelServer(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        REQUESTS.append(request)
        assert self.path == "/v1/chat/completions", self.path
        tools = request.get("tools", [])
        messages = request["messages"]
        user_index = max(i for i, message in enumerate(messages) if message["role"] == "user")
        answered = any(message["role"] == "tool" for message in messages[user_index + 1:])
        if tools and not answered:
            names = {tool["function"]["name"] for tool in tools}
            assert "wb_wb_status" in names and "wb_workspace_list_resources" in names, names
            delta = {"role": "assistant", "tool_calls": [{"index": 0, "id": f"call_{len(REQUESTS)}",
                     "type": "function", "function": {"name": "wb_wb_status", "arguments": "{}"}}]}
            finish = "tool_calls"
        else:
            delta = {"role": "assistant", "content": "Workspace smoke test succeeded."}
            finish = "stop"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        base = {"id": "chatcmpl-smoke", "object": "chat.completion.chunk", "created": int(time.time()), "model": request["model"]}
        try:
            for content, reason in ((delta, None), ({}, finish)):
                event = {**base, "choices": [{"index": 0, "delta": content, "finish_reason": reason}]}
                self.wfile.write(("data: " + json.dumps(event) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except BrokenPipeError:
            pass  # OpenCode may cancel a background title once the run ends.


def run(args, env, cwd):
    result = subprocess.run(args, env=env, cwd=cwd, text=True, capture_output=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def main():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        home = root / "config"
        home.mkdir()
        binaries = root / "bin"
        binaries.mkdir()
        wb = binaries / "wb"
        wb.write_text('#!/bin/sh\nprintf \'%s\\n\' \'{"status":"smoke-workspace"}\'\n')
        wb.chmod(0o755)
        env = {**os.environ, "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
               "OPENCODE_HOME": str(home), "OPENCODE_GPU_MEMORY_MIB": "81559", "OLLAMA_MODEL": "auto",
               "OLLAMA_CONTEXT_LENGTH": "65536", "OPENCODE_DISABLE_MODELS_FETCH": "true",
               "XDG_CONFIG_HOME": str(root / "xdg-config"), "XDG_DATA_HOME": str(root / "xdg-data"),
               "XDG_CACHE_HOME": str(root / "xdg-cache"), "XDG_STATE_HOME": str(root / "xdg-state")}
        assert run(["opencode", "--version"], env, root).strip() == "1.18.22"
        release = json.loads((APP / "ollama-release.json").read_text())["version"]
        version = subprocess.run(["ollama", "--version"], env=env, text=True, capture_output=True, check=True)
        assert release in version.stdout + version.stderr
        run([str(APP / "configure-opencode.sh"), "abc", str(home)], env, root)
        config_path = home / ".config/opencode/opencode.json"
        config = json.loads(config_path.read_text())
        assert config["model"] == "ollama/" + LARGE
        assert config["enabled_providers"] == ["ollama"] and "small_model" not in config
        context = home / ".claude/CLAUDE.md"
        context.parent.mkdir()
        context.write_text("Use Workbench MCP tools to inspect the workspace.\n")
        server = ThreadingHTTPServer(("127.0.0.1", 0), ModelServer)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        config["provider"]["ollama"]["options"]["baseURL"] = f"http://127.0.0.1:{server.server_port}/v1"
        config_path.write_text(json.dumps(config))
        env["OPENCODE_CONFIG"] = str(config_path)
        try:
            listing = run(["opencode", "models"], env, root).strip().splitlines()
            assert set(listing) == {"ollama/" + SMALL, "ollama/" + LARGE}, listing
            mcp = run(["opencode", "mcp", "list"], env, root)
            assert "connected" in mcp.lower(), mcp
            session = None
            for model in (LARGE, SMALL, LARGE):
                previous = len(REQUESTS)
                command = ["opencode", "run", "--format", "json", "--model", "ollama/" + model]
                if session:
                    command += ["--session", session]
                command += ["Use wb_wb_status to check the workspace, then summarize its result."]
                output = run(command, env, root)
                events = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
                completed = [e["part"] for e in events if e.get("type") == "tool_use"
                             and e["part"].get("tool") == "wb_wb_status" and e["part"]["state"]["status"] == "completed"]
                assert completed and "smoke-workspace" in completed[0]["state"]["output"], output
                session = completed[0]["sessionID"]
                current = REQUESTS[previous:]
                assert current and {r["model"] for r in current} == {model}, current
                assert any(e.get("type") == "text" for e in events), output
                print(f"PASS: installed OpenCode -> {model} -> full MCP inventory -> wb_status -> summary", flush=True)
            run(["opencode-gpu-check", "--help"], env, root)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
