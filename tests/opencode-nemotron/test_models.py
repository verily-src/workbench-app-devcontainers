"""Exercise the real shell scripts without GPU, network, or model downloads."""

import json
import os
from pathlib import Path
import pty
import select
import subprocess
import sys
import tempfile
import time
import unittest


APP = Path(__file__).resolve().parents[2] / "src" / "opencode-nemotron"
DEFAULT = "nemotron-3-nano:4b"
SMALL_Q8 = "nemotron-3-nano:4b-q8_0"
LARGE = "nemotron-3.5-lightning:30b"


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "config"
        self.home.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.calls = self.root / "calls.jsonl"
        self.override = self.home / ".opencode-model"
        self.config = self.home / ".config/opencode/opencode.json"
        self.env = {
            **os.environ,
            "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
            "OPENCODE_HOME": str(self.home),
            "OLLAMA_MODEL": "",
            "OLLAMA_CONTEXT_LENGTH": "65536",
            "TEST_CALLS": str(self.calls),
        }
        # Stub the external boundary, not the scripts or jq configuration logic.
        stub = f"#!{sys.executable}\n" + '''
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["TEST_CALLS"], "a") as log:
    log.write(json.dumps([name, args]) + "\\n")
if name == "ollama":
    if args[0] == "show":
        sys.exit(0 if os.environ.get("TEST_CACHED") == "1" else 1)
    if args[0] == "pull":
        sys.exit(1 if os.environ.get("TEST_PULL_FAIL") == "1" else 0)
    sys.exit("Unexpected ollama call: " + repr(args))
if name == "curl":
    url = next(a for a in args if a.startswith("http"))
    if url.endswith("/api/version"):
        print('{"version":"test"}')
    elif url.endswith("/api/show"):
        print(json.dumps({"capabilities": [] if os.environ.get("TEST_NO_TOOLS") else ["tools"]}))
    elif url.endswith("/api/generate"):
        print('{"error":"out of memory"}' if os.environ.get("TEST_LOAD_FAIL") else '{"done":true}')
    else:
        sys.exit("Unexpected URL: " + url)
elif name == "nvidia-smi":
    print("NVIDIA T4, 15360 MiB")
elif name == "id":
    # Exercise the unprivileged picker path even on root-run CI containers.
    print("1000" if args == ["-u"] else "abc")
'''
        for name in ("ollama", "curl", "nvidia-smi", "id"):
            path = self.bin / name
            path.write_text(stub)
            path.chmod(0o755)

    def run_script(self, name, *args, ok=True):
        result = subprocess.run(
            [str(APP / name), *args], env=self.env, input="",
            text=True, capture_output=True, timeout=15,
        )
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def read_calls(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines()] if self.calls.exists() else []

    def selection(self):
        return self.override.read_text().strip(), json.loads(self.config.read_text())["model"]

    def interactive(self, choice):
        master, slave = pty.openpty()
        process = subprocess.Popen(
            [str(APP / "opencode-model.sh")], env=self.env,
            stdin=slave, stdout=slave, stderr=slave,
        )
        os.close(slave)
        output = b""
        try:
            deadline = time.monotonic() + 10
            while b"Model [" not in output and time.monotonic() < deadline:
                if select.select([master], [], [], 0.2)[0]:
                    output += os.read(master, 65536)
            self.assertIn(b"Model [", output, output.decode())
            os.write(master, choice.encode() + b"\n")
            return process.wait(timeout=15)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            os.close(master)

    def test_default_environment_and_persistent_precedence(self):
        self.assertEqual(self.run_script("resolve-model.sh").stdout.strip(), DEFAULT)
        self.env["OLLAMA_MODEL"] = LARGE
        self.assertEqual(self.run_script("resolve-model.sh").stdout.strip(), LARGE)
        self.override.write_text(SMALL_Q8 + "\n")
        self.assertEqual(self.run_script("resolve-model.sh").stdout.strip(), SMALL_Q8)
        self.env["OLLAMA_MODEL"] = "prompt"
        self.assertEqual(self.run_script("resolve-model.sh").stdout.strip(), SMALL_Q8)

    def test_invalid_saved_selection_fails_before_network_access(self):
        self.override.write_text(" \n")
        self.run_script("start-ollama.sh", ok=False)
        self.assertEqual(self.read_calls(), [])

    def test_config_registers_workbench_context_and_mcp(self):
        self.run_script("configure-opencode.sh", "abc", str(self.home))
        config = json.loads(self.config.read_text())
        self.assertEqual(config["model"], "ollama/" + DEFAULT)
        self.assertEqual(config["model"], config["small_model"])
        self.assertIn(str(self.home / ".claude/CLAUDE.md"), config["instructions"])
        self.assertIn("/opt/opencode-workbench/workbench-instructions.md", config["instructions"])
        self.assertEqual(config["mcp"]["wb"], {
            "type": "local", "command": ["/opt/wb-mcp-server/wb-mcp-server"],
            "enabled": True, "timeout": 30000,
        })
        self.assertEqual(config["share"], "disabled")
        self.assertIs(config["autoupdate"], False)

    def test_context_budget_agrees_between_agent_and_server(self):
        self.env["OLLAMA_CONTEXT_LENGTH"] = "32768"
        self.run_script("opencode-model.sh", DEFAULT)
        config = json.loads(self.config.read_text())
        limit = config["provider"]["ollama"]["models"][DEFAULT]["limit"]
        self.assertEqual(limit["context"], 32768)
        args = next(args for name, args in self.read_calls() if name == "curl" and any(a.endswith("/api/generate") for a in args))
        request = json.loads(args[args.index("-d") + 1])
        self.assertEqual(request["options"]["num_ctx"], limit["context"])
        self.assertIs(request["stream"], False)

    def test_invalid_context_does_not_touch_existing_config(self):
        self.run_script("configure-opencode.sh", "abc", str(self.home))
        old_config = self.config.read_bytes()
        for value in ("0", "8192", "bad", "032768"):
            with self.subTest(value=value):
                self.env["OLLAMA_CONTEXT_LENGTH"] = value
                self.run_script("configure-opencode.sh", "abc", str(self.home), ok=False)
                self.assertEqual(self.config.read_bytes(), old_config)

    def test_picker_pulls_only_selected_model_and_persists_it(self):
        self.run_script("opencode-model.sh", SMALL_Q8)
        self.assertEqual(self.selection(), (SMALL_Q8, "ollama/" + SMALL_Q8))
        pulls = [args for name, args in self.read_calls() if name == "ollama" and args[0] == "pull"]
        self.assertEqual(pulls, [["pull", SMALL_Q8]])
        self.assertEqual(set(json.loads(self.config.read_text())["provider"]["ollama"]["models"]), {SMALL_Q8})

    def test_restart_reuses_cached_weights_without_pull(self):
        self.override.write_text(SMALL_Q8)
        self.env["TEST_CACHED"] = "1"
        self.run_script("start-ollama.sh")
        self.assertFalse(any(name == "ollama" and args[0] == "pull" for name, args in self.read_calls()))
        self.assertIn(["ollama", ["show", SMALL_Q8]], self.read_calls())

    def test_failed_download_tools_or_load_preserves_saved_selection(self):
        self.override.write_text(LARGE + "\n")
        self.run_script("configure-opencode.sh", "abc", str(self.home))
        old_config = self.config.read_bytes()
        for failure in ("TEST_PULL_FAIL", "TEST_NO_TOOLS", "TEST_LOAD_FAIL"):
            with self.subTest(failure=failure):
                self.env[failure] = "1"
                self.run_script("opencode-model.sh", SMALL_Q8, ok=False)
                self.assertEqual(self.selection(), (LARGE, "ollama/" + LARGE))
                self.assertEqual(self.config.read_bytes(), old_config)
                del self.env[failure]

    def test_deferred_startup_has_no_download_or_fake_model(self):
        self.env["OLLAMA_MODEL"] = "prompt"
        self.run_script("configure-opencode.sh", "abc", str(self.home))
        self.run_script("start-ollama.sh")
        config = json.loads(self.config.read_text())
        self.assertNotIn("model", config)
        self.assertNotIn("small_model", config)
        self.assertEqual(config["provider"]["ollama"]["models"], {})
        self.assertFalse(any(name == "ollama" for name, _ in self.read_calls()))
        self.assertFalse(self.override.exists())

    def test_noninteractive_first_launch_explains_how_to_select(self):
        self.env["OLLAMA_MODEL"] = "prompt"
        result = self.run_script("opencode-launch.sh", "run", "hello", ok=False)
        self.assertIn("opencode-model <ollama-model-tag>", result.stderr)
        self.assertEqual(self.read_calls(), [])

    def test_listing_and_invalid_choices_never_download(self):
        listing = self.run_script("opencode-model.sh", "--list").stdout
        for model in json.loads((APP / "models.json").read_text()):
            self.assertIn(model["tag"], listing)
        for args in ([], ["prompt"], ["--bad"], ["bad tag"], [DEFAULT, LARGE]):
            self.run_script("opencode-model.sh", *args, ok=False)
        self.assertEqual(self.read_calls(), [])

    def test_interactive_choice_selects_q8(self):
        self.assertEqual(self.interactive("2"), 0)
        self.assertEqual(self.selection(), (SMALL_Q8, "ollama/" + SMALL_Q8))

    def test_interactive_default_selects_nano_4b(self):
        self.assertEqual(self.interactive(""), 0)
        self.assertEqual(self.selection(), (DEFAULT, "ollama/" + DEFAULT))

    def test_interactive_cancel_or_out_of_range_preserves_selection(self):
        self.override.write_text(LARGE)
        for choice in ("q", "99", "no", "0"):
            with self.subTest(choice=choice):
                self.assertNotEqual(self.interactive(choice), 0)
                self.assertEqual(self.override.read_text(), LARGE)
        self.assertFalse(any(name == "ollama" for name, _ in self.read_calls()))


if __name__ == "__main__":
    unittest.main()
