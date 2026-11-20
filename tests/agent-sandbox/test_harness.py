"""harness.py: the harness contract every harness feature must meet."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

FEATURES = Path(__file__).resolve().parents[2] / "features" / "src"
HARNESS_PY = FEATURES / "agent-sandbox" / "harness.py"
# Every harness feature's harnesses/ folder.
HARNESS_FILES = sorted(FEATURES.glob("*/harnesses/*.yaml"))


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(HARNESS_PY), *map(str, args)], capture_output=True, text=True, check=False)


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, data) -> Path:
        path = self.dir / "h.yaml"
        path.write_text(yaml.safe_dump(data))
        return path

    def test_every_shipped_harness_is_valid(self):
        self.assertTrue(HARNESS_FILES)
        for harness in HARNESS_FILES:
            result = run(harness)
            self.assertEqual(result.returncode, 0, f"{harness}: {result.stderr}")
            data = json.loads(result.stdout)
            self.assertEqual(data["name"], harness.stem, "a harness file is named after its harness")
            hook = (data.get("config") or {}).get("hook")
            if hook and not hook.startswith("/"):
                self.assertTrue((harness.parent / hook).exists(), f"{harness}: hook {hook} is relative to the harness file")

    def test_bad_harness_is_rejected(self):
        for harness in (
            {"name": "x", "image": "i", "binaries": ["/a"], "command": ["a"], "serve": {"command": ["a"]}},
            {"name": "x", "image": "i", "binaries": ["/a"], "command": ["a"], "serve": {"command": [], "port": 4096}},
            {"name": "x", "image": "i", "binaries": ["/a"], "command": ["a"], "serve": {"command": ["a"], "port": 80}},
            {"name": "Bad Name", "image": "i", "binaries": ["/a"], "command": ["a"]},
            {"name": "x", "image": "i", "binaries": ["relative/path"], "command": ["a"]},
            {"name": "x", "image": "i", "binaries": ["/a"], "command": []},
            {"name": "x", "image": "i", "binaries": ["/a"], "command": ["a"], "env": {"AGENT_MODEL": "x"}},
            {"name": "x", "image": "i", "binaries": ["/a"], "command": ["a"], "config": {"hook": "../x", "env": "C"}},
            {"name": "x", "image": "i", "binaries": ["/a"], "command": ["a"], "surprise": 1},
        ):
            result = run(self.write(harness))
            self.assertNotEqual(result.returncode, 0, harness)

    def test_harness_json_is_what_agent_sandbox_reads(self):
        result = run(FEATURES / "opencode-harness" / "harnesses" / "opencode.yaml")
        data = json.loads(result.stdout)
        self.assertEqual(data["command"], ["opencode"])
        self.assertEqual(data["config"], {"hook": "opencode-config.sh", "env": "OPENCODE_CONFIG_CONTENT"})
        self.assertEqual(data["serve"]["port"], 4096)
        self.assertEqual(data["binaries"], ["/opt/opencode/.opencode/bin/opencode"])


if __name__ == "__main__":
    unittest.main()
